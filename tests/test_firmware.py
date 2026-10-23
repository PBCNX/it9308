import os
import unittest

from it9308 import firmware


class FirmwareTest(unittest.TestCase):
    def test_missing_image_is_reported(self):
        with self.assertRaises(FileNotFoundError):
            firmware.load(os.path.join(os.path.dirname(__file__), "absent.bin"))

    def test_wrong_image_is_rejected(self):
        path = os.path.join(os.path.dirname(__file__), "wrong.bin")
        with open(path, "wb") as handle:
            handle.write(b"\x00" * firmware.SIZE)
        try:
            with self.assertRaises(ValueError):
                firmware.load(path)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
