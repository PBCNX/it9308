"""Read-only IT930x bridge probe for 048d:9308 / 048d:9309.

The frame and checksum follow the protocol described in docs/protocol.md.

    [len-1][cmd hi][cmd lo][seq][payload ...][cs hi][cs lo]
    response: [seq][result][data ...][cs hi][cs lo]

Only QUERYINFO and REG_READ are sent. No firmware download, no register writes.

    python tools/it930x_probe.py
    python tools/it930x_probe.py --read 0x1222:4 --read 0x1220:4
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from it9175.device import _ensure_pyusb, find_devices  # noqa: E402

EP_OUT = 0x02
EP_IN = 0x81

CMD_REG_READ = 0x0000
CMD_REG_WRITE = 0x0001
CMD_QUERYINFO = 0x0022
CMD_BOOT = 0x0023
CMD_I2C_READ = 0x002A
CMD_I2C_WRITE = 0x002B
CMD_FW_SCATTER_WRITE = 0x0029

DEFAULT_REGS = (0x1222, 0x1220, 0x1223, 0xF103)


def checksum(buf):
    total = 0
    length = len(buf)
    i = 0
    while i + 1 < length:
        total += (buf[i] << 8) | buf[i + 1]
        i += 2
    if length % 2:
        total += buf[i] << 8
    return (~total) & 0xFFFF


def reg_length(reg):
    if reg & 0xFF000000:
        return 4
    if reg & 0x00FF0000:
        return 3
    if reg & 0x0000FF00:
        return 2
    return 1


class It930x:
    def __init__(self, dev, timeout=2000):
        self.dev = dev
        self.timeout = timeout
        self.seq = 0

    def command(self, cmd, payload=b"", reply_len=0, no_rx=False):
        body = bytes([(cmd >> 8) & 0xFF, cmd & 0xFF, self.seq & 0xFF]) + payload
        self.seq = (self.seq + 1) & 0xFF
        length = 4 + len(payload) + 2
        frame = bytearray([length - 1]) + body
        cs = checksum(frame[1:length - 2])
        frame += bytes([(cs >> 8) & 0xFF, cs & 0xFF])
        self.dev.write(EP_OUT, bytes(frame), self.timeout)
        if no_rx:
            return 0, b""
        raw = bytes(self.dev.read(EP_IN, 256, self.timeout))
        if len(raw) < 5:
            raise RuntimeError("short response (%d bytes): %s" % (len(raw), raw.hex(" ")))
        got = checksum(raw[1:len(raw) - 2])
        want = (raw[-2] << 8) | raw[-1]
        if got != want:
            raise RuntimeError("checksum mismatch: got 0x%04x want 0x%04x (%s)"
                               % (got, want, raw.hex(" ")))
        if raw[1] != (self.seq - 1) & 0xFF:
            raise RuntimeError("sequence mismatch: %s" % raw.hex(" "))
        result = raw[2]
        data = raw[3:len(raw) - 2]
        if result:
            raise RuntimeError("bridge returned error %d (%s)" % (result, raw.hex(" ")))
        return result, data[:reply_len] if reply_len else data

    def query_info(self):
        _, data = self.command(CMD_QUERYINFO, b"\x01", 4)
        return int.from_bytes(data, "big")

    def read_regs(self, reg, length):
        payload = bytes([length, reg_length(reg),
                         (reg >> 24) & 0xFF, (reg >> 16) & 0xFF,
                         (reg >> 8) & 0xFF, reg & 0xFF])
        _, data = self.command(CMD_REG_READ, payload, length)
        return data

    def write_reg(self, reg, value):
        payload = bytes([1, reg_length(reg),
                         (reg >> 24) & 0xFF, (reg >> 16) & 0xFF,
                         (reg >> 8) & 0xFF, reg & 0xFF, value & 0xFF])
        self.command(CMD_REG_WRITE, payload)

    def i2c_write(self, bus, addr, data):
        payload = bytes([len(data), bus & 0xFF, (addr << 1) & 0xFF]) + bytes(data)
        self.command(CMD_I2C_WRITE, payload)

    def i2c_read(self, bus, addr, length=1):
        payload = bytes([length, bus & 0xFF, (addr << 1) & 0xFF])
        _, data = self.command(CMD_I2C_READ, payload, length)
        return data


def firmware_blocks(image):
    offset = 0
    while offset < len(image):
        if image[offset] != 0x03:
            raise RuntimeError("bad firmware block at %d" % offset)
        count = image[offset + 3]
        size = 4 + count * 3
        for index in range(count):
            size += image[offset + 6 + index * 3]
        yield image[offset:offset + size]
        offset += size


def load_firmware(bridge, path, log=print):
    image = open(path, "rb").read()
    log("firmware image: %d bytes" % len(image))
    bridge.write_reg(0xF103, 0x07)
    blocks = 0
    for chunk in firmware_blocks(image):
        bridge.command(CMD_FW_SCATTER_WRITE, chunk)
        blocks += 1
    log("sent %d blocks" % blocks)
    try:
        bridge.command(CMD_BOOT)
        log("BOOT acknowledged")
    except Exception as exc:
        log("BOOT returned no ack (%s); continuing" % exc)


def hex_int(text):
    """Accept 9309, 0x9309 and decimal-looking IDs as hexadecimal."""
    text = str(text).lower()
    return int(text[2:] if text.startswith("0x") else text, 16)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=hex_int, default=0x9308)
    ap.add_argument("--vid", type=hex_int, default=0x048D)
    ap.add_argument("--read", action="append", default=[],
                    help="REG[:LEN] in hex, e.g. 0x1222:4")
    ap.add_argument("--load-firmware", metavar="FILE",
                    help="upload an IT930x scatter-block firmware image, then BOOT")
    ap.add_argument("--init-i2c", action="store_true",
                    help="set the I2C clock registers before scanning")
    ap.add_argument("--i2c-scan", action="store_true",
                    help="scan buses 0-2 for responding I2C addresses")
    ap.add_argument("--i2c-read", action="append", default=[], metavar="BUS:ADDR[:LEN]",
                    help="read N bytes from an I2C address")
    ap.add_argument("--timeout", type=int, default=2000)
    args = ap.parse_args(argv)

    _ensure_pyusb()
    import usb.util

    devices = [d for d in find_devices() if d.idProduct == args.pid]
    if not devices:
        print("no %04x:%04x device" % (args.vid, args.pid))
        return 2
    dev = devices[0]

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except Exception:
        pass
    try:
        dev.set_configuration()
    except Exception as exc:
        print("set_configuration:", exc)
    usb.util.claim_interface(dev, 0)
    try:
        try:
            serial = usb.util.get_string(dev, dev.iSerialNumber)
        except Exception:
            serial = "?"
        print("device %04x:%04x serial %s bus %s addr %s" % (
            dev.idVendor, dev.idProduct, serial, dev.bus, dev.address))

        bridge = It930x(dev, args.timeout)
        if args.load_firmware:
            load_firmware(bridge, args.load_firmware)
            time.sleep(0.3)
        version = 0
        for attempt in range(5):
            try:
                version = bridge.query_info()
                break
            except Exception as exc:
                if attempt == 4:
                    raise
                time.sleep(0.3)
        print("firmware version: 0x%08x (%d.%d.%d.%d)" % (
            version, (version >> 24) & 0xFF, (version >> 16) & 0xFF,
            (version >> 8) & 0xFF, version & 0xFF))

        if args.init_i2c:
            bridge.write_reg(0xF6A7, 0x07)
            bridge.write_reg(0xF103, 0x07)
            print("i2c clock registers set")

        if args.i2c_scan:
            saved = bridge.timeout
            bridge.timeout = 500
            for bus in (0, 1, 2):
                found = []
                for addr in range(0x08, 0x78):
                    try:
                        data = bridge.i2c_read(bus, addr, 1)
                        found.append((addr, data.hex(" ")))
                    except Exception:
                        pass
                if found:
                    print("i2c bus %d: %s" % (
                        bus, ", ".join("0x%02x=%s" % (a, d) for a, d in found)))
                else:
                    print("i2c bus %d: no devices" % bus)
            bridge.timeout = saved

        for item in args.i2c_read:
            parts = item.split(":")
            bus, addr = int(parts[0], 0), int(parts[1], 0)
            length = int(parts[2], 0) if len(parts) > 2 else 1
            try:
                print("i2c %d:0x%02x[%d] = %s" % (
                    bus, addr, length, bridge.i2c_read(bus, addr, length).hex(" ")))
            except Exception as exc:
                print("i2c %d:0x%02x failed: %s" % (bus, addr, exc))

        regs = [(0x1222, 1), (0x1220, 1), (0x1223, 1), (0xF103, 1)]
        for item in args.read:
            reg, _, length = item.partition(":")
            regs.append((int(reg, 0), int(length, 0) if length else 1))
        seen = set()
        for reg, length in regs:
            if (reg, length) in seen:
                continue
            seen.add((reg, length))
            try:
                data = bridge.read_regs(reg, length)
                print("reg 0x%04x[%d] = %s" % (reg, length, data.hex(" ")))
            except Exception as exc:
                print("reg 0x%04x failed: %s" % (reg, exc))
        return 0
    finally:
        try:
            usb.util.release_interface(dev, 0)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
