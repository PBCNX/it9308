"""ISDB-T Information Packet (IIP): the frame-ahead transmission-control packet.

One TSP per multiplex frame, multiplexed in the *invalid hierarchy* (`layer_indicator` '1000') and not
carried by any of layers A/B/C. Per ARIB STD-B31 v2.2-E1 §5.5.3 (Tables 5-8, 5-10) its 184-byte payload is:

```text
IIP_packet_pointer                              16  uimsbf
modulation_control_configuration_information   160  bslbf
IIP_branch_number                                8  uimsbf
last_IIP_branch_number                           8  uimsbf
network_synchronization_information_length       8  uimsbf
network_synchronization_information()           ...  bslbf, then 0xFF stuffing
```

and the information describes the multiplex frame **after** the one carrying the packet.

Unlike TMCC, the IIP *does* carry the transmission mode and guard interval (`mode_GI_information`,
Table 5-10/5-11): `current_mode` is `01/10/11` = 2K/4K/8K, guard `00..11` = 1/32, 1/16, 1/8, 1/4. It also
carries the next frame's copy of the EWBS flag (B26).
"""
from dataclasses import dataclass

MODES = {1: "2K", 2: "4K", 3: "8K"}
GUARDS = {0: "1/32", 1: "1/16", 2: "1/8", 3: "1/4"}
MODULATIONS = {0: "DQPSK", 1: "QPSK", 2: "16QAM", 3: "64QAM"}
CODES = {0: "1/2", 1: "2/3", 2: "3/4", 3: "5/6", 4: "7/8"}
INTERLEAVES = {0: "I0", 1: "I1", 2: "I2", 3: "I4"}
UNKNOWN = "?"
UNUSED = 7


@dataclass
class IipLayer:
    present: bool = False
    modulation: str = UNKNOWN
    code_rate: str = UNKNOWN
    interleave: str = UNKNOWN
    segments: int = 0


@dataclass
class Iip:
    pointer: int = 0
    mode: str = UNKNOWN
    guard: str = UNKNOWN
    next_mode: str = UNKNOWN
    next_guard: str = UNKNOWN
    ewbs: bool = False
    partial: bool = False
    layer_a: IipLayer = None
    layer_b: IipLayer = None
    layer_c: IipLayer = None
    branch: int = 0
    last_branch: int = 0
    net_sync_length: int = 0
    crc_ok: bool = False

    def __post_init__(self):
        for name in ("layer_a", "layer_b", "layer_c"):
            if getattr(self, name) is None:
                setattr(self, name, IipLayer())


class BitReader:
    def __init__(self, data):
        self.bits = []
        for byte in data:
            for shift in range(7, -1, -1):
                self.bits.append((byte >> shift) & 1)
        self.position = 0

    def take(self, count):
        value = 0
        for _ in range(count):
            value = (value << 1) | self.bits[self.position]
            self.position += 1
        return value


def crc32_mpeg2(data):
    """ISO/IEC 13818-1 CRC-32 (STD-B31 Table 5-10 ``CRC_32``), poly 0x04C11DB7, init 0xFFFFFFFF.

    Covers the MCCI from ``TMCC_synchronization_word`` to ``reserved_future_use`` - the first 16 of the
    20 bytes in this implementation.
    """
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def _layer(reader):
    modulation = reader.take(3)
    code = reader.take(3)
    interleave = reader.take(3)
    segments = reader.take(4)
    layer = IipLayer()
    layer.segments = 0 if segments == 15 and modulation == UNUSED else segments
    layer.present = modulation != UNUSED and segments != 15
    if layer.present:
        layer.modulation = MODULATIONS.get(modulation, UNKNOWN)
        layer.code_rate = CODES.get(code, UNKNOWN)
        layer.interleave = INTERLEAVES.get(interleave, UNKNOWN)
    return layer


def decode(payload):
    """Decode one IIP payload (the 184 bytes after the 4-byte TSP header)."""
    if len(payload) < 25:
        raise ValueError("IIP payload too short: %d bytes" % len(payload))
    iip = Iip()
    iip.pointer = (payload[0] << 8) | payload[1]
    reader = BitReader(payload[2:22])       # the 160-bit MCCI block
    reader.take(1)                          # TMCC_synchronization_word
    reader.take(1)                          # AC_data_effective_position
    reader.take(2)                          # reserved
    reader.take(4)                          # initialization_timing_indicator
    iip.mode = MODES.get(reader.take(2), UNKNOWN)
    iip.guard = GUARDS.get(reader.take(2), UNKNOWN)
    iip.next_mode = MODES.get(reader.take(2), UNKNOWN)
    iip.next_guard = GUARDS.get(reader.take(2), UNKNOWN)
    reader.take(2)                          # system_identifier
    reader.take(4)                          # count_down_index
    iip.ewbs = bool(reader.take(1))         # B26 copy for the next frame
    iip.partial = bool(reader.take(1))
    iip.layer_a = _layer(reader)
    iip.layer_b = _layer(reader)
    iip.layer_c = _layer(reader)
    reader.take(1)                          # next partial_reception_flag
    _layer(reader)                          # next A
    _layer(reader)                          # next B
    _layer(reader)                          # next C
    reader.take(3)                          # phase correction
    reader.take(12)                         # TMCC reserved
    reader.take(10)                         # reserved_future_use
    reader.take(32)                         # CRC_32
    mcci = payload[2:22]
    iip.crc_ok = crc32_mpeg2(mcci[:16]) == int.from_bytes(mcci[16:20], "big")
    iip.branch = payload[22]
    iip.last_branch = payload[23]
    iip.net_sync_length = payload[24]
    return iip


def describe(iip):
    def layer_text(name, layer):
        if not layer.present:
            return "  %s:-" % name
        return "  %s:%s %s %s %dseg" % (name, layer.modulation, layer.code_rate,
                                        layer.interleave, layer.segments)

    line = "iip mode %s  guard %s  partial %d  ewbs %d" % (
        iip.mode, iip.guard, int(iip.partial), int(iip.ewbs))
    line += layer_text("L0", iip.layer_a) + layer_text("L1", iip.layer_b)
    line += layer_text("L2", iip.layer_c)
    return line
