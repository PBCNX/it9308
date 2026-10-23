"""USB transport for ITE IT930x bridges.

Written from the protocol notes in docs/protocol.md: a length-prefixed command
frame with a big-endian-word checksum, a mirrored response, and a 188-byte
transport-stream endpoint.
"""
import os
import struct
import sys
import time

VID = 0x048D
PID_IT9308 = 0x9308
PID_IT9309 = 0x9309

EP_COMMAND_OUT = 0x02
EP_COMMAND_IN = 0x81
EP_STREAM_IN = 0x84

CMD_READ_REGISTER = 0x0000
CMD_WRITE_REGISTER = 0x0001
CMD_INFO = 0x0022
CMD_BOOT = 0x0023
CMD_WRITE_FIRMWARE = 0x0029
CMD_READ_I2C = 0x002A
CMD_WRITE_I2C = 0x002B

TS_PACKET = 188
TS_READ = TS_PACKET * 87


class TransportError(RuntimeError):
    pass


def _pyusb():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    vendor = os.path.join(root, "vendor")
    if os.path.isdir(os.path.join(vendor, "usb")) and vendor not in sys.path:
        sys.path.insert(0, vendor)
    import usb.util

    return usb.util


def backend():
    _pyusb()
    import usb.backend.libusb1 as libusb1

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundled = os.path.join(root, "vendor", "windows", "x64", "libusb-1.0.dll")
    chosen = os.environ.get("IT9308_LIBUSB")
    if chosen:
        return libusb1.get_backend(find_library=lambda name: chosen)
    if os.name == "nt" and os.path.exists(bundled):
        return libusb1.get_backend(find_library=lambda name: bundled)
    return libusb1.get_backend()


def devices():
    _pyusb()
    import usb.core

    handle = backend()
    if handle is None:
        raise TransportError("libusb backend unavailable")
    return list(usb.core.find(find_all=True, idVendor=VID, backend=handle))


def word_sum(data):
    """Checksum: one's complement of big-endian 16-bit words."""
    total = 0
    for index in range(0, len(data) - 1, 2):
        total += (data[index] << 8) | data[index + 1]
    if len(data) % 2:
        total += data[-1] << 8
    return (~total) & 0xFFFF


def address_bytes(register):
    """Number of significant address bytes, 1 to 4."""
    for width, shift in ((4, 24), (3, 16), (2, 8)):
        if register >> shift:
            return width
    return 1


class Device:
    def __init__(self, usb_device, timeout=2000, log=None):
        self.usb = usb_device
        self.timeout = timeout
        self.sequence = 0
        self.log = log or (lambda message: None)

    def open(self):
        try:
            self.usb.set_configuration()
        except Exception:
            pass
        _pyusb().claim_interface(self.usb, 0)
        return self

    def close(self):
        try:
            _pyusb().release_interface(self.usb, 0)
        except Exception:
            pass

    # -- framed commands ---------------------------------------------------
    def exchange(self, command, body=b"", reply=0):
        packet = bytes([(command >> 8) & 0xFF, command & 0xFF,
                        self.sequence & 0xFF]) + body
        self.sequence = (self.sequence + 1) & 0xFF
        packet = bytes([len(packet) + 2]) + packet
        packet += struct.pack(">H", word_sum(packet[1:]))

        try:
            self.usb.write(EP_COMMAND_OUT, packet, self.timeout)
            answer = bytes(self.usb.read(EP_COMMAND_IN, 256, self.timeout))
        except Exception as exc:
            raise TransportError(str(exc))

        if len(answer) < 5:
            raise TransportError("short response")
        if word_sum(answer[1:-2]) != struct.unpack(">H", answer[-2:])[0]:
            raise TransportError("checksum mismatch")
        if answer[2]:
            raise TransportError("command 0x%02x failed: %d" % (command, answer[2]))
        payload = answer[3:-2]
        return payload if not reply else payload[:reply]

    def firmware_version(self):
        return int.from_bytes(self.exchange(CMD_INFO, b"\x01", 4), "big")

    # -- registers and I2C -------------------------------------------------
    def read_register(self, register, length=1):
        body = bytes([length, address_bytes(register)]) + register.to_bytes(4, "big")
        return self.exchange(CMD_READ_REGISTER, body, length)

    def write_register(self, register, value):
        body = bytes([1, address_bytes(register)]) + register.to_bytes(4, "big")
        self.exchange(CMD_WRITE_REGISTER, body + bytes([value & 0xFF]))

    def read_i2c(self, bus, address, length=1):
        body = bytes([length, bus, (address << 1) & 0xFF])
        return self.exchange(CMD_READ_I2C, body, length)

    def write_i2c(self, bus, address, data):
        body = bytes([len(data), bus, (address << 1) & 0xFF]) + bytes(data)
        self.exchange(CMD_WRITE_I2C, body)

    # -- firmware and stream -----------------------------------------------
    def upload(self, image):
        self.write_register(0xF103, 0x07)
        offset = 0
        while offset < len(image):
            segments = image[offset + 3]
            size = 4 + segments * 3
            for index in range(segments):
                size += image[offset + 6 + index * 3]
            self.exchange(CMD_WRITE_FIRMWARE, image[offset:offset + size])
            offset += size
        self.exchange(CMD_BOOT)
        time.sleep(0.3)
        return self.firmware_version()

    def read_stream(self, size=TS_READ, timeout=300):
        return bytes(self.usb.read(EP_STREAM_IN, size, timeout))


class PacketAligner:
    """Finds the 0x47 phase and returns only complete 188-byte packets."""

    def __init__(self):
        self.buffer = bytearray()

    def push(self, data):
        self.buffer += data
        if not self.buffer:
            return b""

        offset = 0
        while offset < TS_PACKET:
            available = len(self.buffer) - offset
            if available >= 2 * TS_PACKET:
                if self.buffer[offset] == 0x47 and self.buffer[offset + TS_PACKET] == 0x47:
                    break
                offset += 1
            elif available >= TS_PACKET:
                if self.buffer[offset] == 0x47:
                    break
                offset += 1
            else:
                return b""

        if offset >= TS_PACKET:
            self.buffer = self.buffer[-2 * TS_PACKET:]
            return b""

        body = self.buffer[offset:]
        count = len(body) // TS_PACKET * TS_PACKET
        if not count:
            self.buffer = body
            return b""

        packets = bytes(body[:count])
        self.buffer = body[count:]
        for start in range(0, len(packets), TS_PACKET):
            if packets[start] != 0x47:
                self.buffer = bytearray()
                return b""
        return packets
