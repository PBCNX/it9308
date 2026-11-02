import unittest

from it9308 import sequence


class SequenceTest(unittest.TestCase):
    def test_steps_are_well_formed(self):
        self.assertGreater(len(sequence.STEPS), 900)
        for delay, frame, reply in sequence.STEPS:
            self.assertIsInstance(delay, int)
            self.assertGreaterEqual(delay, 0)
            self.assertLessEqual(delay, 500)
            if frame is None:
                continue
            data = bytes.fromhex(frame)
            self.assertEqual(data[0], len(data) - 1)
            self.assertGreaterEqual(reply, 0)
            self.assertLessEqual(reply, 64)


if __name__ == "__main__":
    unittest.main()
