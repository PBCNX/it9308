import unittest

from it9308 import sequence, tune
from it9308.transport import word_sum


class TuneTest(unittest.TestCase):
    def test_captured_frequency_is_byte_identical(self):
        patched = tune.patched(sequence.STEPS, tune.CAPTURED_KHZ)
        self.assertEqual(patched, sequence.STEPS)

    def test_473143_frames_are_exact(self):
        frames = [f for _delay, f, _reply in tune.patched(sequence.STEPS, 473143)
                  if f and "073837" in f]
        self.assertEqual(frames, [
            "14002b8a0c02cc5200006b4d0000073837fffe9b55",
            "14002b840c02cc5200006b4d0000073837fffea155",
        ])

    def test_every_touched_frame_is_resealed(self):
        for _delay, frame_hex, _reply in tune.patched(sequence.STEPS, 473143):
            if frame_hex:
                frame = bytes.fromhex(frame_hex)
                self.assertEqual(int.from_bytes(frame[-2:], "big"),
                                 word_sum(frame[1:-2]))

    def test_only_two_frames_change(self):
        before = [f for _d, f, _r in sequence.STEPS]
        after = [f for _d, f, _r in tune.patched(sequence.STEPS, 473143)]
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual(len(changed), 2)

    def test_out_of_range(self):
        for value in (0, -1, 0x1000000):
            with self.assertRaises(ValueError):
                tune.patched(sequence.STEPS, value)


if __name__ == "__main__":
    unittest.main()
