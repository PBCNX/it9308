# it9308 — ITE IT930x + Sony ISDB-T dongle (`048d:9308`)

User-space driver for the ISDB-T dongle sold as **DGI1011** / TVplus Go
(ITE IT930x bridge, Sony demodulator). It uploads the bridge firmware, replays
the captured 952-step bring-up, tunes a centre frequency and streams MPEG-TS to
a file, stdout or UDP. libusb on Windows, macOS and Linux; a pure-JVM core for
Android. No kernel driver, no vendor library.

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
| **Android** | 🟡 clean-room core, live 1 Hz S/Q, and queued reader verified on a phone (OpenDTV-MOD); 5-min TV5 soak 0 bad sync; retune no-op, full tune only |

Measured on Windows (WinUSB/Zadig) with a DTA-115 at 599.143 MHz: **177,043
packets in 45.0 s, 5.92 Mbps, 0 bad sync bytes**, PAT/PMT with three programs.
The feed itself was losing packets that day (16,728 continuity discontinuities
against 6 in an earlier capture) and one resync discarded 79 packets; both are
recorded in [`docs/verification.md`](docs/verification.md) and are not
attributed to the stick.

The stick was on USB bus 1 on 2026-10-23. `python -m it9308 list` is the current
answer, not this paragraph.

Re-plugged on 2026-11-02: the firmware was blank, `probe` re-uploaded
`1.10.0.0`, all 952 steps replayed, and the demod reports chip ID **`0x6A`**.
The feed was then freed and retuned to 599.143 (ISDB-T `ABS-PANAY.ts`, a
7-program mux): 45 s runs of 294,162 packets / 9.83 Mbps and 289,201 packets /
9.67 Mbps, 0 bad sync; the first had one 80-packet resync, the second none.
A read-size A/B (16,356 vs 15,040 bytes) made no measurable difference.
`--freq 473143` also locks on the retuned transmitter: 66,003 packets in 10 s,
0 bad sync (65,282 at 599.143).

On a Raspberry Pi 5 (aarch64, Python 3.13, pyusb 1.2.1) with an outdoor antenna,
2026-11-02: a 479–509 MHz scan found **5 of 6 channels** (479 GMA, 485 ALLTV,
491 IBC, 497 TV5, 509 A2Z), and a 20 s capture on 479.143 gave **110,162
packets / 0 bad sync / 8.28 Mbps** with 8 programs.

## Install

From a checkout — the supported way, nothing to install. pyusb 1.3.1 and a
64-bit `libusb-1.0.dll` are vendored:

```bash
python -m it9308 list
```

`python -m it9308 --version` prints `it9308-pbcnx` alongside the version. That
is a visible provenance marker for attribution/search, not telemetry; it makes
no network or device calls.

- **Windows**: bind the dongle to WinUSB with [Zadig](https://zadig.akeo.ie/).
  `IT9308_LIBUSB` points at a different DLL.
- **Linux**: `sudo cp udev/99-it9308.rules /etc/udev/rules.d/`, reload udev
  (`sudo udevadm control --reload-rules && sudo udevadm trigger`), replug. The
  rule grants `uaccess`; no kernel driver is involved. Not yet executed on a
  Linux host.
- **macOS**: install libusb (`brew install libusb`). If pyusb cannot find it,
  set `IT9308_LIBUSB=/opt/homebrew/lib/libusb-1.0.dylib`. Not yet executed on a
  Mac.

## Firmware

6,498 bytes, SHA-256
`e4e94633b4ac47c6bba5ab90eedd4a7e5ffa2ce7e342884c91749c7464704a70`, sent as
137 scatter records. The driver hashes it and refuses a different image.

The bridge has no flash: a replug clears the firmware and `QUERYINFO` reads
`0x00000000` until it is uploaded again. `play` and `probe` do that
automatically.

The image is vendor material and is **not in the public snapshot**: the private
tree carries it at `it9308/firmware.bin` and the release withholds it. Supply
it with `--firmware PATH` or `IT9308_FIRMWARE`; do not redistribute it (see
[`NOTICE`](NOTICE)). `list` and the tests do not need it.

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

The repo has **no Android USB transport**. The vendor app (AIRialTV GO
1.0.6/2.0.4, `com.adth.endeavoursony.Bus`) shows the exact shape: interface 0;
endpoints by **index** 0 = `0x81` IN, 1 = `0x02` OUT, 2 = `0x84` TS; command
`bulkTransfer` 500 ms exact-length; TS 15,040 B through ten queued
`UsbRequest`s (`requestWait(500)` on SDK 26+) or one blocking 15,040-byte read.
OpenDTV's private vendor-JNI path agrees on the endpoints and batch size. None
of that vendor code belongs here; the app-side `Transport` is now in
[`java/android/`](java/android/README.md) — compile-checked against
`android.jar`, not yet run on a phone. Details and evidence:
[`docs/vendor-apks-2026-11-02.md`](docs/vendor-apks-2026-11-02.md).

## More

- [`docs/protocol.md`](docs/protocol.md) — command set, frames/checksum,
  firmware records, GPIO map, TS block
- [`docs/verification.md`](docs/verification.md) — every number and its date
- [`START-HERE.md`](START-HERE.md) — bench state, commands, traps
- [`java/README.md`](java/README.md) — the JVM core and its self-test

## Licence

MIT — see [`LICENSE`](LICENSE). Copyright (c) 2026 The IT9308 Open Driver
Authors. The vendor firmware is outside the licence
([`NOTICE`](NOTICE)); the protocol code is written from captured USB traffic,
not from vendor source.
