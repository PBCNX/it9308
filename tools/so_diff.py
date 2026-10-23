"""Compare vendor .so variants section by section.

TVplus GO ships several tuner backends that are all exactly 1474016 bytes:

    libendeavourtuner.so          1474016   <- 0x930A  EndeavourTunerUtility
    libendeavour-mn88553hel.so    1474016   <- 0x930B  EndeavourMN88553HTunerUtility
    libendeavour-sonytuner.so     1474016   <- 0x9306/0x9308 (Sony)

Same length, different SHA-256.  A raw byte diff is useless here: one extra
string in .dynstr shifts every following section by 8 or 0x10 bytes, so almost
every byte "differs" purely through displacement.  So we compare *section
contents* against each other (text to text, rodata to rodata) and diff the
symbol name sets, which is alignment-free.

    python tools/so_diff.py A.so B.so [--runs N] [--symbols]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from elfinfo import Elf  # noqa: E402


def runs(offsets):
    """Collapse a sorted list of offsets into [start, end] inclusive runs."""
    out = []
    for off in offsets:
        if out and off == out[-1][1] + 1:
            out[-1][1] = off
        else:
            out.append([off, off])
    return out


def show_symbols(a, b, a_name, b_name):
    na = {s["name"] for s in a.symbols}
    nb = {s["name"] for s in b.symbols}
    print("dynsym: %s %d symbols, %s %d symbols" % (a_name, len(na), b_name, len(nb)))
    only_a = sorted(na - nb)
    only_b = sorted(nb - na)
    print("\n  only in %s (%d):" % (a_name, len(only_a)))
    for s in only_a[:60]:
        print("     ", s)
    print("\n  only in %s (%d):" % (b_name, len(only_b)))
    for s in only_b[:60]:
        print("     ", s)


def printable_runs(blob, minlen=6):
    """Extract printable ASCII runs, the raw material for a string-set diff."""
    out, cur = [], bytearray()
    for byte in blob:
        if 0x20 <= byte < 0x7f:
            cur.append(byte)
        else:
            if len(cur) >= minlen:
                out.append(cur.decode("latin1"))
            cur = bytearray()
    if len(cur) >= minlen:
        out.append(cur.decode("latin1"))
    return out


def show_strings(a, b, a_name, b_name):
    for sec in (".rodata",):
        sa, sb = a.section(sec), b.section(sec)
        if not sa or not sb:
            continue
        la = printable_runs(a.bytes_of(sec))
        lb = printable_runs(b.bytes_of(sec))
        seta, setb = set(la), set(lb)
        print("%s: %s %d strings, %s %d strings" % (sec, a_name, len(la), b_name, len(lb)))
        only_a = sorted(seta - setb)
        only_b = sorted(setb - seta)
        print("\n  only in %s (%d):" % (a_name, len(only_a)))
        for s in only_a[:80]:
            print("     %r" % s)
        print("\n  only in %s (%d):" % (b_name, len(only_b)))
        for s in only_b[:80]:
            print("     %r" % s)


def main():
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 1
    a_path, b_path = args[0], args[1]
    nruns = 8
    if "--runs" in sys.argv:
        nruns = int(sys.argv[sys.argv.index("--runs") + 1])

    a, b = Elf(a_path), Elf(b_path)
    a_name, b_name = os.path.basename(a_path), os.path.basename(b_path)
    print("A %-32s %d bytes" % (a_name, len(a.data)))
    print("B %-32s %d bytes" % (b_name, len(b.data)))

    if "--symbols" in sys.argv:
        show_symbols(a, b, a_name, b_name)
        return 0
    if "--strings" in sys.argv:
        show_strings(a, b, a_name, b_name)
        return 0

    secs_a = {s["name"]: s for s in a.sections if s["size"]}
    secs_b = {s["name"]: s for s in b.sections if s["size"]}
    print("\n%-20s %6s %6s %8s  %s" % ("section", "A", "B", "same?", "differing bytes"))
    for name, sa in secs_a.items():
        sb = secs_b.get(name)
        if sb is None:
            print("%-20s  missing in B" % name)
            continue
        da = a.data[sa["offset"]:sa["offset"] + sa["size"]]
        db = b.data[sb["offset"]:sb["offset"] + sb["size"]]
        n = min(len(da), len(db))
        diffs = [i for i in range(n) if da[i] != db[i]]
        verdict = "yes" if not diffs and len(da) == len(db) else "no"
        print("%-20s %6x %6x %8s  %d%s" % (
            name, sa["size"], sb["size"], verdict, len(diffs),
            "" if len(da) == len(db) else " (len delta %d)" % (len(db) - len(da))))
        if diffs and nruns:
            for start, end in runs(diffs)[:nruns]:
                aa = da[start:end + 1][:12].hex()
                bb = db[start:end + 1][:12].hex()
                print("      +%06x len %4d  A %-24s B %s" % (start, end - start + 1, aa, bb))
    return 0


if __name__ == "__main__":
    sys.exit(main())
