"""Replay the captured 952 steps and audit every response.

`device._replay()` writes each frame and reads the reply but never looks at the
result byte, so a NAK anywhere in the sequence would be invisible.  This walks
the same frames and reports short replies, bad checksums and non-zero results,
which is the evidence behind "952/952 commands accepted" in START-HERE.md.

    python tools/audit_replay.py
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from it9308 import sequence  # noqa: E402
from it9308.transport import (Device, EP_COMMAND_IN, EP_COMMAND_OUT,  # noqa: E402
                              PID_IT9308, devices, word_sum)


def main():
    found = [d for d in devices() if d.idProduct == PID_IT9308]
    if not found:
        raise SystemExit("no IT9308 device (048d:9308) found")
    dev = Device(found[0]).open()
    try:
        print("firmware version: 0x%08x" % dev.firmware_version())
        failures = []
        seq_mismatch = 0
        started = time.time()
        for index, (delay, frame_hex, _reply) in enumerate(sequence.STEPS):
            if delay:
                time.sleep(delay / 1000.0)
            if frame_hex is None:
                continue
            frame = bytes.fromhex(frame_hex)
            command = (frame[1] << 8) | frame[2]
            dev.usb.write(EP_COMMAND_OUT, frame, dev.timeout)
            answer = bytes(dev.usb.read(EP_COMMAND_IN, 256, dev.timeout))
            if len(answer) < 5:
                failures.append((index + 1, command, "short reply"))
                continue
            if word_sum(answer[1:-2]) != struct.unpack(">H", answer[-2:])[0]:
                failures.append((index + 1, command, "checksum"))
                continue
            if answer[1] != frame[3]:
                seq_mismatch += 1
            if answer[2]:
                failures.append((index + 1, command, "result %d" % answer[2]))
        elapsed = time.time() - started
    finally:
        dev.close()

    print("replayed %d steps in %.1f s" % (len(sequence.STEPS), elapsed))
    print("failures: %d" % len(failures))
    for step, command, why in failures[:40]:
        print("  step %3d cmd 0x%04x %s" % (step, command, why))
    print("request/response seq mismatches: %d" % seq_mismatch)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
