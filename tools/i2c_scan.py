"""Scan the IT930x I2C buses for a device that acknowledges.

Written for the parked `048D:9309` (TVplus GO: IT9303FN bridge + Panasonic
MN88553H), where the vendor backends both failed at a single hard-coded
address - Sony at bus 2/0x66, Panasonic at bus 3/0x70.  Instead of trusting
those addresses, find what actually answers.

    python tools/i2c_scan.py                     # buses 0-3, addresses 0x60-0x77
    python tools/i2c_scan.py --buses 0-3 --addresses 0x08-0x7f
    python tools/i2c_scan.py --firmware ../it9308/firmware.bin   # cold unit

A NAK comes back as a bridge error (``TransportError``), which is the scan's
"nobody there"; an ACK prints the byte(s) read.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from it9308.transport import Device, TransportError, devices  # noqa: E402


def parse_range(text, default):
    if not text:
        return default
    if "-" in text:
        low, high = text.split("-", 1)
        return list(range(int(low, 0), int(high, 0) + 1))
    return [int(text, 0)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--buses", default="0-3")
    parser.add_argument("--addresses", default="0x60-0x77")
    parser.add_argument("--firmware")
    parser.add_argument("--timeout", type=int, default=2000)
    args = parser.parse_args()

    found = devices()
    if not found:
        print("no 048D device attached")
        return 1
    usb = found[0]
    print("device %04x:%04x bus %s addr %s"
          % (usb.idVendor, usb.idProduct, usb.bus, usb.address))

    device = Device(usb, timeout=args.timeout)
    device.open()
    version = device.firmware_version()
    print("firmware version: 0x%08x" % version)
    if not version and args.firmware:
        image = open(args.firmware, "rb").read()
        version = device.upload(image)
        print("uploaded %d bytes, version now 0x%08x" % (len(image), version))
    if not version:
        print("bridge has no firmware; pass --firmware for a cold unit")
        device.close()
        return 1

    # The I2C engine only runs after its speed is programmed; without this the
    # bridge echoes the address byte back with result 0, so every address looks
    # like an ACK.  Same two writes as it930x_config_i2c().  Any register write
    # in between (GPIOs included) drops the configuration again, so it is
    # re-applied before every probe.
    def configure():
        device.write_register(0xF6A7, 0x07)
        device.write_register(0xF103, 0x07)

    def echoes(data, address):
        """True when the reply is the request's address byte, not device data."""
        return bool(data) and data[0] == ((address << 1) | 1)

    configure()
    print("i2c speed configured (0xf6a7, 0xf103 = 0x07)")

    buses = parse_range(args.buses, list(range(4)))
    addresses = parse_range(args.addresses, list(range(0x60, 0x78)))

    hits = []
    echoed = 0
    for bus in buses:
        for address in addresses:
            configure()
            try:
                data = device.read_i2c(bus, address, 1)
            except TransportError:
                continue
            except Exception as error:
                print("  bus %d 0x%02x: %s" % (bus, address, error))
                continue
            if echoes(data, address):
                echoed += 1
                continue
            value = data[0] if data else None
            print("  ACK bus %d 0x%02x -> %s" % (bus, address,
                                                 data.hex() if data else "-"))
            hits.append((bus, address, value))

    device.close()
    if echoed:
        print("\n%d probe(s) returned the request byte unchanged (echo, ignored)"
              % echoed)
    print("%d device(s) acknowledged" % len(hits))
    for bus, address, value in hits:
        print("  bus %d address 0x%02x (first byte %s)"
              % (bus, address, "0x%02x" % value if value is not None else "-"))
    return 0 if hits else 2


if __name__ == "__main__":
    raise SystemExit(main())
