"""Extract the IT930x scatter-block firmware chain embedded in a vendor .so.

The vendor/IT9308 libraries carry the bridge firmware as a chain of blocks:
    byte 0 = 0x03, byte 3 = segment count, then per segment [addr hi][addr lo][len].

    python tools/extract_vendor_fw.py --so <lib.so> --offset 0x65530 --out fw.bin
"""
import argparse
import os
import sys


def block_size(data, off):
    if off + 4 > len(data) or data[off] != 0x03:
        return None
    segments = data[off + 3]
    if not 1 <= segments <= 16:
        return None
    total = 4 + segments * 3
    for index in range(segments):
        length = data[off + 6 + index * 3]
        if not length:
            return None
        total += length
    return total if off + total <= len(data) else None


def extract(data, offset):
    out = bytearray()
    blocks = 0
    while True:
        size = block_size(data, offset)
        if not size:
            break
        out += data[offset:offset + size]
        offset += size
        blocks += 1
    return bytes(out), blocks


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--so", required=True)
    ap.add_argument("--offset", type=lambda x: int(x, 0), required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    data = open(args.so, "rb").read()
    image, blocks = extract(data, args.offset)
    if not image:
        print("no firmware chain at that offset", file=sys.stderr)
        return 2
    with open(args.out, "wb") as f:
        f.write(image)
    print("%s: %d blocks, %d bytes -> %s" % (
        os.path.basename(args.so), blocks, len(image), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
