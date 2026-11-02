"""Sony demod status: lock and SNR, measured on the phone.

The live registers are on the 0x64 address, read plainly (no bank write):

- lock: reg 0x10, bit 0x01 (GMA 0x21, empty 0x10);
- SNR: reg 0x13 high, reg 0x14 low, 16-bit big-endian,
  ``10*log10(raw) - 9.031`` dB (GMA 0x0744 -> 23.7 dB, empty 0x0002 -> -6.0);
- RF: reg 0x11 high / 0x12 low, relative index
  ``((b1 >> 5) | (b0 << 3))`` (GMA 66, empty 7); not calibrated dBm.

Read once between tune() and setStreaming(); a read while TS flows stops the
stream on this part.
"""
import math
from dataclasses import dataclass

DEMOD_BUS = 2
STATUS_ADDRESS = 0x64
STATUS_REG = 0x10
SNR_REG_HI = 0x13
SNR_REG_LO = 0x14


@dataclass
class SignalStatus:
    known: bool = False
    locked: bool = False
    strength: int = -1
    quality: int = -1
    raw_strength: int = -1
    raw_snr: int = -1
    snr_db: float = float("nan")


def _read(device, register, length):
    device.write_i2c(DEMOD_BUS, STATUS_ADDRESS, bytes([register]))
    return device.read_i2c(DEMOD_BUS, STATUS_ADDRESS, length)


def read_status(device):
    try:
        lock = _read(device, STATUS_REG, 1)
        if not lock:
            return SignalStatus()
        high = _read(device, SNR_REG_HI, 1)
        low = _read(device, SNR_REG_LO, 1)
        raw_snr = -1
        snr_db = float("nan")
        if high and low:
            raw_snr = (high[0] << 8) | low[0]
            if raw_snr > 0:
                snr_db = 10.0 * math.log10(raw_snr) - 9.031

        rf_high = _read(device, 0x11, 1)
        rf_low = _read(device, 0x12, 1)
        raw_strength = -1
        strength = -1
        if rf_high and rf_low:
            raw_strength = ((rf_low[0] & 0xFF) >> 5) | ((rf_high[0] & 0xFF) << 3)
            strength = min(100, raw_strength)

        return SignalStatus(known=True, locked=bool(lock[0] & 0x01),
                            strength=strength, raw_strength=raw_strength,
                            raw_snr=raw_snr, snr_db=snr_db)
    except Exception:
        return SignalStatus()
