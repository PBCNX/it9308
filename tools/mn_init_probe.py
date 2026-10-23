"""Replay the TVplus GO bring-up against the MN88553H firmware, then probe I2C.

The Android capture (docs/9309-vendor-capture.txt) shows the vendor stack doing
~30 IT9303 register writes and then a single I2C probe: write 0xff to address
0x70 on bus 3.  On that run the probe failed with result 0x15 and the app gave
up with "mn init rc=0x101".

That capture was taken while a Sony-flavour image was resident in the bridge
(QUERYINFO answered 0x010a0000 and the app skipped its own upload), so the I2C
failure may say nothing about the tuner.  This tool uploads the Panasonic
image first, replays the vendor register sequence byte for byte, and only then
probes.

    python tools/mn_init_probe.py                 # upload, replay, probe
    python tools/mn_init_probe.py --probe-only    # probe the current state
    python tools/mn_init_probe.py --no-upload     # replay without flashing
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from it9308.transport import Device, TransportError, devices  # noqa: E402

PID_9309 = 0x9309

# register, value -- order matters, this is the vendor's order
VENDOR_SEQUENCE = [
    (0x4976, 0x00),
    (0x4BFB, 0x00),
    (0x4978, 0x00),
    (0x4977, 0x00),
    (0xF6A7, 0x07),
    (0xF103, 0x07),
    (0xDA1A, 0x00),
    (0xF41F, 0x04),
    (0xDA10, 0x00),
    (0xF41A, 0x05),
    (0xDA1D, 0x01),
    (0xDD11, 0x0F),
    (0xDD13, 0x1B),
    (0xDD11, 0x2F),
    (0xDD0C, 0x80),
    (0xDA05, 0x00),
    (0xDA06, 0x00),
    (0xDA1D, 0x00),
    (0xD920, 0x00),
    (0xD833, 0x01),
    (0xD830, 0x00),
    (0xD831, 0x01),
    (0xD832, 0x00),
    (0x495C, 0x00),
    (0x4976, 0x01),
    (0x4975, 0x00),
    (0x4971, 0x00),
    (0xD8D4, 0x01),
    (0xD8D5, 0x01),
    (0xD8D3, 0x01),
    (0xD8B8, 0x01),
    (0xD8B9, 0x01),
    (0xD8B7, 0x01),
    (0xDA5A, 0x1F),
    (0xDA4C, 0x01),
]


def pick_device():
    for d in devices():
        if d.idProduct == PID_9309:
            return d
    raise SystemExit("no 048d:9309 on the bus")


def open_device():
    dev = Device(pick_device())
    dev.open()
    return dev


def replay(dev, log=print):
    for index, (reg, value) in enumerate(VENDOR_SEQUENCE):
        try:
            dev.write_register(reg, value)
        except TransportError as exc:
            log("  %2d  W %04x = %02x  FAILED: %s" % (index, reg, value, exc))
        else:
            log("  %2d  W %04x = %02x" % (index, reg, value))


def probe_address(dev, bus, address):
    """Return (acked, payload_or_error, echoed?)."""
    try:
        data = dev.read_i2c(bus, address, 1)
    except TransportError as exc:
        return False, str(exc), False
    echo = bool(data) and data[0] == ((address << 1) | 1) & 0xFF
    return not echo, data.hex(), echo


def scan(dev, buses, first=0x08, last=0x77, log=print):
    hits = []
    for bus in buses:
        line = []
        for address in range(first, last + 1):
            acked, data, echo = probe_address(dev, bus, address)
            if acked:
                line.append("%02x:%s" % (address, data))
                hits.append((bus, address, data))
            elif not echo and data != str(TransportError):
                # a NAK is the normal "nothing there" answer
                pass
        log("bus %d: %s" % (bus, " ".join(line) if line else "(no ACK)"))
        # a write of 0xff is the vendor's own liveness check
        try:
            dev.write_i2c(bus, 0x70, b"\xff")
            log("bus %d: I2C write 0x70 ff -> ACK (vendor's probe passes)" % bus)
        except TransportError as exc:
            log("bus %d: I2C write 0x70 ff -> %s (vendor's probe fails)" % (bus, exc))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=r"D:\Profile\Documents\DeepSeek\sticks\.tmp\vendor-mn88553.bin")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--probe-only", action="store_true", help="skip the register replay")
    ap.add_argument("--buses", default="0,1,2,3")
    a = ap.parse_args(argv)

    dev = open_device()
    try:
        print("048d:9309 opened, firmware version 0x%08x" % dev.firmware_version())

        if not a.probe_only and not a.no_upload:
            image = open(a.image, "rb").read()
            print("uploading %d bytes (%s)" % (len(image), a.image))
            print("  version after boot: 0x%08x" % dev.upload(image))

        if not a.probe_only:
            print("replaying the vendor register sequence")
            replay(dev)

        buses = [int(b) for b in a.buses.split(",")]
        print("probing I2C buses %s" % buses)
        scan(dev, buses)
    finally:
        dev.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
