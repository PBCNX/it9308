"""Frequency patching for the captured 599.143 MHz sequence.

The tune is a 24-bit big-endian kHz field inside two I2C payloads. Replacing
it also changes the frame checksum, so every touched frame is resealed.
"""
from .transport import word_sum

CAPTURED_KHZ = 599143
CAPTURED_FIELD = b"\x09\x24\x67"  # 599,143 kHz


def patched(steps, frequency_khz):
    """Return a copy of ``steps`` tuned to ``frequency_khz``.

    Only the two frames carrying the captured kHz field change; their checksum
    is recomputed. Delays, replies and every other frame are preserved.
    """
    if not 1 <= frequency_khz <= 0xFFFFFF:
        raise ValueError("frequency out of 24-bit range: %d" % frequency_khz)
    replacement = frequency_khz.to_bytes(3, "big")
    result = []
    for delay, frame_hex, reply in steps:
        if frame_hex:
            data = bytearray.fromhex(frame_hex)
            if CAPTURED_FIELD in data:
                data = data.replace(CAPTURED_FIELD, replacement)
                data[-2:] = word_sum(data[1:-2]).to_bytes(2, "big")
                frame_hex = data.hex()
        result.append((delay, frame_hex, reply))
    return result
