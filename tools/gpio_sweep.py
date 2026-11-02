"""Hunt for the tuner's power line by watching the I2C bus.

The vendor sequence we captured belongs to a different board, so its GPIO
choices (0xd8d3 / 0xd8b8 / 0xd8b9 / 0xd8b7) may not power this one.  Rather
than guess a rail, sweep the 0xd8xx GPIO block and watch for a *new* I2C ACK
on the tuner buses.  A device appearing where there was none is unambiguous,
which is more than can be said for the 0x60 phantom we chased earlier (0x60 is
the bridge itself).

    python tools/gpio_sweep.py --image ... --regs d8a0:d900 --value 1
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from it9308.transport import Device, TransportError, devices  # noqa: E402

# 7-bit addresses worth watching for on any bus
WATCH = [0x60, 0x61, 0x62, 0x64, 0x66, 0x70, 0x71, 0x30, 0x31, 0x32, 0x33,
         0x37, 0x38, 0x50]
BUSES = [2, 3]          # 2 = the EEPROM/tuner segment, 3 = default port
SPEED = [(0xF6A7, 0x07), (0xF103, 0x07)]
VENDOR_GPIO = [(0xD8D3, 1), (0xD8B8, 1), (0xD8B9, 1), (0xD8B7, 1)]


def open_device():
    for d in devices():
        if d.idProduct == 0x9309:
            dev = Device(d)
            dev.open()
            return dev
    raise SystemExit("no 048d:9309 on the bus")


def acks(dev, buses, addrs):
    """Write-probe each address; returns {(bus, addr)} that ACK."""
    found = set()
    for reg, val in SPEED:
        try:
            dev.write_register(reg, val)
        except TransportError:
            return found
    for bus in buses:
        for a in addrs:
            try:
                dev.write_i2c(bus, a, b"\x00")
                found.add((bus, a))
            except TransportError:
                pass
    return found


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=r"D:\Profile\Documents\DeepSeek\sticks\.tmp\vendor-mn88553.bin")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--regs", default="d8a0:d900", help="hex range lo:hi")
    ap.add_argument("--value", type=lambda s: int(s, 0), default=1)
    ap.add_argument("--base", action="store_true", default=True,
                    help="apply the vendor GPIO quartet before each candidate")
    a = ap.parse_args(argv)

    dev = open_device()
    try:
        version = dev.firmware_version()
        print("version 0x%08x" % version)
        if version == 0 and not a.no_upload:
            image = open(a.image, "rb").read()
            print("uploading %d bytes" % len(image))
            print("  now 0x%08x" % dev.upload(image))

        for reg, val in SPEED + VENDOR_GPIO:
            dev.write_register(reg, val)

        base = acks(dev, BUSES, WATCH)
        print("baseline ACK: %s" % sorted("bus%d/%02x" % b for b in base))

        lo, hi = [int(x, 16) for x in a.regs.split(":")]
        hits = []
        for reg in range(lo, hi + 1):
            try:
                dev.write_register(reg, a.value)
            except TransportError:
                continue
            now = acks(dev, BUSES, WATCH)
            new = now - base
            if new:
                label = ",".join("bus%d/%02x" % b for b in sorted(new))
                print("  0x%04x = %02x  -> NEW %s" % (reg, a.value, label))
                hits.append((reg, sorted(new)))
                base |= new
        print("\n%d new responders" % len(hits))
        for reg, addrs in hits:
            print("  0x%04x: %s" % (reg, ",".join("%02x" % x[1] for x in addrs)))
    finally:
        dev.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
