import unittest

from it9308.device import It9308Device


class FakeTransport:
    def __init__(self, reply=b"\x6a"):
        self.reply = reply
        self.writes = []

    def write_i2c(self, bus, address, data):
        self.writes.append((bus, address, bytes(data)))

    def read_i2c(self, bus, address, length=1):
        if (bus, address) != (2, 0x66):
            raise AssertionError("unexpected I2C read at %d/0x%02x" % (bus, address))
        return self.reply[:length]


class ChipIdTest(unittest.TestCase):
    def test_reads_register_fd_on_bus2_66(self):
        fake = FakeTransport(b"\x6a")
        self.assertEqual(It9308Device(fake).chip_id(), 0x6A)
        self.assertEqual(fake.writes, [(2, 0x66, b"\xfd")])

    def test_returns_the_first_byte(self):
        self.assertEqual(It9308Device(FakeTransport(b"\x62")).chip_id(), 0x62)


if __name__ == "__main__":
    unittest.main()
