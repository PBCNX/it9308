"""Bring-up for the IT9308 using the captured sequence."""
import time

from . import firmware, sequence
from .transport import (Device, EP_COMMAND_IN, EP_COMMAND_OUT,
                        PacketAligner, TransportError)


class It9308Device:
    def __init__(self, device, log=None):
        self.device = device
        self.log = log or (lambda message: None)
        self.aligner = PacketAligner()
        self.version = 0

    def start(self, firmware_path=None):
        self.version = self.device.firmware_version()
        self.log("firmware version: 0x%08x" % self.version)
        if not self.version:
            image = firmware.load(firmware_path)
            self.version = self.device.upload(image)
            self.log("firmware loaded: 0x%08x" % self.version)
            if not self.version:
                raise TransportError("firmware did not start")
        self._replay()
        return self

    def _replay(self):
        total = len(sequence.STEPS)
        for index, (delay, frame_hex, _reply) in enumerate(sequence.STEPS):
            if delay:
                time.sleep(delay / 1000.0)
            if frame_hex is None:
                continue
            frame = bytes.fromhex(frame_hex)
            try:
                self.device.usb.write(EP_COMMAND_OUT, frame, self.device.timeout)
                self.device.usb.read(EP_COMMAND_IN, 256, self.device.timeout)
            except Exception as exc:
                raise TransportError("replay step %d/%d failed: %s" % (
                    index + 1, total, exc))
        self.log("replayed %d steps" % total)

    def read_ts(self, timeout=300):
        try:
            return self.aligner.push(self.device.read_stream(timeout=timeout))
        except Exception:
            return b""
