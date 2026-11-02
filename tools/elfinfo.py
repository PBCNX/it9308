"""Minimal ELF64 reader: sections, dynamic symbols, and where things point.

pyelftools is not installed and the .so is stripped, but .dynsym still carries
the Java_* JNI entry points, which is enough to start walking.
"""
import struct


class Elf:
    def __init__(self, path):
        self.data = open(path, "rb").read()
        d = self.data
        if d[:4] != b"\x7fELF":
            raise ValueError("not ELF")
        self.is64 = d[4] == 2
        e_shoff, = struct.unpack_from("<Q", d, 0x28)
        e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", d, 0x3A)
        self.sections = []
        for i in range(e_shnum):
            off = e_shoff + i * e_shentsize
            name, typ, flags, addr, offset, size, link, info, align, entsize = \
                struct.unpack_from("<IIQQQQIIQQ", d, off)
            self.sections.append(dict(name_idx=name, type=typ, flags=flags,
                                      addr=addr, offset=offset, size=size,
                                      link=link, info=info, entsize=entsize))
        shstr = self.sections[e_shstrndx]
        base = shstr["offset"]
        for s in self.sections:
            end = d.index(b"\x00", base + s["name_idx"])
            s["name"] = d[base + s["name_idx"]:end].decode("latin1")
        self.symbols = self._dynsym()

    def section(self, name):
        for s in self.sections:
            if s["name"] == name:
                return s
        return None

    def bytes_of(self, name):
        s = self.section(name)
        return self.data[s["offset"]:s["offset"] + s["size"]] if s else b""

    def _dynsym(self):
        sym = self.section(".dynsym")
        if not sym:
            return []
        strtab = self.sections[sym["link"]]
        base = strtab["offset"]
        out = []
        count = sym["size"] // 24
        for i in range(count):
            off = sym["offset"] + i * 24
            name, info, other, shndx, value, size = struct.unpack_from("<IBBHQQ", self.data, off)
            if not name:
                continue
            end = self.data.index(b"\x00", base + name)
            out.append(dict(name=self.data[base + name:end].decode("latin1"),
                            value=value, size=size, shndx=shndx))
        return out

    def where(self, addr):
        """Map a virtual address to a section name."""
        for s in self.sections:
            if s["addr"] and s["addr"] <= addr < s["addr"] + s["size"]:
                return s["name"]
        return "?"


if __name__ == "__main__":
    import sys
    e = Elf(sys.argv[1])
    print("sections:")
    for s in e.sections:
        if s["size"]:
            print("  %-18s %-10s addr %08x off %06x size %06x" % (
                s["name"], s["type"], s["addr"], s["offset"], s["size"]))
    jni = [s for s in e.symbols if s["name"].startswith("Java_")]
    print("\n%d dynamic symbols, %d JNI" % (len(e.symbols), len(jni)))
    for s in jni:
        print("  %08x %6d %s" % (s["value"], s["size"], s["name"]))
