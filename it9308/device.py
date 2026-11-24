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


FAST_RETUNE_START = 700


class It9308Device:
    def __init__(self, device, log=None):
        self.device = device
        self.log = log or (lambda message: None)
        self.aligner = PacketAligner()
        self.version = 0

    def recover(self, firmware_path=None, frequency_khz=None, force_upload=False):
        """Clear a stuck bridge **in software**: the vendor's reboot, upload only if the chip came back
        blank, then the replay.

        No USB bus reset: on this bridge ``libusb_reset_device`` leaves the command endpoint answering
        `Pipe error`, so the reliable lever is a **fresh handle** (the caller closes and re-opens between
        attempts) plus the vendor's own ``IT9300_reboot``. ``start()`` skips the upload when the version
        reads non-zero, which is why a state in the firmware's RAM (a disabled TS port at ``0xDA4C``, a
        half-configured tuner) survives a normal reconnect; the reboot or the forced upload clears it,
        and the replay rewrites the bridge registers including the TS enable.

        It cannot beat a state held in hardware (a device that ignores USB); if the stream is still
        silent afterwards, the stick needs an unplug - which is what the ``play`` hint says.
        """
        # a wedge can leave the command endpoint halted before we even start
        halted = self.device.clear_halts()
        if halted:
            self.log("cleared %d endpoint halt(s) before reboot" % halted)
        self.log("recovering: bridge reboot (IT9300_reboot)")
        self.version = self.device.reboot()
        self.log("version after reboot: 0x%08x" % self.version)
        if not self.version or force_upload:
            image = firmware.load(firmware_path)
            self.version = self.device.upload(image)
            self.log("firmware reloaded: 0x%08x" % self.version)
            if not self.version:
                raise TransportError("firmware did not start after recovery")
        # the reboot can leave the command endpoint stalled; clear it before the replay
        halted = self.device.clear_halts()
        if halted:
            self.log("cleared %d endpoint halt(s)" % halted)
        self.frequency_khz = frequency_khz or tune.CAPTURED_KHZ
        self.log("tuning %d kHz" % self.frequency_khz)
        steps = (sequence.STEPS if frequency_khz is None
                 else tune.patched(sequence.STEPS, frequency_khz))
        self._replay(steps)
        self.drain_ts()
        return self

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
        self.drain_ts()
        return self

    def drain_ts(self, max_bytes=300800, max_seconds=0.2):
        """Discard stale TS after a retune, as the vendor app does."""
        deadline = time.monotonic() + max_seconds
        total = 0
        while total < max_bytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            chunk = self.read_ts(timeout=max(1, min(50, int(remaining * 1000))))
            if not chunk:
                break
            total += len(chunk)
        if total:
            self.log("drained %d TS bytes" % total)
        return total

    def retune(self, frequency_khz):
        """Deprecated: the 17-step block is a measured no-op; use fast_retune()."""
        return self.start(None, frequency_khz)

    def fast_retune(self, frequency_khz, delay_scale=0.05):
        """Switch channel by replaying only the tail of the sequence (measured 2026-11-20).

        The tune frames are at steps 394 and 764. Replaying from step 700 switches correctly in ~1.1 s
        (full replay ~4.4 s), and the switch is verified by reading TMCC afterwards: 497 -> 479 must show
        ``QPSK 7/8`` + ``16QAM``. Starting later does not work - 755 and beyond leave the old channel - so
        this constant carries margin over the measured boundary (750 works, 755 does not).
        """
        steps = tune.patched(sequence.STEPS, frequency_khz)
        tail = steps[FAST_RETUNE_START:]
        self.log("fast retune %d kHz: %d of %d steps" % (frequency_khz, len(tail), len(steps)))
        self._replay(tail, delay_scale=delay_scale)
        self.frequency_khz = frequency_khz
        return self

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

    def _replay(self, steps=None, delay_scale=1.0):
        steps = sequence.STEPS if steps is None else steps
        total = len(steps)
        for index, (delay, frame_hex, _reply) in enumerate(steps):
            if delay:
                time.sleep(delay * delay_scale / 1000.0)
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
