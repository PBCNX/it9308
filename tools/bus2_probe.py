"""Probe bus 2: does the 0x30 cluster behave like a real register file?

The write-ACK map (tools/i2c_map.py) says bus 2 carries 0x30..0x33, 0x37 and
0x50, while the vendor's own tuner address (bus 3, 0x70) NAKs.  Before
believing 0x30 is the Panasonic demod, check that its reads actually depend on
a register pointer -- a phantom responder returns the same bytes whatever we
write first.

Panasonic ISDB-T demods (MN88472 and friends) use 16-bit register addresses:
write [hi][lo] then read.  So the test is: set the pointer to 0x0000, 0x0001,
0x0002 and see whether the data moves.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from it9308.transport import Device, TransportError, devices  # noqa: E402

POWER = [(0xD8D3, 0x01), (0xD8B8, 0x01), (0xD8B9, 0x01), (0xD8B7, 0x01)]
I2C_SPEED = [(0xF6A7, 0x07), (0xF103, 0x07)]


def open_device():
    for d in devices():
        if d.idProduct == 0x9309:
            dev = Device(d)
            dev.open()
            return dev
    raise SystemExit("no 048d:9309 on the bus")


def read(dev, bus, address, length, read_bit=True):
    byte = ((address << 1) | (1 if read_bit else 0)) & 0xFF
    try:
        return dev.exchange(0x2A, bytes([length, bus, byte]), length).hex()
    except TransportError as exc:
        return "ERR(%s)" % exc


def write(dev, bus, address, data):
    try:
        dev.write_i2c(bus, address, data)
        return True
    except TransportError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bus", type=int, default=2)
    ap.add_argument("--addresses", default="30,31,32,33,37,50")
    a = ap.parse_args(argv)

    dev = open_device()
    try:
        print("version 0x%08x" % dev.firmware_version())
        for reg, val in I2C_SPEED + POWER:
            dev.write_register(reg, val)

        for text in a.addresses.split(","):
            addr = int(text, 16)
            if not write(dev, a.bus, addr, b"\x00"):
                print("\n%02x: no write ACK" % addr)
                continue
            print("\n%02x on bus %d" % (addr, a.bus))
            print("  no pointer      R|1 %s   R|0 %s"
                  % (read(dev, a.bus, addr, 8), read(dev, a.bus, addr, 8, False)))
            for reg in (0x0000, 0x0001, 0x0002, 0x0003, 0x0010, 0x0030):
                ok = write(dev, a.bus, addr, bytes([reg >> 8, reg & 0xFF]))
                ptr = "%-6s" % ("ptr ok" if ok else "ptr OK?") if ok else "ptr NAK"
                print("  ptr %04x %s  R|1 %s   R|0 %s"
                      % (reg, ptr,
                         read(dev, a.bus, addr, 8),
                         read(dev, a.bus, addr, 8, False)))
            # one byte pointer form, in case it is 8-bit addressed
            write(dev, a.bus, addr, bytes([0x00]))
            print("  ptr 00   (8-bit)  R|1 %s" % read(dev, a.bus, addr, 8))
    finally:
        dev.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
