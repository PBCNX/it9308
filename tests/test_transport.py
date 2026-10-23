import unittest

from it9308.transport import PacketAligner, word_sum


class ChecksumTest(unittest.TestCase):
    def test_known_frame(self):
        # QUERYINFO frame from the capture: 06 00 22 01 01 fe dc
        self.assertEqual(word_sum(bytes.fromhex("00220101")), 0xFEDC)


class AlignerTest(unittest.TestCase):
    def test_locks_and_carries(self):
        packet = bytes([0x47]) + bytes(range(1, 188))
        aligner = PacketAligner()
        self.assertEqual(aligner.push(b"ABC" + packet), packet)
        self.assertEqual(aligner.push(packet[:100]), b"")
        self.assertEqual(len(aligner.push(packet[100:])), 188)


if __name__ == "__main__":
    unittest.main()
