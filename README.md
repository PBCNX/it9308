# it9308 — ITE IT930x + Sony ISDB-T dongle (`048d:9308`)

User-space driver for the ISDB-T dongle
ITE IT930x bridge + Sony demodulator. It uploads the bridge firmware, replays
the captured 952-step bring-up, tunes a centre frequency and streams MPEG-TS to
a file, stdout or UDP. libusb on Windows, macOS and Linux; a pure-JVM core for
Android.

## Device

| | |
|---|---|
| USB ID | `048d:9308` (product "DGI1011") |
| Bridge | ITE IT930x, reports chip type `0x9306` |
| Demod | Sony, chip ID `0x6A` (`0xFD`), I2C bus 2 at 7-bit `0x64`/`0x66`, page-switched |
| Endpoints | `0x02` OUT commands, `0x81` IN responses, `0x84` IN MPEG-TS |
| TS read | 15,040 B batches = 80 × 188 = 4 × 3,760 (the driver asks 16,356, the bridge returns 15,040) |
| Firmware | 6,498 B, 137 scatter records, reports `1.10.0.0` |

## Status

| Platform | State |
|---|---|
| **Windows** | ✅ measured 2026-10-23, 2026-11-02, 2026-11-03: lock, TS and live S/Q at 599.143 MHz |
| **Linux** | ✅ measured 2026-11-02/03 on a Raspberry Pi 5 (aarch64): real-antenna scan, 20 s capture, live S/Q |
| **macOS** | 🟡 same libusb path, never executed there |
| **Android** | ✅ clean-room core and transport verified in OpenDTV-MOD (live 1 Hz S/Q, queued reader, 5-min TV5 soak, 0 bad sync); no Android app/APK is shipped here |

`✅` measured on hardware; `🟡` code exists but has not been run on that platform.

## Firmware

6,498 bytes, SHA-256
`e4e94633b4ac47c6bba5ab90eedd4a7e5ffa2ce7e342884c91749c7464704a70`, sent as
137 scatter records. The driver hashes it and refuses a different image.

The bridge has no flash: a replug clears the firmware and `QUERYINFO` reads
`0x00000000` until it is uploaded again. `play` and `probe` do that
automatically.

## Run

```bash
python -m it9308 list
python -m it9308 probe                      # bring-up and a short TS read
python -m it9308 play --seconds 20 --out capture.ts
python -m it9308 play --freq 473143 --seconds 20 --out capture.ts
python -m it9308 play --seconds 20 --udp 127.0.0.1:5000
python tools/bench.py --seconds 20 --out capture.ts
python tools/bench.py --analyze capture.ts  # measure a file, no hardware
python tools/scan.py --start 479143 --end 509143 --dwell 3
python tools/audit_replay.py                # check all 952 responses
```

`--freq KHZ` patches the 24-bit kHz field in the two tune frames and recomputes
their checksums; 599.143 (captured) and 473.143 were both measured on
2026-11-02. There is no scan command.

## Tests

```bash
python -m unittest discover -s tests        # 14 tests, no hardware, no firmware image
```

The tests cover the frame checksum and aligner, the 952-step table and firmware
validation. There is no simulator: `bench.py` measures the endpoint, not a
model.

## Java / Android

`it9308/java` is a dependency-free JVM port of the protocol (bridge frames,
the 952-step sequence, the unvalidated frequency patch). `SelfTest` replays the
capture and compares writes with the Python command log:

```bash
cd java
java -cp "out;src/main/resources" ph.pbcnx.it9308.SelfTest
# it9308 java self-test: OK (952 steps)
```

Use JDK 17+; the checked-in `out` classes are class-file version 61 and a
Java 8 runtime rejects them.

## More

- [`docs/protocol.md`](docs/protocol.md) — command set, frames/checksum,
  firmware records, GPIO map, TS block
- [`docs/verification.md`](docs/verification.md) — every number and its date
- [`java/README.md`](java/README.md) — the JVM core and its self-test

## Licence

MIT — see [`LICENSE`](LICENSE). Copyright (c) 2026 The IT9308 Open Driver
Authors. The vendor firmware is outside the licence
([`NOTICE`](NOTICE)); the protocol code is written from captured USB traffic,
not from vendor source.
