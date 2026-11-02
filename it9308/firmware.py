"""Vendor firmware handling: the image is supplied by the user, never bundled."""
import hashlib
import os

SHA256 = "e4e94633b4ac47c6bba5ab90eedd4a7e5ffa2ce7e342884c91749c7464704a70"
SIZE = 6498

SEARCH = ("firmware.bin", "it930x-firmware.bin", "it9308-firmware.bin")


def find(path=None):
    if path:
        return path
    env = os.environ.get("IT9308_FIRMWARE")
    if env:
        return env
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in SEARCH:
        candidate = os.path.join(here, name)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(here, "firmware.bin")


def load(path=None):
    path = find(path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            "IT9308 firmware not found at %s. The image is vendor material and "
            "is not distributed: extract it from the IT9308 app, then set "
            "IT9308_FIRMWARE or pass --firmware PATH." % path)
    with open(path, "rb") as handle:
        image = handle.read()
    if len(image) != SIZE or hashlib.sha256(image).hexdigest() != SHA256:
        raise ValueError("firmware at %s is not the expected 6,498-byte image" % path)
    return image
