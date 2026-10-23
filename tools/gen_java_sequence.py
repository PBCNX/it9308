"""Export the captured IT930x sequence as a compact binary for the Java core."""
import struct
import sys

sys.path.insert(0, r"D:\Profile\Documents\DeepSeek\sticks\it9308")
from it9308.sequence import STEPS

OUT = r"D:\Profile\Documents\DeepSeek\sticks\it9308\java\src\main\resources\it9308\sequence.bin"

buffer = bytearray(b"SQ93")
buffer += struct.pack("<I", len(STEPS))
for delay, frame_hex, reply in STEPS:
    if frame_hex is None:
        buffer += struct.pack("<HH", delay, 0)
        buffer += bytes([reply])
        continue
    frame = bytes.fromhex(frame_hex)
    buffer += struct.pack("<HH", delay, len(frame))
    buffer += frame
    buffer += bytes([reply])

with open(OUT, "wb") as handle:
    handle.write(buffer)

print("steps", len(STEPS), "bytes", len(buffer))
