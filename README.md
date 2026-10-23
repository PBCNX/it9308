# it9308

User-space driver for USB ISDB-T tuners built on the ITE IT930x bridge with a
Sony demod (`048D:9308`). It loads the bridge firmware, applies the captured
952-step bring-up sequence, and streams MPEG-TS to a file, stdout or UDP.

## Requirements

- Python 3.9+ and libusb 1.0 (a 64-bit DLL is bundled for Windows)
- Windows: bind the dongle to WinUSB with Zadig
- pyusb is vendored, no pip install needed

## Firmware

The 6,498-byte bridge firmware is vendor material and is not included in the
public snapshot. Supply it with `--firmware PATH` or `IT9308_FIRMWARE`, or place
it at `it9308/firmware.bin`. The driver verifies its SHA-256 before uploading.

The bridge has no flash: a replug clears the firmware and `QUERYINFO` reads
`0x00000000` until it is uploaded again. The driver does that automatically in
`play`/`probe`.

## Usage

```bash
python -m it9308 list
python -m it9308 probe
python -m it9308 play --out capture.ts
python -m it9308 play --seconds 20 --out capture.ts
python tools/bench.py --seconds 20 --out capture.ts
python tools/audit_replay.py
```

`bench.py` also re-measures a file without touching hardware:

```bash
python tools/bench.py --analyze capture.ts
```

## Status

Tuning is the captured 599.143 MHz sequence; parameterisation is pending, so
the frequency is fixed.

Measured on the bench, 2026-10-23 12:57 (live stick, firmware `1.10.0.0`,
952/952 replay commands accepted):

| | |
|---|---|
| duration | 45.0 s |
| endpoint bytes | 33,299,072 (33,284,084 emitted as 177,043 packets) |
| packets | 177,043 |
| sync errors | **0** (every emitted packet starts `0x47`) |
| framing loss | 14,960 bytes (~79 packets, one resync) |
| bitrate | **5.92 Mbps** |
| PSI | PAT programs 2624->PMT `0x0101`, 2625->`0x0102`, 2648->`0x1FC8` |
| elementary streams | H.264 (`0x1B`) on `0x0111`/`0x0121`/`0x0211`; audio (`0x11`) on `0x0112`/`0x0122`/`0x0212`; PCR `0x0100`/`0x0120`/`0x0210` |

A second 15 s run measured 57,682 packets / 5.79 Mbps / 0 sync errors, with one
resync that discarded 15,120 bytes (about 80 packets). The shipping `play`
command on the same feed wrote 55,921 packets (10,513,148 bytes) in 15 s, about
5.6 Mbps; that command does not report framing loss.

**Feed/path note:** that capture carries 16,728 continuity discontinuities
(13,829 on the video PID), while the 00:34 capture of the same mux had 6, and
each live run lost one ~15 KB buffer to a resync. `transport_error_indicator`
is clear throughout, and the CC gaps are single packets rather than the
20-packet burst a dropped 3,760-byte frame would make. Both point at the
playout/feed; re-measure once the DTA-115 playout rate is known good before
treating either number as a property of the stick.

Earlier validated capture (`.tmp/9308.ts`, 2026-10-23 00:34): 8,272,376 bytes
in 44,002 packets, 100% sync, 6 CC discontinuities.

## Licence

MIT (see `LICENSE`). Written from the observed USB protocol; no vendor source,
decompiled code or binaries are used.
