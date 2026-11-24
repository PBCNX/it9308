"""ISDB-T transmission parameters (TMCC) as this demod reports them.

The demod mirrors the TMCC bit stream closely enough that the ARIB STD-B31 layout applies directly
(Tables 3-22 and 3-23): each hierarchical layer is a 13-bit block - modulation 3, code rate 3,
interleave 3, segments 4 - and the blocks sit one after another in the parameter information.

Measured packing on this chip (2026-11-19, controlled mux and real channels):

```text
0x24  bits 3:2 mode (2K=0, 8K=1, 4K=2), bits 1:0 guard (1/16=1, 1/8=2, 1/4=3, 1/32=0)
0x32  bit 0 partial reception, bit 1 TMCC emergency flag (B26)
0x33  bits 7:5 layer A modulation, 4:2 layer A code rate, 1:0 layer A interleave (high bits)
0x34  bit 7 layer A interleave (low bit), 6:3 layer A segments, 2:0 layer B modulation
0x35  bits 7:5 layer B code rate, 4:2 layer B interleave, 1:0 layer B segments (high bits)
0x36  bits 7:6 layer B segments (low bits), 5:3 layer C modulation
```

`7` in a modulation field is the standard's "unused layer". Anything outside the measured layout prints
`?` rather than a guess.
"""
from dataclasses import dataclass, field
import time

DEMOD_BUS = 2
STATUS_ADDRESS = 0x64

MODES = {0: "2K", 1: "8K", 2: "4K"}
GUARDS = {0: "1/32", 1: "1/16", 2: "1/8", 3: "1/4"}
MODULATIONS = {0: "DQPSK", 1: "QPSK", 2: "16QAM", 3: "64QAM"}
CODES = {0: "1/2", 1: "2/3", 2: "3/4", 3: "5/6", 4: "7/8"}
INTERLEAVES = {0: "I0", 1: "I1", 2: "I2", 3: "I4"}
UNUSED = 7
UNKNOWN = "?"


@dataclass
class Layer:
    modulation: str = UNKNOWN
    code_rate: str = UNKNOWN
    interleave: str = UNKNOWN
    segments: int = -1
    present: bool = False

    def as_dict(self, name):
        return {"layer": name, "present": self.present, "segments": self.segments,
                "modulation": self.modulation, "code_rate": self.code_rate,
                "interleave": self.interleave}


@dataclass
class Tmcc:
    mode: str = UNKNOWN
    guard: str = UNKNOWN
    partial: bool = False
    ewbs: bool = False
    layer_a: Layer = field(default_factory=Layer)
    layer_b: Layer = field(default_factory=Layer)
    layer_c: Layer = field(default_factory=Layer)
    raw: dict = field(default_factory=dict)

    def as_dict(self):
        return {
            "mode": self.mode,
            "guard": self.guard,
            "partial": self.partial,
            "ewbs": self.ewbs,
            "layers": [self.layer_a.as_dict("A"), self.layer_b.as_dict("B"),
                       self.layer_c.as_dict("C")],
            "raw": {"0x%02x" % register: "0x%02x" % value
                    for register, value in sorted(self.raw.items())},
        }

    @property
    def valid(self):
        """A reading is a channel only when at least one layer carries segments.

        ``0x0000`` is both a legitimate 2K / 1/32 configuration and what an **undecoded** TMCC
        register reads, so the mode alone cannot tell them apart. The total segment count can: a real
        multiplex always has 1..13 segments across its layers. Same rule as IT9175's ``Tmcc.valid``
        (2026-11-20): a field that is zero by default is not evidence until something else agrees.
        """
        total = sum(layer.segments for layer in (self.layer_a, self.layer_b, self.layer_c)
                    if layer.present)
        return (self.mode != UNKNOWN and self.guard != UNKNOWN and 1 <= total <= 13)


def _layer(modulation, code, interleave, segments):
    layer = Layer(segments=segments, present=modulation != UNUSED)
    layer.modulation = MODULATIONS.get(modulation, UNKNOWN) if layer.present else "-"
    layer.code_rate = CODES.get(code, UNKNOWN) if layer.present else "-"
    layer.interleave = INTERLEAVES.get(interleave, UNKNOWN) if layer.present else "-"
    if not layer.present:
        layer.segments = 0
    return layer


