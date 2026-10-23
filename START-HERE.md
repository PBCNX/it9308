# Start here - the IT930x + Sony stick (048d:9308)

Read this first; `docs/protocol.md` is the shared bridge reference and
`it9308/sequence.py` is the 952-step capture.

## What it is

IT930x bridge + Sony ISDB-T demod ("DGI1011", `048d:9308`); demod on I2C bus 2
at 7-bit `0x64`/`0x66`. The 6,498-byte vendor image reports `1.10.0.0`; the
private tree carries it and `release.ps1` withholds it from the public snapshot.

**`it9309` imports `it9308.transport`** - do not change its public shape alone.

## Bench state (2026-10-23, ~13:00)

- bus 1, firmware `0x010a0000`; a replug needs a re-upload, `play`/`probe` do it
- **952/952 replay commands result 0 and echo seq** (`tools/audit_replay.py`)
- TS block: `da4c=01 da73=03 da78=47 dd88=b00e da5a=1f da14=01 da17=1f`
- live: **177,043 packets / 45.0 s / 5.92 Mbps / 0 bad sync bytes**; one resync
  discarded 14,960 B (~79 packets)
- feed is a DTA-115 at 599.143 MHz (StreamXpress). Today it drops ~9% of packets
  (16,728 CC against 6 at 00:34); emitted packets are in sync and TEI=0, so the
  CC number is a bench observation, not a stick property

## Commands

```
python -m it9308 list
python -m it9308 probe
python -m it9308 play --seconds 20 --out capture.ts
python tools/bench.py --seconds 20 --out capture.ts
python tools/bench.py --analyze capture.ts
python tools/audit_replay.py
python -m unittest discover -s tests
```

## Proven - do not re-derive

- firmware: `0x22`; if 0, `0xF103 = 7`, 137 scatter records via `0x29`, BOOT
  `0x23`, re-query. The whole 952-step sequence is accepted.
- PSI: programs 2624/2625/2648 -> PMT `0x0101`/`0x0102`/`0x1FC8`; H.264
  (`0x1B`) on `0111`/`0121`/`0211`; audio (`0x11`) on `0112`/`0122`/`0212`;
  PCR `0100`/`0120`/`0210`.
- the tune is an I2C write to bus 2 / `0x66` carrying 24-bit kHz `09 24 67` =
  599,143 kHz; it appears twice in the capture.
- `0x1222` reads `01 06 93` on this stick, the same as the 9309 -> generic I2C.

## Closed - do not reopen

- "the replay is silently failing" - audited, 952/952 result 0.
- "the TS block never got enabled" - `0xDA4C` reads `01`.
- "it needs a different firmware" - `1.10.0.0` boots and streams.
- Python has no frequency parameterisation; the Java `Sequence.patched` is
  unvalidated and is not evidence.

## Next moves

1. Get the playout rate right, re-run `bench.py`; CC should fall to single digits.
2. Parameterise the tune: substitute the three frequency bytes, validate on a
   second known channel. The one real feature gap.
3. Keep `transport.py` stable; if it changes, update `it9309` with it.

## Traps that have cost hours

- **one open per process** - `Device.close()` leaks the pyusb handle.
- EP `0x84` with a 16,356-byte request returns 15,040 bytes (4 x 3,760, the
  frame size) - a frame boundary, not a short read.
- checksum is one's complement over **big-endian** 16-bit words, stored
  big-endian; the 9309 notes' "little-endian" wording is wrong.
- `0xDD88`/`0xDD89` is a **little-endian** frame size: `B0 0E` = 3,760, not `0E B0`.
- a GPIO output register does nothing until mode=output and enable=1.
- firmware is vendor material: private tree only, `release.ps1` withholds it.

## Where the detail is

| file | what |
|---|---|
| `docs/protocol.md` | commands, frames/checksum, firmware records, GPIO map, TS block |
| `it9308/transport.py` | frames, checksum, I2C, `PacketAligner` |
| `it9308/sequence.py` | the 952 captured steps |
| `tools/bench.py` / `tools/audit_replay.py` | measurements / response audit |
| `docs/9309.md` | pointer to the separate 9309 tree (different demod) |
