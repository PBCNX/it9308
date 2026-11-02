"""8051 / MCS-51 disassembler for ITE (IT930x) firmware images.

The IT9303 core runs the tuner driver as 8051 code, shipped inside the ITE
"0x03" record container.  Capstone has no 8051 backend, and there is no
radare2 on the analysis box, so this module carries its own decoder.

Container format (reverse engineered from libendeavour-*.so, validated by the
chain walk below):

    offset 0            0x03          block tag
    offset 1..2         ?? ??         unknown (constant 00 00)
    offset 3            m             1..16 sub records
    offset 4 + 3j       addr_hi
    offset 5 + 3j       addr_lo
    offset 6 + 3j       len
    offset 4 + 3m       payloads, concatenated in record order

Records are sparse and need not end on an instruction boundary, so the image
is rebuilt as an address -> byte map and disassembled by recursive descent.

Usage:
    python dis8051.py FILE [--base 0x4100] [--container ite|raw|auto]
                            [--listing OUT] [--stats] [--scan movx]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

# --------------------------------------------------------------------------
# container
# --------------------------------------------------------------------------


def ite_records(data: bytes):
    """Walk the 0x03 record chain.  Returns (records, consumed) or (None, 0)."""
    off = 0
    records = []
    while off + 4 <= len(data) and data[off] == 0x03:
        m = data[off + 3]
        if not 1 <= m <= 16 or off + 4 + 3 * m > len(data):
            return None, 0
        spans = []
        total = 4 + 3 * m
        for j in range(m):
            hi = data[off + 4 + 3 * j]
            lo = data[off + 5 + 3 * j]
            ln = data[off + 6 + 3 * j]
            if ln == 0:
                return None, 0
            spans.append((hi << 8 | lo, ln))
            total += ln
        if off + total > len(data):
            return None, 0
        pos = off + 4 + 3 * m
        for addr, ln in spans:
            records.append((addr, data[pos : pos + ln]))
            pos += ln
        off += total
    return records, off


def load_image(path: str):
    data = open(path, "rb").read()
    records, consumed = ite_records(data)
    if records and consumed == len(data):
        image = {}
        for addr, blob in records:
            for i, b in enumerate(blob):
                image[addr + i] = b
        return image, "ite(%d records, base 0x%04x)" % (len(records), min(image))
    return None, "raw"


def image_bytes(image):
    lo, hi = min(image), max(image)
    return bytes(image.get(a, 0xFF) for a in range(lo, hi + 1))


# --------------------------------------------------------------------------
# decode table
# --------------------------------------------------------------------------

# operand kinds and how many extra bytes each consumes
SIZE = {
    "direct": 1, "#imm8": 1, "rel": 1, "bit": 1, "addr16": 2,
    "#imm16": 2, "A,#imm8": 1, "C,bit": 1, "bit,rel": 2,
    "direct,#imm8": 2, "direct,direct": 2, "A,direct,rel": 2,
    "direct,rel": 2, "Rn,#imm8,rel": 2, "@Ri,#imm8,rel": 2,
}


def _src(ops: str) -> int:
    return sum(SIZE.get(o.strip(), 0) for o in ops.split(","))


# (mnemonic, operand string) for every non-regular opcode
FIXED = {
    0x00: ("NOP", ""), 0x02: ("LJMP", "addr16"), 0x03: ("RR", "A"),
    0x04: ("INC", "A"),
    0x05: ("INC", "direct"), 0x06: ("INC", "@R0"), 0x07: ("INC", "@R1"),
    0x10: ("JBC", "bit,rel"), 0x12: ("LCALL", "addr16"), 0x13: ("RRC", "A"),
    0x14: ("DEC", "A"), 0x15: ("DEC", "direct"),
    0x16: ("DEC", "@R0"), 0x17: ("DEC", "@R1"),
    0x20: ("JB", "bit,rel"), 0x22: ("RET", ""), 0x23: ("RL", "A"),
    0x24: ("ADD", "A,#imm8"), 0x25: ("ADD", "A,direct"),
    0x26: ("ADD", "A,@R0"), 0x27: ("ADD", "A,@R1"),
    0x30: ("JNB", "bit,rel"), 0x32: ("RETI", ""), 0x33: ("RLC", "A"),
    0x34: ("ADDC", "A,#imm8"), 0x35: ("ADDC", "A,direct"),
    0x36: ("ADDC", "A,@R0"), 0x37: ("ADDC", "A,@R1"),
    0x40: ("JC", "rel"), 0x42: ("ORL", "direct,A"),
    0x43: ("ORL", "direct,#imm8"), 0x44: ("ORL", "A,#imm8"),
    0x45: ("ORL", "A,direct"), 0x46: ("ORL", "A,@R0"), 0x47: ("ORL", "A,@R1"),
    0x50: ("JNC", "rel"), 0x52: ("ANL", "direct,A"),
    0x53: ("ANL", "direct,#imm8"), 0x54: ("ANL", "A,#imm8"),
    0x55: ("ANL", "A,direct"), 0x56: ("ANL", "A,@R0"), 0x57: ("ANL", "A,@R1"),
    0x60: ("JZ", "rel"), 0x62: ("XRL", "direct,A"),
    0x63: ("XRL", "direct,#imm8"), 0x64: ("XRL", "A,#imm8"),
    0x65: ("XRL", "A,direct"), 0x66: ("XRL", "A,@R0"), 0x67: ("XRL", "A,@R1"),
    0x70: ("JNZ", "rel"), 0x72: ("ORL", "C,bit"), 0x73: ("JMP", "@A+DPTR"),
    0x74: ("MOV", "A,#imm8"), 0x75: ("MOV", "direct,#imm8"),
    0x76: ("MOV", "@R0,#imm8"), 0x77: ("MOV", "@R1,#imm8"),
    0x80: ("SJMP", "rel"), 0x82: ("ANL", "C,bit"),
    0x83: ("MOVC", "A,@A+PC"), 0x84: ("DIV", "AB"),
    0x85: ("MOV", "direct,direct"),
    0x86: ("MOV", "direct,@R0"), 0x87: ("MOV", "direct,@R1"),
    0x90: ("MOV", "DPTR,#imm16"), 0x92: ("MOV", "bit,C"),
    0x93: ("MOVC", "A,@A+DPTR"), 0x94: ("SUBB", "A,#imm8"),
    0x95: ("SUBB", "A,direct"), 0x96: ("SUBB", "A,@R0"),
    0x97: ("SUBB", "A,@R1"),
    0xA0: ("ORL", "C,/bit"), 0xA2: ("MOV", "C,bit"), 0xA3: ("INC", "DPTR"),
    0xA4: ("MUL", "AB"), 0xA5: ("DB", "0xa5"),
    0xA6: ("MOV", "@R0,direct"), 0xA7: ("MOV", "@R1,direct"),
    0xB0: ("ANL", "C,/bit"), 0xB2: ("CPL", "bit"), 0xB3: ("CPL", "C"),
    0xB4: ("CJNE", "A,#imm8,rel"), 0xB5: ("CJNE", "A,direct,rel"),
    0xB6: ("CJNE", "@R0,#imm8,rel"), 0xB7: ("CJNE", "@R1,#imm8,rel"),
    0xC0: ("PUSH", "direct"), 0xC2: ("CLR", "bit"), 0xC3: ("CLR", "C"),
    0xC4: ("SWAP", "A"), 0xC5: ("XCH", "A,direct"),
    0xC6: ("XCH", "A,@R0"), 0xC7: ("XCH", "A,@R1"),
    0xD0: ("POP", "direct"), 0xD2: ("SETB", "bit"), 0xD3: ("SETB", "C"),
    0xD4: ("DA", "A"), 0xD5: ("DJNZ", "direct,rel"),
    0xD6: ("XCHD", "A,@R0"), 0xD7: ("XCHD", "A,@R1"),
    0xE0: ("MOVX", "A,@DPTR"), 0xE2: ("MOVX", "A,@R0"),
    0xE3: ("MOVX", "A,@R1"), 0xE4: ("CLR", "A"), 0xE5: ("MOV", "A,direct"),
    0xE6: ("MOV", "A,@R0"), 0xE7: ("MOV", "A,@R1"),
    0xF0: ("MOVX", "@DPTR,A"), 0xF2: ("MOVX", "@R0,A"), 0xF3: ("MOVX", "@R1,A"),
    0xF4: ("CPL", "A"), 0xF5: ("MOV", "direct,A"),
    0xF6: ("MOV", "@R0,A"), 0xF7: ("MOV", "@R1,A"),
}

# Register banks: op 0x08..0x0F INC Rn, 0x18.. DEC Rn, ... table of (base, mnemonic)
RANGE = [
    (0x08, "INC", "Rn"), (0x18, "DEC", "Rn"), (0x28, "ADD", "A,Rn"),
    (0x38, "ADDC", "A,Rn"), (0x48, "ORL", "A,Rn"), (0x58, "ANL", "A,Rn"),
    (0x68, "XRL", "A,Rn"), (0x78, "MOV", "Rn,#imm8"),
    (0x88, "MOV", "direct,Rn"), (0x98, "SUBB", "A,Rn"),
    (0xA8, "MOV", "Rn,direct"), (0xB8, "CJNE", "Rn,#imm8,rel"),
    (0xC8, "XCH", "A,Rn"), (0xD8, "DJNZ", "Rn,rel"),
    (0xE8, "MOV", "A,Rn"), (0xF8, "MOV", "Rn,A"),
]

SFR_NAMES = {
    0x80: "P0", 0x81: "SP", 0x82: "DPL", 0x83: "DPH", 0x87: "PCON",
    0x88: "TCON", 0x89: "TMOD", 0x8A: "TL0", 0x8B: "TL1", 0x8C: "TH0",
    0x8D: "TH1", 0x90: "P1", 0x98: "SCON", 0x99: "SBUF", 0xA0: "P2",
    0xA8: "IE", 0xB0: "P3", 0xD0: "PSW", 0xE0: "ACC", 0xF0: "B",
}

# 8051 reset/vector table bit names (bit address -> mnemonic)
BIT_NAMES = {
    0x88: "IT0", 0x89: "IE0", 0x8A: "IT1", 0x8B: "IE1", 0x8C: "TR0",
    0x8D: "TF0", 0x8E: "TR1", 0x8F: "TF1",
    0x98: "RI", 0x99: "TI", 0x9A: "RB8", 0x9B: "TB8", 0x9C: "REN",
    0x9D: "SM2", 0x9E: "SM1", 0x9F: "SM0",
    0xA8: "EX0", 0xA9: "ET0", 0xAA: "EX1", 0xAB: "ET1", 0xAC: "ES",
    0xAF: "EA",
    0xB0: "RXD", 0xB1: "TXD", 0xB2: "INT0", 0xB3: "INT1", 0xB4: "T0",
    0xB5: "T1", 0xB6: "WR", 0xB7: "RD",
    0xD7: "CY", 0xD6: "AC", 0xD5: "F0", 0xD4: "RS1", 0xD3: "RS0",
    0xD2: "OV", 0xD1: "F1", 0xD0: "P",
}

AJMP_ACALL = {0x01, 0x11, 0x21, 0x31, 0x41, 0x51, 0x61, 0x71, 0x81, 0x91,
              0xA1, 0xB1, 0xC1, 0xD1, 0xE1, 0xF1}


def bit_name(addr: int) -> str:
    if addr in BIT_NAMES:
        return BIT_NAMES[addr]
    return "0x%02x.%d" % (addr, 0)


def fmt_direct(addr: int, bit: bool) -> str:
    if bit:
        if addr in BIT_NAMES:
            return BIT_NAMES[addr]
        if addr < 0x80:
            return "0x%02x.%d" % (addr >> 3, addr & 7)
        return "0x%02x.%d" % (addr & 0xF8, addr & 7)
    if addr in SFR_NAMES:
        return SFR_NAMES[addr]
    return "0x%02x" % addr


def decode(buf: bytes, off: int, base: int = 0):
    """Decode one instruction at buffer offset off (absolute address off+base)."""
    if off >= len(buf):
        return None
    pc = off + base
    op = buf[off]
    if op in FIXED:
        mn, ops = FIXED[op]
    elif op in AJMP_ACALL:
        # AJMP lives on even high nibbles, ACALL on odd ones
        kind = "AJMP" if (op >> 4) % 2 == 0 else "ACALL"
        return _ajmp(buf, off, base, op, kind)
    else:
        for rb, mn, ops in RANGE:
            if rb <= op < rb + 8:
                ops = ops.replace("Rn", "R%d" % (op - rb))
                break
        else:
            return 1, "DB 0x%02x" % op

    n = 1 + _src(ops)
    if off + n > len(buf):
        return None
    body = buf[off + 1 : off + n]
    args = []
    i = 0
    for part in ops.split(","):
        part = part.strip()
        if part == "direct":
            args.append(fmt_direct(body[i], False)); i += 1
        elif part == "bit":
            args.append(fmt_direct(body[i], True)); i += 1
        elif part == "#imm8":
            args.append("#0x%02x" % body[i]); i += 1
        elif part == "#imm16":
            args.append("#0x%04x" % (body[i] << 8 | body[i + 1])); i += 2
        elif part == "addr16":
            args.append("0x%04x" % (body[i] << 8 | body[i + 1])); i += 2
        elif part == "rel":
            tgt = pc + n + _s8(body[i]); i += 1
            args.append("0x%04x" % tgt)
        elif part == "C,bit":
            args.append("C"); args.append(fmt_direct(body[i], True)); i += 1
        elif part == "bit,rel":
            args.append(fmt_direct(body[i], True)); i += 1
            args.append("0x%04x" % (pc + n + _s8(body[i]))); i += 1
        elif part == "@A+DPTR":
            args.append("@A+DPTR")
        elif part == "@A+PC":
            args.append("@A+PC")
        else:
            args.append(part)
    text = mn + (" " + ",".join(args) if args else "")
    return n, text


def _s8(b: int) -> int:
    return b - 256 if b > 127 else b


def _ajmp(buf, off, base, op, kind):
    if off + 2 > len(buf):
        return None
    pc = off + base
    imm = buf[off + 1]
    page = (pc + 2) & 0xF800
    tgt = page | ((op >> 5) & 7) << 8 | imm
    return 2, "%s 0x%04x" % (kind, tgt)


# --------------------------------------------------------------------------
# recursive descent
# --------------------------------------------------------------------------


def branch_target(text: str):
    """Extract the last numeric operand (the branch target), if any."""
    parts = text.split(None, 1)
    if len(parts) < 2:
        return None
    for tok in parts[1].split(",")[::-1]:
        tok = tok.strip()
        if tok.startswith("0x") and len(tok) == 6:
            try:
                return int(tok, 16)
            except ValueError:
                return None
    return None


def descend(image, entries):
    lo, hi = min(image), max(image)
    buf = image_bytes(image)
    base = lo
    code = {}
    work = [e for e in entries if lo <= e <= hi]
    while work:
        pc = work.pop()
        while lo <= pc <= hi and pc in image:
            if pc in code:
                break
            d = decode(buf, pc - base, base)
            if d is None:
                break
            n, text = d
            code[pc] = (n, text)
            mn = text.split()[0]
            follow = True
            if mn in ("SJMP", "AJMP", "LJMP", "JMP"):
                follow = False
                t = branch_target(text)
                if t is not None and lo <= t <= hi:
                    work.append(t)
            elif mn in ("RET", "RETI"):
                follow = False
            elif mn in ("JZ", "JNZ", "JC", "JNC", "JB", "JNB", "JBC"):
                t = branch_target(text)
                if t is not None and lo <= t <= hi:
                    work.append(t)
            elif mn in ("DJNZ", "CJNE"):
                t = branch_target(text)
                if t is not None and lo <= t <= hi:
                    work.append(t)
            elif mn in ("ACALL", "LCALL"):
                t = branch_target(text)
                if t is not None and lo <= t <= hi:
                    work.append(t)
            if not follow:
                break
            pc += n
    return code, buf, base


def linear(image, start, stop=None):
    """Sweep instructions across every mapped region at or after start."""
    lo, hi = min(image), max(image)
    buf = image_bytes(image)
    stop = hi if stop is None else stop
    code = {}
    regions = []
    run_start = prev = None
    for a in sorted(image):
        if a > stop:
            break
        if run_start is None:
            run_start = a
        elif a != prev + 1:
            regions.append((run_start, prev))
            run_start = a
        prev = a
    if run_start is not None:
        regions.append((run_start, prev))
    for r0, r1 in regions:
        pc = max(r0, start)
        while pc <= r1:
            d = decode(buf, pc - lo, lo)
            if d is None:
                break
            code[pc] = d
            pc += d[0]
    return code, buf, lo


def call_targets(code, lo, hi):
    tgts = {}
    for pc in sorted(code):
        text = code[pc][1]
        if text.startswith(("LCALL", "ACALL", "LJMP", "AJMP")):
            t = branch_target(text)
            if t is not None and lo <= t <= hi:
                tgts.setdefault(t, []).append(pc)
    return tgts


def validate(code):
    """How many branch/call targets land on a decoded instruction?"""
    starts = set(code)
    ok = miss = 0
    for pc in code:
        text = code[pc][1]
        if text.startswith(("LCALL", "ACALL", "LJMP", "AJMP", "SJMP", "JZ",
                            "JNZ", "JC", "JNC", "JB", "JNB", "JBC", "DJNZ",
                            "CJNE")):
            t = branch_target(text)
            if t is None:
                continue
            if t in starts:
                ok += 1
            else:
                miss += 1
    return ok, miss


def listing(code, buf, base, out):
    lo, hi = min(code), max(code)
    prev_end = None
    for pc in sorted(code):
        n, text = code[pc]
        if prev_end is not None and pc != prev_end:
            out.write("%04x            ; ---- gap ----\n" % prev_end)
        raw = buf[pc - base : pc - base + n].hex()
        out.write("%04x  %-10s %s\n" % (pc, raw, text))
        prev_end = pc + n


def scan_movx(code, buf, base):
    """Pair 'MOV DPTR,#imm16' with the following access to @DPTR."""
    hits = []
    order = sorted(code)
    for i, pc in enumerate(order):
        n, text = code[pc]
        if text.startswith("MOV DPTR,#"):
            dptr = int(text.split("#0x")[1], 16)
            for j in range(i + 1, min(i + 6, len(order))):
                p2 = order[j]
                t2 = code[p2][1]
                if t2.startswith("MOVX"):
                    hits.append((pc, dptr, t2, p2, j - i))
                    break
                if t2.split()[0] in ("RET", "RETI") or t2.startswith("MOV DPTR,#"):
                    break
    return hits


def find_entries(image, buf, base):
    """Vector table at the image start plus every LJMP/ACALL target."""
    lo, hi = min(image), max(image)
    entries = [lo]
    for pc in range(lo, min(lo + 0x60, hi)):
        d = decode(buf, pc - base, base)
        if d and d[1].startswith("LJMP"):
            t = branch_target(d[1])
            if t is not None and lo <= t <= hi:
                entries.append(t)
    return entries


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--base", help="load raw file at this address")
    ap.add_argument("--container", choices=("ite", "raw", "auto"), default="auto")
    ap.add_argument("--entry", help="comma separated entry addresses (default: every"
                                    " LJMP vector in the first 0x60 bytes)")
    ap.add_argument("--linear", help="linear sweep start address")
    ap.add_argument("--listing", help="write full listing here")
    ap.add_argument("--scan", choices=("movx", "calls"), default=None)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args(argv)

    image, how = load_image(a.file)
    if image is None or a.container == "raw":
        raw = open(a.file, "rb").read()
        base = int(a.base, 0) if a.base else 0
        image = {base + i: b for i, b in enumerate(raw)}
        how = "raw at 0x%04x" % base

    buf = image_bytes(image)
    base = min(image)
    if a.linear:
        entries = [int(x, 0) for x in a.linear.split(",")]
        code, buf, base = linear(image, entries[0], entries[1] if len(entries) > 1 else None)
    else:
        if a.entry:
            entries = [int(x, 0) for x in a.entry.split(",")]
        else:
            entries = find_entries(image, buf, base)
        code, buf, base = descend(image, entries)

    print("%s: %s, %d bytes mapped, 0x%04x..0x%04x, %d instructions %s" % (
        a.file, how, len(image), base, max(image), len(code),
        "from " + ",".join("0x%04x" % e for e in entries)))
    ok, miss = validate(code)
    print("branch targets on an instruction: %d, off: %d" % (ok, miss))

    if a.listing:
        with open(a.listing, "w", encoding="ascii", errors="replace", newline="\n") as fh:
            listing(code, buf, base, fh)
        print("listing -> %s" % a.listing)

    if a.scan == "movx":
        hits = scan_movx(code, buf, base)
        print("\n%d DPTR accesses:" % len(hits))
        for pc, dptr, text, p2, gap in hits:
            print("  %04x  MOV DPTR,#%04x  ->  %-22s" % (pc, dptr, text))
    if a.scan == "calls":
        tg = call_targets(code, min(image), max(image))
        print("\n%d call/jump targets:" % len(tg))
        for t in sorted(tg):
            print("  %04x  <- %s" % (t, ",".join("%04x" % s for s in tg[t][:6])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
