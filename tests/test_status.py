import math
import unittest

from it9308.device import It9308Device


class FakeI2c:
    def __init__(self, status=0x21, snr_hi=0x07, snr_lo=0x44,
                 rf_hi=0x08, rf_lo=0x58):
        self.status = status
        self.snr_hi = snr_hi
        self.snr_lo = snr_lo
        self.rf_hi = rf_hi
        self.rf_lo = rf_lo
        self.last = None
        self.last_address = None
        self.writes = []
        self.addresses = []

    def write_i2c(self, bus, address, data):
        self.last = bytes(data)
        self.last_address = address
        self.writes.append(self.last)
        self.addresses.append(address)

    def read_i2c(self, bus, address, length=1):
        register = self.last[0]
        if address == 0x64 and register == 0x10:
            return bytes([self.status])
        if address == 0x64 and register == 0x13:
            return bytes([self.snr_hi])
        if address == 0x64 and register == 0x14:
            return bytes([self.snr_lo])
        if address == 0x64 and register == 0x11:
            return bytes([self.rf_hi])
        if address == 0x64 and register == 0x12:
            return bytes([self.rf_lo])
        return bytes(length)


class StatusTest(unittest.TestCase):
    def test_reads_lock_and_snr_without_touching_page0(self):
        fake = FakeI2c()
        status = It9308Device(fake).status()
        self.assertTrue(status.known)
        self.assertTrue(status.locked)
        self.assertEqual(status.raw_snr, 1860)
        self.assertAlmostEqual(status.snr_db, 23.664, places=2)
        self.assertEqual(status.raw_strength, 66)
        self.assertEqual(status.strength, 66)
        self.assertIn(bytes([0x10]), fake.writes)
        self.assertIn(bytes([0x13]), fake.writes)
        self.assertIn(bytes([0x14]), fake.writes)
        self.assertIn(bytes([0x11]), fake.writes)
        self.assertIn(bytes([0x12]), fake.writes)
        self.assertTrue(all(address == 0x64 for address in fake.addresses))

    def test_unlocked_and_empty_snr(self):
        status = It9308Device(FakeI2c(status=0x10, snr_hi=0, snr_lo=2,
                                      rf_hi=0, rf_lo=0xF8)).status()
        self.assertTrue(status.known)
        self.assertFalse(status.locked)
        self.assertEqual(status.raw_snr, 2)
        self.assertEqual(status.raw_strength, 7)
        self.assertEqual(status.strength, 7)
        self.assertAlmostEqual(status.snr_db, -6.02, places=2)


if __name__ == "__main__":
    unittest.main()
