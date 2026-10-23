"""Relocate the MN88553H driver's I2C address by patching its immediates.

The vendor driver picks the chip's sub-address from a sub-bus index:

    tuner_hwl_regwrite  : sub-bus 0/1/2 -> I2C byte 0xe0 / 0xe2 / 0xe4

That is 7-bit 0x70 / 0x71 / 0x72.  On the TVplus GO prototype the same chip
answers at byte 0x60 / 0x62 / 0x64 (7-bit 0x30 / 0x31 / 0x32), i.e. an address
strap 0x80 lower, so every vendor write misses with a NAK (result 0x15) and
the driver gives up after its first probe.

Because the addresses are plain MOVZ immediates, the fix is 18 instructions:
in the five tuner_hwl_* accessors, rewrite

    mov wN, #0xe0 -> #0x60
    mov wN, #0xe2 -> #0x62
    mov wN, #0xe4 -> #0x64

Nothing else in the image matches those immediates inside the tuner code, so
the patch is deterministic and verifiable.

    python tools/patch_mn_addr.py IN.so OUT.so [--delta 0x80]
"""
from __future__ import annotations

import argparse
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs
except ImportError:  # pragma: no cover
    Cs = None

# MOVZ Wd,#imm16 : 0b0101_0010_1 hw imm16 Rd, hw = 0
MOVZ_W = 0x52800000
MOVZ_MASK = 0xFF800000

FUNCTIONS = [
    "tuner_hwl_regwrite",
    "tuner_hwl_regread",
    "tuner_hwl_regnwrite",
    "tuner_hwl_regnread",
    "tuner_hwl_relev",
]
ADDRESSES = (0xE0, 0xE2, 0xE4)


class Elf32Text:
    """Just enough ELF to find .text and the tuner symbols."""

    def __init__(self, data):
        self.data = data
        e_shoff, = struct.unpack_from("<Q", data, 0x28)
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x3A)
        self.sections = []
        for i in range(e_shnum):
            off = e_shoff + i * e_shentsize
            name, typ, flags, addr, offset, size, link, info, align, entsize = \
                struct.unpack_from("<IIQQQQIIQQ", data, off)
            self.sections.append(dict(name_idx=name, type=typ, addr=addr,
                                      offset=offset, size=size, link=link))
        shstr = self.sections[e_shstrndx]
        base = shstr["offset"]
        for s in self.sections:
            end = data.index(b"\x00", base + s["name_idx"])
            s["name"] = data[base + s["name_idx"]:end].decode("latin1")
        self.symbols = {}
        sym = self.section(".dynsym")
        strtab = self.sections[sym["link"]]
        for i in range(sym["size"] // 24):
            off = sym["offset"] + i * 24
            n, info, other, shndx, value, size = struct.unpack_from("<IBBHQQ", data, off)
            if not n or not value:
                continue
            end = data.index(b"\x00", strtab["offset"] + n)
            name = data[strtab["offset"] + n:end].decode("latin1")
            self.symbols[name] = (value, size)

    def section(self, name):
        for s in self.sections:
            if s["name"] == name:
                return s
        raise SystemExit("no %s section - not an ELF .so?" % name)

    def offset(self, va):
        for s in self.sections:
            if s["addr"] and s["addr"] <= va < s["addr"] + s["size"]:
                return s["offset"] + (va - s["addr"])
        return None


def encode_movz(reg, imm16):
    return MOVZ_W | ((imm16 & 0xFFFF) << 5) | (reg & 0x1F)


def find_sites(data):
    """Locate every load of a tuner address immediate inside the accessors.

    0xe2 / 0xe4 are not bitmask immediates so the compiler emits MOVZ for
    them, but 0xe0 is, so it shows up as `orr wN, wzr, #0xe0`.  Both are
    matched here and both get rewritten to MOVZ, which is always encodable
    and has identical semantics (no flags, zero-extended).
    """
    if Cs is None:
        raise SystemExit("capstone is required to locate the sites")
    elf = Elf32Text(data)
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    sites = []
    for name in FUNCTIONS:
        value, size = elf.symbols[name]
        start = elf.offset(value)
        for ins in md.disasm(bytes(data[start:start + size]), value):
            if ins.mnemonic not in ("mov", "movz", "orr"):
                continue
            parts = [x.strip() for x in ins.op_str.split(",")]
            if len(parts) < 2 or not re.fullmatch(r"w\d+", parts[0]):
                continue
            last = parts[-1]
            if not last.startswith("#0x"):
                continue
            imm = int(last[3:], 16)
            if imm in ADDRESSES and ins.address == ins.address:
                reg = int(parts[0][1:])
                sites.append((elf.offset(ins.address), ins.address, ins.mnemonic, reg, imm))
    return elf, sites


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("target")
    ap.add_argument("--delta", type=lambda s: int(s, 0), default=0x80)
    a = ap.parse_args(argv)

    data = bytearray(open(a.source, "rb").read())
    elf, sites = find_sites(data)
    if not sites:
        raise SystemExit("no address immediates found - already patched?")

    print("%s: %d address loads" % (os.path.basename(a.source), len(sites)))
    for off, va, mnemonic, reg, imm in sites:
        new = encode_movz(reg, imm - a.delta)
        struct.pack_into("<I", data, off, new)
        print("  %08x  w%-2d #0x%02x -> #0x%02x   (%s)" % (va, reg, imm, imm - a.delta, mnemonic))

    # verify by re-reading with capstone, if available
    if Cs is not None:
        text = elf.section(".text")
        md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        bad = 0
        for off, va, mnemonic, reg, imm in sites:
            got = list(md.disasm(bytes(data[off:off + 4]), va))
            want = "w%d, #0x%x" % (reg, imm - a.delta)
            if not got or got[0].op_str.replace(" ", "") != want.replace(" ", ""):
                print("  VERIFY FAILED at %08x: %s" % (va, got[0].op_str if got else "?"))
                bad += 1
        if bad:
            raise SystemExit("%d sites did not verify" % bad)
        print("verified %d sites with capstone" % len(sites))

    open(a.target, "wb").write(data)
    print("wrote %s (%d bytes)" % (a.target, len(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
