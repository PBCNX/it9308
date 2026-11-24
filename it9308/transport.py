"""USB transport for ITE IT930x bridges.

Written from our protocol notes: a length-prefixed command
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
    handle = libusb1.get_backend()
    if handle is None and sys.platform == "darwin":
        # pyusb's default macOS lookup does not search Homebrew prefixes.
        for candidate in ("/opt/homebrew/lib/libusb-1.0.dylib",
                          "/usr/local/lib/libusb-1.0.dylib"):
            if os.path.exists(candidate):
                handle = libusb1.get_backend(
                    find_library=lambda name, path=candidate: path)
                if handle is not None:
                    break
    return handle


def devices():
    _pyusb()
    import usb.core

    handle = backend()
    if handle is None:
        raise TransportError("libusb backend unavailable: install libusb-1.0 (Windows: libusb.info, then set IT9308_LIBUSB; macOS: brew install libusb; Linux: libusb-1.0-0)")
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
        # dispose the libusb device too: releasing the interface alone leaves the handle alive, and a
        # process that re-execs itself (or a close/reopen in the same process) then finds the interface
        # still claimed (Pi, 2026-11-20)
        try:
            _pyusb().dispose_resources(self.usb)
        except Exception:
            pass

    def reboot_blind(self):
        """Send ``IT9300_reboot`` and do **not** read the answer.

        On a wedged bridge the reboot stalls the command endpoint, so the reply never arrives cleanly; the
        driver should close the handle immediately and verify on a fresh one. Fire-and-forget is the
        reliable half of the vendor's reboot.
        """
        body = bytes([(CMD_BOOT >> 8) & 0xFF, CMD_BOOT & 0xFF, self.sequence & 0xFF])
        self.sequence = (self.sequence + 1) & 0xFF
        packet = bytes([len(body) + 2]) + body
        packet += struct.pack(">H", word_sum(packet[1:]))
        self.usb.write(EP_COMMAND_OUT, packet, self.timeout)

    def clear_halts(self):
        """Clear a stall on every endpoint. After the bridge reboots, the command endpoint can answer
        ``Pipe error`` until its halt is cleared - this is the recovery for that, and it is safe to call
        at any time."""
        cleared = 0
        try:
            for configuration in self.usb:
                for interface in configuration:
                    for endpoint in interface:
                        try:
                            self.usb.clear_halt(endpoint.bEndpointAddress)
                            cleared += 1
                        except Exception:
                            pass
        except Exception:
            pass
        return cleared

    def reset(self):
        """Reset the USB device and clear endpoint halts.

        This is a **bus** reset: the bridge's firmware RAM survives it, so it is not a substitute for
        unplugging. It is still worth doing before a forced firmware reload, because it also clears a
        halted bulk endpoint.
        """
        reset = getattr(self.usb, "reset", None)
        if callable(reset):
            try:
                reset()
            except Exception as error:
                self.log("usb reset failed: %s" % error)
        # after a bus reset the configuration is gone: re-set it and re-claim the interface before any
        # command, or the next exchange answers with a checksum mismatch
        try:
            self.usb.set_configuration()
        except Exception:
            pass
        try:
            _pyusb().claim_interface(self.usb, 0)
        except Exception:
            pass
        try:
            for endpoint in self.usb:
                try:
                    self.usb.clear_halt(endpoint)
                except Exception:
                    pass
        except Exception:
            pass

    # -- framed commands ---------------------------------------------------
    def exchange(self, command, body=b"", reply=0, attempts=3):
        """Send a framed command and return its payload.

        A queued reply from an earlier command has a valid checksum too, so a stale frame is only visible
        through its length and sequence number (the host's 0xC9 case, 2026-11-21). Do **not** hard-fail on the
        seq: measured on 2026-11-21, gating on it made a working session read nothing at all. Instead, retry
        the exchange - the bridge answers each request, so a drain-and-retry turns a stale frame into a slow
        read rather than a wrong value or a dead session.
        """
        last = None
        for _attempt in range(max(1, attempts)):
            sent = self.sequence & 0xFF
            packet = bytes([(command >> 8) & 0xFF, command & 0xFF, sent]) + body
            self.sequence = (self.sequence + 1) & 0xFF
            packet = bytes([len(packet) + 2]) + packet
            packet += struct.pack(">H", word_sum(packet[1:]))

            try:
                self.usb.write(EP_COMMAND_OUT, packet, self.timeout)
                answer = bytes(self.usb.read(EP_COMMAND_IN, 256, self.timeout))
            except Exception as exc:
                raise TransportError(str(exc))

            if len(answer) < 5:
                last = TransportError("short response")
                continue
            if word_sum(answer[1:-2]) != struct.unpack(">H", answer[-2:])[0]:
                last = TransportError("checksum mismatch")
                continue
            if answer[2]:
                raise TransportError("command 0x%02x failed: %d" % (command, answer[2]))
            payload = answer[3:-2]
            if reply and len(payload) != reply:
                # len=04 means "no payload": byte 3 is the first CRC byte, never data
                last = TransportError("short reply: %d bytes, expected %d" % (len(payload), reply))
                continue
            if answer[1] != sent:
                last = TransportError("stale response: seq 0x%02x, expected 0x%02x" % (answer[1], sent))
                continue
            return payload if not reply else payload[:reply]
        raise last if last is not None else TransportError("no response")

    def reboot(self):
        """The vendor SDK's ``IT9300_reboot``: boot command, then the version the bridge comes back with.

        A zero version means the chip came back blank (boot ROM), so a firmware upload is required; a
        non-zero version means the existing image restarted, which is the cheaper recovery.
        """
        self.exchange(CMD_BOOT)
        time.sleep(0.3)
        return self.firmware_version()

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
