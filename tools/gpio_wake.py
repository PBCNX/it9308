"""Hunt for the MN88553H's reset/enable pin on the IT930x GPIO block.

The previous sweep wrote GPIO registers blind.  `px4_drv` shows each pin needs
three registers - mode, enable and output - and the output register does
nothing unless the pin was configured as an output first.  The IT930x layout is

    gpio  mode    enable  output
     1    0xd8b0  0xd8b1  0xd8af        9    0xd8cc  0xd8cd  0xd8cb
     2    0xd8b8  0xd8b9  0xd8b7       10    0xd8d8  0xd8d9  0xd8d7
     3    0xd8b4  0xd8b5  0xd8b3       11    0xd8d4  0xd8d5  0xd8d3
     4    0xd8c0  0xd8c1  0xd8bf       12    0xd8e0  0xd8e1  0xd8df
     5    0xd8bc  0xd8bd  0xd8bb       13    0xd8dc  0xd8dd  0xd8db
     6    0xd8c8  0xd8c9  0xd8c7       14    0xd8e4  0xd8e5  0xd8e3
     7    0xd8c4  0xd8c5  0xd8c3       15    0xd8e8  0xd8e9  0xd8e7
     8    0xd8d0  0xd8d1  0xd8cf       16    0xd8ec  0xd8ed  0xd8eb

so the hunt drives each pin as a real output, pulsing it low then high and
watching the I2C buses for a device that answers where nothing answered before.

    python tools/gpio_wake.py                  # single pin at a time
    python tools/gpio_wake.py --phase pair     # vendor pair held high, add one
    python tools/gpio_wake.py --no-upload      # use the resident image
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from it9308.transport import Device, TransportError, devices  # noqa: E402

MODE = [0xD8B0, 0xD8B8, 0xD8B4, 0xD8C0, 0xD8BC, 0xD8C8, 0xD8C4, 0xD8D0,
        0xD8CC, 0xD8D8, 0xD8D4, 0xD8E0, 0xD8DC, 0xD8E4, 0xD8E8, 0xD8EC]
OUT = [0xD8AF, 0xD8B7, 0xD8B3, 0xD8BF, 0xD8BB, 0xD8C7, 0xD8C3, 0xD8CF,
       0xD8CB, 0xD8D7, 0xD8D3, 0xD8DF, 0xD8DB, 0xD8E3, 0xD8E7, 0xD8EB]

SPEED = [(0xF6A7, 0x07), (0xF103, 0x07)]
# the vendor's own pair: GPIO2 and GPIO11 as outputs, driven high
VENDOR_PAIR = [2, 11]

BUSES = [2, 3]
ADDRS = [0x30, 0x31, 0x32, 0x33, 0x50, 0x60, 0x62, 0x64, 0x70, 0x71, 0x72]


def open_device():
    for d in devices():
        if d.idProduct == 0x9309:
            return Device(d).open()
    raise SystemExit("no 048d:9309 on the bus")


def setup_pin(dev, gpio, level):
    """Drive GPIO n as an output at the given level."""
    index = gpio - 1
    dev.write_register(MODE[index], 1)     # IT930X_GPIO_OUT
    dev.write_register(MODE[index] + 1, 1)  # enable
    dev.write_register(OUT[index], 1 if level else 0)


def release_pin(dev, gpio):
    index = gpio - 1
    dev.write_register(OUT[index], 0)
    dev.write_register(MODE[index] + 1, 0)  # disable
    dev.write_register(MODE[index], 0)      # input


def probe(dev):
    """Return {(bus, addr): read byte} for everything that ACKs a write."""
    for reg, val in SPEED:
        try:
            dev.write_register(reg, val)
        except TransportError:
            pass
    out = {}
    for bus in BUSES:
        for a in ADDRS:
            try:
                dev.write_i2c(bus, a, b"\x00")
            except TransportError:
                continue
            try:
                out[(bus, a)] = dev.exchange(0x2A, bytes([1, bus, (a << 1) | 1]), 1).hex()
            except TransportError:
                out[(bus, a)] = "ERR"
    return out


def label(key):
    return "bus%d/%02x" % key


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=r"D:\Profile\Documents\DeepSeek\sticks\.tmp\vendor-mn88553.bin")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--phase", choices=("single", "pair", "both"), default="both")
    ap.add_argument("--settle", type=float, default=0.02)
    a = ap.parse_args(argv)

    dev = open_device()
    try:
        version = dev.firmware_version()
        print("version 0x%08x" % version)
        if version == 0 and not a.no_upload:
            print("uploading", os.path.basename(a.image))
            print("  now 0x%08x" % dev.upload(open(a.image, "rb").read()))

        base = probe(dev)
        print("baseline: %s" % " ".join("%s=%s" % (label(k), v) for k, v in sorted(base.items())))

        changes = []

        def step(name, fn):
            fn()
            time.sleep(a.settle)
            now = probe(dev)
            new = {k: v for k, v in now.items() if k not in base}
            gone = [k for k in base if k not in now]
            moved = {k: (base[k], v) for k, v in now.items() if k in base and base[k] != v}
            if new or gone or moved:
                msg = []
                if new:
                    msg.append("NEW " + " ".join("%s=%s" % (label(k), v) for k, v in sorted(new.items())))
                if gone:
                    msg.append("LOST " + " ".join(label(k) for k in gone))
                if moved:
                    msg.append("CHANGED " + " ".join("%s %s->%s" % (label(k), o, n) for k, (o, n) in sorted(moved.items())))
                print("  %-22s %s" % (name, "; ".join(msg)))
                changes.append((name, msg))
            return now

        if a.phase in ("single", "both"):
            print("\nphase 1: each GPIO alone, low then high")
            for gpio in range(1, 17):
                setup_pin(dev, gpio, 0)
                step("gpio%d low" % gpio, lambda: None)
                setup_pin(dev, gpio, 1)
                step("gpio%d high" % gpio, lambda: None)
                release_pin(dev, gpio)
                time.sleep(a.settle)

        if a.phase in ("pair", "both"):
            print("\nphase 2: vendor pair held high, one extra pin at a time")
            for gpio in VENDOR_PAIR:
                setup_pin(dev, gpio, 1)
            time.sleep(0.05)
            base = probe(dev)
            for gpio in [g for g in range(1, 17) if g not in VENDOR_PAIR]:
                setup_pin(dev, gpio, 0)
                step("pair+gpio%d low" % gpio, lambda: None)
                setup_pin(dev, gpio, 1)
                step("pair+gpio%d high" % gpio, lambda: None)
                release_pin(dev, gpio)
            for gpio in VENDOR_PAIR:
                release_pin(dev, gpio)

        print("\n%d transitions" % len(changes))
        if not changes:
            print("no GPIO changed the I2C map: nothing on this bridge can wake the tuner")
    finally:
        dev.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
