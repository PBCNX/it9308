"""Write-ACK scan: definitive I2C device map for the IT930x buses.

A write to a non-existent address fails with result 0x15 (NAK).  A read can be
ambiguous because the bridge answers with (addr<<1)|1 when nobody is there, so
writes are the only trustworthy probe.
"""
import sys

sys.path.insert(0, r"D:\Profile\Documents\DeepSeek\sticks\it9308")
from it9308.transport import Device, TransportError, devices

dev = Device([d for d in devices() if d.idProduct == 0x9309][0])
dev.open()
print("version 0x%08x" % dev.firmware_version())
for reg, val in ((0xF6A7, 0x07), (0xF103, 0x07), (0xD8D3, 0x01), (0xD8B8, 0x01),
                 (0xD8B9, 0x01), (0xD8B7, 0x01)):
    dev.write_register(reg, val)

for bus in range(4):
    found = []
    for a in range(0x08, 0x78):
        try:
            dev.write_i2c(bus, a, b"\x00")
            found.append(a)
        except TransportError:
            pass
    print("bus %d ACK: %s" % (bus, " ".join("%02x" % a for a in found) or "(none)"))

print("--- reads at the responders, 8 bytes each")
for bus in range(4):
    for a in range(0x08, 0x78):
        try:
            dev.write_i2c(bus, a, b"\x00")
        except TransportError:
            continue
        for length in (1, 8):
            try:
                d = dev.exchange(0x2A, bytes([length, bus, (a << 1) | 1]), length)
                print("  bus %d %02x len %d -> %s" % (bus, a, length, d.hex()))
            except TransportError as e:
                print("  bus %d %02x len %d -> %s" % (bus, a, length, e))
dev.close()