def decode(registers):
    """Turn the raw register bytes into a :class:`Tmcc`."""
    value24 = registers.get(0x24)
    value32 = registers.get(0x32, 0)
    value33 = registers.get(0x33)
    value34 = registers.get(0x34)
    value35 = registers.get(0x35)
    value36 = registers.get(0x36)
    tmcc = Tmcc(raw=dict(registers))
    if value24 is not None:
        tmcc.mode = MODES.get((value24 >> 2) & 0x03, UNKNOWN)
        tmcc.guard = GUARDS.get(value24 & 0x03, UNKNOWN)
    tmcc.partial = bool(value32 & 0x01)
    tmcc.ewbs = bool(value32 & 0x02)
    if value33 is not None:
        value34 = value34 if value34 is not None else 0
        value35 = value35 if value35 is not None else 0xFF
        value36 = value36 if value36 is not None else 0xFF
        tmcc.layer_a = _layer((value33 >> 5) & 0x07, (value33 >> 2) & 0x07,
                              ((value33 & 0x03) << 1) | ((value34 >> 7) & 0x01),
                              (value34 >> 3) & 0x0F)
        tmcc.layer_b = _layer(value34 & 0x07, (value35 >> 5) & 0x07, (value35 >> 2) & 0x07,
                              ((value35 & 0x03) << 2) | ((value36 >> 6) & 0x03))
        value37 = registers.get(0x37)
        value37 = value37 if value37 is not None else 0xFF
        tmcc.layer_c = _layer((value36 >> 3) & 0x07, value36 & 0x07,
                              (value37 >> 5) & 0x07, (value37 >> 1) & 0x0F)
    return tmcc


def _read(device, register):
    device.write_i2c(DEMOD_BUS, STATUS_ADDRESS, bytes([register]))
    data = device.read_i2c(DEMOD_BUS, STATUS_ADDRESS, 1)
    return data[0] if data else None


def read_tmcc(device):
    """Read the TMCC registers; None values mean the read failed."""
    registers = {}
    for register in (0x24, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37):
        value = _read(device, register)
        if value is not None:
            registers[register] = value
    return decode(registers)


def describe(tmcc):
    """One line, in the shape the hosts asked for."""
    line = "tmcc mode %s  guard %s  partial %d  ewbs %d" % (
        tmcc.mode, tmcc.guard, int(tmcc.partial), int(tmcc.ewbs))

    def layer_text(name, layer):
        if not layer.present:
            return "  %s:-" % name
        return "  %s:%s %s %s %dseg" % (name, layer.modulation, layer.code_rate,
                                        layer.interleave, layer.segments)

    line += layer_text("L0", tmcc.layer_a)
    line += layer_text("L1", tmcc.layer_b)
    line += layer_text("L2", tmcc.layer_c)
    return line


def watch(read, emit=print, interval=1.0, seconds=0.0, sleep=time.sleep,
          clock=time.monotonic):
    """Poll the TMCC flag and emit a line on every change (the EWBS activation display).

    ``read`` returns a :class:`Tmcc`, or ``None`` when the demod is not locked. The first good read
    prints the state; a rise prints ``ALERT`` and a fall ``CLEAR``, each with the full parameter line so
    a host has the layer context of the alert. A loss of lock prints ``LOST`` once and the next good read
    prints ``state`` again - an unlocked demod must never be presented as an alert transition. Returns the
    number of alert rises seen.
    """
    started = clock()
    previous = None
    alerts = 0
    while True:
        value = read()
        if value is None:
            if previous is not None:
                emit("LOST   no lock")
                previous = None
        elif previous is None:
            emit("state  " + describe(value))
            previous = value
        elif value.ewbs != previous.ewbs:
            emit(("ALERT  " if value.ewbs else "CLEAR  ") + describe(value))
            if value.ewbs:
                alerts += 1
            previous = value
        if seconds and clock() - started >= seconds:
            break
        sleep(interval)
    return alerts
