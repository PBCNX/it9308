"""Bring-up for the IT9308 using the captured sequence."""
import time

from . import firmware, sequence, tune
from .status import read_status
from .transport import (Device, EP_COMMAND_IN, EP_COMMAND_OUT,
                        PacketAligner, TransportError)

#: Sony demod bus and address, and the chip-ID register.
DEMOD_BUS = 2
DEMOD_ADDRESS = 0x66
DEMOD_CHIP_ID = 0xFD


class It9308Device:
    def __init__(self, device, log=None):
        self.device = device
        self.log = log or (lambda message: None)
        self.aligner = PacketAligner()
        self.version = 0

    def start(self, firmware_path=None, frequency_khz=None):
        self.version = self.device.firmware_version()
        self.log("firmware version: 0x%08x" % self.version)
        if not self.version:
            image = firmware.load(firmware_path)
            self.version = self.device.upload(image)
            self.log("firmware loaded: 0x%08x" % self.version)
            if not self.version:
                raise TransportError("firmware did not start")
        self.frequency_khz = frequency_khz or tune.CAPTURED_KHZ
        self.log("tuning %d kHz" % self.frequency_khz)
        steps = (sequence.STEPS if frequency_khz is None
                 else tune.patched(sequence.STEPS, frequency_khz))
        self._replay(steps)
        return self

    def retune(self, frequency_khz):
        """Deprecated: the 17-step block is a measured no-op; full replay."""
        return self.start(None, frequency_khz)

    def chip_id(self):
        """Sony demod chip ID: register 0xFD on bus 2 / 0x66.

        Measured 0x6A on this stick (2026-11-02). The vendor's
        sony_tunerdemod_ChipID recognises 0x62 and 0x6A. The demod must be
        initialised first (start()). The captured sequence's step 55 is the
        same read.
        """
        self.device.write_i2c(DEMOD_BUS, DEMOD_ADDRESS, [DEMOD_CHIP_ID])
        return self.device.read_i2c(DEMOD_BUS, DEMOD_ADDRESS, 1)[0]

    def status(self):
        """Lock, RF level and SNR; see it9308/status.py for the registers."""
        return read_status(self.device)

    def _replay(self, steps=None):
        steps = sequence.STEPS if steps is None else steps
        total = len(steps)
        for index, (delay, frame_hex, _reply) in enumerate(steps):
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
