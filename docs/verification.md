# Verification

Three kinds of evidence are kept apart here:

- **machine evidence** — unit tests, the Java self-test, the firmware hash.
  Reproducible without a stick.
- **bench evidence** — runs on the physical `048d:9308` on Windows,
  2026-10-23. They cannot be repeated by someone without the stick and the
  DTA-115 feed.
- **app evidence** — the Android 9308 path in the OpenDTV tree. It used the
  vendor's JNI library, so it proves the USB shape on a phone, not this repo's
  clean-room core.

## Machine evidence — re-run 2026-11-02

```
python -m unittest discover -s tests
Ran 14 tests in 0.010s
OK
```

CPython 3.14.3, Windows. None needs hardware or the vendor image (checked by
pointing `IT9308_FIRMWARE` at a missing path; the result is the same).

| Test | What is asserted |
|---|---|
| `test_transport` | the captured QUERYINFO frame's checksum is `0xFEDC`; `PacketAligner` locks on a mid-packet read and carries a split packet |
| `test_sequence` | the table has >900 steps, every length byte is `len(frame)-1`, delays are 0..500 ms, reply hints are sane |
| `test_firmware` | a missing image raises `FileNotFoundError`; a 6,498-byte file with the wrong bytes raises `ValueError` |
| `test_device` | `chip_id()` writes `0xFD` to bus 2 / `0x66` and returns the first reply byte, checked against a fake I2C transport |
| `test_tune` | `patched(599143)` is byte-identical; `patched(473143)` changes exactly two frames, reseals their checksums, and rejects out-of-range values |
| `test_status` | fake I2C; `status()` decodes lock, SNR 1860 -> 23.66 dB and RF index 66 -> strength 66, all on 0x64 |

The 6,498-byte image's SHA-256 is pinned in `it9308/firmware.py`:
`e4e94633b4ac47c6bba5ab90eedd4a7e5ffa2ce7e342884c91749c7464704a70`.

### Java self-test — 2026-10-23

Prebuilt classes and a fresh compile both pass with JDK 17:

```
it9308 java self-test: OK (952 steps)     # java/out
it9308 java self-test: OK (952 steps)     # javac of src/main + src/test
```

The machine's default `java` is 1.8 and rejects the class files (version 61),
so the run used the JDK 17 shipped in `OpenDTV/tools/jdk17`. That is an
environment fact, not a code failure.

### Android transport compile check — 2026-11-02

The new `java/android/` adapter was compiled with JDK 17 against
`platforms/android-34/android.jar`:

```
javac -source 8 -target 8 -cp android.jar -d out (7 sources)
exit 0
```

That is a build check only; the adapter has not run on a phone.

## Bench evidence — Windows, 2026-10-23

Stick on USB bus 1, firmware already `0x010a0000` (no upload needed). Feed:
DTA-115 (serial `4115002287`, port 2) at 599.143 MHz, driven by StreamXpress.
The feed was idle at 36 MHz / output off at 12:45; it came up after the playout
was started.

### Bring-up audit

```
python tools/audit_replay.py
firmware version: 0x010a0000
replayed 952 steps in 4.5 s
failures: 0
request/response seq mismatches: 0
```

`audit_replay.py` checks every response's length, checksum, result byte and
sequence echo. `device._replay()` itself ignores the result byte, so this is a
separate check, not something the driver already proved.

Read back after the replay:

| register | value |
|---|---|
| `0xDA4C` TS enable | `01` |
| `0xDA58` | `00` |
| `0xDA51` | `00` |
| `0xDA73` | `03` |
| `0xDA78` | `47` |
| `0xDA5A` | `1F` |
| `0xDD88` frame size (2 bytes) | `B0 0E` (little-endian 3,760) |
| `0xDA14` / `0xDA17` | `01` / `1F` |

Chip type at `0x1222` (3 bytes): `01 06 93`, the same as the 9309; the field
is `0x9306`, so both use the generic I2C body.

### Live run — 45.0 s

| Check | Result |
|---|---|
| duration | 45.0 s |
| endpoint bytes | 33,299,072 |
| packets emitted | 177,043 (33,284,084 bytes) |
| bad sync bytes | **0** (every emitted packet starts `0x47`) |
| framing loss | 14,960 bytes (~79 packets, one resync) |
| bitrate | **5.919 Mbps** |
| `transport_error_indicator` | 0 on all 177,043 packets |
| PAT | programs 2624 / 2625 / 2648 -> PMT `0x0101` / `0x0102` / `0x1FC8` |
| PMT | H.264 (`0x1B`) on `0x0111`/`0x0121`/`0x0211`; audio (`0x11`) on `0x0112`/`0x0122`/`0x0212`; PCR `0x0100`/`0x0120`/`0x0210` |
| CC discontinuities | 16,728 (13,829 on the video PID) |

Two more runs on the same feed:

| Run | Result |
|---|---|
| `bench.py --seconds 15` | 57,682 packets, 5.79 Mbps, 0 bad sync, one resync discarding 15,120 B (~80 packets) |
| `play --seconds 15` (shipping CLI) | 55,921 packets, 10,513,148 bytes, ~5.6 Mbps; the CLI does not report framing loss |

### The continuity number is the feed, not the stick

The 00:34 capture of the same mux (`.tmp/9308.ts`, taken before this session)
had **6** CC discontinuities in 44,002 packets. The 12:57 run had 16,728. The
emitted framing stays clean and TEI is clear; the gaps are single or double
packets, not the 20-packet burst a dropped 3,760-byte USB frame would produce.
So the playout was dropping packets. The exact file StreamXpress played was not
identified: the first packet of the capture matches `RadyoTV.ts` at the position
where the previous session stopped, which is consistent with a stale FIFO
packet rather than the current source. This figure is therefore not a property
of the stick.

### Earlier capture — 00:34

| | |
|---|---|
| bytes / packets | 8,272,376 / 44,002 |
| bad sync bytes | 0 |
| CC discontinuities | 6 |
| PSI | same three programs and PIDs as the 12:57 run |

### Re-plug — 2026-11-02

The stick was re-attached and the bridge had lost its firmware (`QUERYINFO`
`0x00000000`). `probe` uploaded `1.10.0.0`, replayed 952 steps, and read the
demod chip ID **`0x6A`** directly: write `FD` to bus 2 / `0x66`, read one byte.

### Stream run — 2026-11-02 (ABS-PANAY)

The DTA-115 was freed and retuned to 599.143 MHz (ISDB-T, 6 MHz, Ch 34),
playing `D:\Broadcasting Files\Transport Streams\ISDB-Tph\ABS-PANAY.ts`
(11,608,837 bps file, 29:59). This is a **different mux** from the 2026-10-23
feed: PAT has seven programs (3200..3205 and 3224) and PMTs
`0x0456..0x0488`/`0x1FC8`.

| run | duration | endpoint bytes | packets | framing loss | bad sync | bitrate |
|---|---|---|---|---|---|---|
| A (with `--out`) | 45.0 s | 55,317,632 | 294,162 | 15,120 B (80 pkt, one resync) | 0 | 9.834 Mbps |
| B | 45.0 s | 54,370,112 | 289,201 | 184 B (0 pkt) | 0 | 9.665 Mbps |

TEI was 0 in both. The 20 s A/B runs also showed 0 bad sync and 0 TEI, with
31 and 43 CC discontinuities over ~131,600 packets (0.03%).

### Read-size A/B — 2026-11-02

Same feed, two processes, 20.0 s each:

| read size | endpoint bytes | packets | framing loss | bad sync | bitrate | CC |
|---|---|---|---|---|---|---|
| 16,356 B (current) | 24,741,312 | 131,601 | 240 B (1 pkt) | 0 | 9.892 Mbps | 31 |
| 15,040 B (vendor batch) | 24,756,352 | 131,681 | 212 B (1 pkt) | 0 | 9.900 Mbps | 43 |

No measurable difference, so `TS_READ` stays 16,356. The device returns the
same 15,040-byte boundaries either way.

### Tune parameterisation — 2026-11-02

The DTA-115 was moved to 473.143 MHz (ISDB-T, Ch 13, same `ABS-PANAY.ts`) and
the captured sequence replayed with only the two 24-bit kHz fields changed; the
frame checksums were recomputed:

| path | frequency | run | packets | bad sync |
|---|---|---|---|---|
| scratch patched replay | 473.143 | 10 s | 65,281 | 0 |
| CLI `play --freq 473143` | 473.143 | 10 s | 66,003 | 0 |
| CLI `play --freq 599143` | 599.143 | 10 s | 65,282 | 0 |

The patched 473.143 frames end `...073837fffe9b55` and
`...073837fffea155`. Without resealing, the old checksum (`...fffeaf23`) would
be wrong: the Java `Sequence.patched` reused it, so its 473.143 path had never
been valid. That is fixed and covered by the Java self-test.

### Status read — Windows, 2026-11-03

Same `probe` on the PC, DTA-115 at 599.143 (ABS-PANAY):

- locked: `lock True`, SNR 21.25 dB, RF 51, TS 105,280 B;
- empty 503.143 (feed still at 599): `lock False`, SNR -6.02 dB, RF 12,
  376 B (two residual packets);
- live 1 Hz while reading TS for 12 s: 12/12 `lock True`, SNR 21.3-21.8 dB,
  RF 52, **48,239 packets, 0 bad sync**.

The Python `status()` is the same 0x64 read as Android, and the live poll does
not disturb the stream. The Pi was measured on 2026-11-03: TV5 497.143
`lock True`, 14.77 dB, RF 49; live 1 Hz 12/12, SNR 14.3-18.0 dB, RF 47-49,
**37,280 packets, 0 bad sync**. Empty 503 gave `lock False`, -9.03 dB, RF 0,
no TS; tuning to the empty mux left the bridge wedged, and a USB reset
recovered it before the next open.

## Linux / Raspberry Pi — 2026-11-02

Raspberry Pi 5, aarch64, Debian (kernel 6.18.39), Python 3.13.5, pyusb 1.2.1,
libusb 1.0.5.0, `048d:9308` on bus 1. The rule from `udev/99-it9308.rules` was
installed as `/etc/udev/rules.d/99-it9308.rules`; the node became
`crw-rw-rw-` and no kernel driver bound.

- 12/12 unit tests pass on the Pi.
- `probe --freq 479143` uploads `1.10.0.0` (blank after plug), replays 952, and
  reads chip ID `0x6A`.
- Outdoor antenna, 2026-11-02, 3 s per channel:

| frequency | packets | sync | Mbps | programs | result |
|---|---|---|---|---|---|
| 479.143 (GMA) | 16,403 | 16,403 | 7.816 | 8 | hit |
| 485.143 (ALLTV) | 7,842 | 7,842 | 3.826 | 1 | hit |
| 491.143 (IBC) | 551 | 551 | 0.239 | 3 | hit |
| 497.143 (TV5) | 9,040 | 9,040 | 4.412 | 5 | hit |
| 503.143 (RPN) | 2 | 2 | 0.001 | 0 | - |
| 509.143 (A2Z) | 7,600 | 7,600 | 3.684 | 3 | hit |

- 20 s capture on 479.143: 20,710,456 bytes, **110,162 packets**, 0 bad sync,
  0 framing loss, **8.28 Mbps**, PAT 8 programs. The file is `~/gma.ts` on the
  Pi.

One USB command timeout during the first scan wedged the bridge; a USB reset
recovered it. `tools/scan.py` now resets and reopens on a failed channel and
retries once, which is how the table above was obtained. 503.143 delivered only
2 packets and is recorded as absent/weak, not a driver failure.

## Android clean-room — 2026-11-02 (OpenDTV-MOD)

The clean-room core was integrated into OpenDTV-MOD and run on a phone. Its
measurements:

- `bringUp` `0x010a0000`, chip ID `0x6A`, 952 steps — same as the Windows/Pi runs;
- `tune(479143)` succeeded, and a 38-frequency sweep produced no tune failure;
- stream 8.24–8.29 Mbps, 0–2 bad sync bytes after the first window, max USB gap
  30 ms;
- GMA 479.143 selected video/avc + audio/mp4a-latm and played; broadcast
  captions drew;
- permissions survived repeated force-stop/restart cycles.

This was the first hardware run of `java/android/`.

After that run, three changes were added: `status()` (lock, raw RF, SNR), the
ten-request queued `AndroidTsReader`, and `retune()` (17-step tune block). They
compile, and Python (16 tests) and the Java self-test pass, but have **not** been
re-run on the phone. The status registers were then measured on the phone, GMA 479.143 versus empty
503.143:

| field | register | decoding |
|---|---|---|
| lock | `0x64` reg `0x10` | bit `0x01`; GMA `0x21`, empty `0x10` |
| SNR | `0x64` reg `0x13`/`0x14` | 16-bit BE; GMA `0x0744` -> 23.7 dB, empty `0x0002` -> -6.0 dB |
| RF | `0x64` reg `0x11`/`0x12` | relative index `((b1>>5)|(b0<<3))`: 599 51-52, GMA 66-74, empty 0-12; `strength=min(100,index)` — 9175-style raw clamp, not dBm |

Four locked runs gave `rawSnr` 1625..2058 (**23.08..24.10 dB**); the empty mux
gave `0x0002` = **-6.02 dB**, exactly the predicted value. The app reads this
A 1 Hz poll on the corrected `0x64` read ran **60/60 reads while streaming**:
lock stayed `0x21`, SNR moved 0x0b70-0x0e9d (23-27 dB), RF `0x0947-0x094c`
(S 74), and the stream stayed at 6.1-6.3 Mbps with no stall or short reads.
The earlier "polling kills TS" was the old page-1/RF shape; live S/Q is safe on
this shape. The app now polls at 1 Hz.

The queued reader is now verified: **8.27-8.28 Mbps, 0 bad sync, 0 short reads**
on GMA, after one stale completion from the previous loop was skipped. It is
the better path than blocking on this device.

A 5-minute soak on TV5 497.143 (queued reader, depth 10) gave:

```text
1,441,407 packets, 8.27-8.28 Mbps, 0 bad sync, 5 short reads
max gap 18-19 ms, pipe drops 0, 58 continuity errors (~0.2/s)
```

API-34 length is confirmed: the first mapped completions show
`position() = 0 / 512 / 15040`, so `ByteBuffer.position()` is the transfer
length and the earlier `pos=0` was a genuinely empty transfer taken before the
gate opened. No reader change needed.

TV5 audio is MPEG-1 Layer II (`0x03`), which the app does not select; that is
an app-side audio story, not a tuner fault.

`retune()` is a **proven no-op**: `retune(503143)` (empty) still delivered 11,360
GMA packets in 2 s, identical to 479.143. The 17-step block is missing the
PLL/switch writes; full `tune()` (952 steps) is the only proven mux change.

## App evidence — Android, OpenDTV vendor path

OpenDTV's private 9308 source loads `libendeavour-sony-jni.so` and drives
the stick through `com.adth.endeavoursony.e`, which owns the
`UsbDeviceConnection`. What it establishes, with the same endpoint map as this
repo:

- interface **0**, endpoints found by address: `0x02` OUT, `0x81` IN, `0x84` IN;
- `UsbManager.openDevice` + `claimInterface(intf, true)`;
- command transfers 5,000 ms, exact-length;
- **TS reads 15,040 bytes** = 4 × 3,760, via ten queued `UsbRequest`s or a
  blocking `bulkTransfer(..., 15040, 5000)`.

That is the same 15,040-byte boundary measured on Windows. It does **not**
cover this repo's core by itself: `SelfTest` uses a fake, and the clean-room
adapter is now `java/android/` (compile-checked, not run on a phone). The
`sony9308-wrapper` in that tree is a scaffold with three unresolved TODOs; the
working path is the vendor one. None of that vendor code or the `.so` is in
this repo.

OpenDTV's public hardware table lists only `048d:275a`, so it does not claim
9308 support publicly either.

### Vendor APKs — 2026-11-02

Teardown of AIRialTV GO 0.2.6 / 1.0.6 / 2.0.4 and Tolka ABS TV 1.0.38; details
and offsets are in `docs/vendor-apks-2026-11-02.md`.

- The Sony 6,498-byte image is unchanged in 0.2.6, 1.0.6 and Tolka
  (`e4e94633...`); the Panasonic 7,013-byte image is unchanged too. There is no
  newer 9308 bridge firmware in these APKs.
- 2.0.4's native libraries are whole-payload packed (530,393 of 532,496 bytes
  differ from 1.0.6); no image is statically readable, but its Java is.
- The 1.0.6/2.0.4 Java gives the exact USB shape: interface 0, endpoints by
  index (0 = `0x81`, 1 = `0x02`, 2 = `0x84`), **500 ms** command transfers, and
  15,040-byte TS reads through ten queued `UsbRequest`s. The older
  `com.adth.endeavoursony.e` path above used 5,000 ms; both are vendor code,
  and 500 ms is the newer one.
- `fw_060` exists only as expected-path strings in the 9309 library, not as
  data: the known PSEQ/TNCTL/chfile blobs are absent and there is no Intel-HEX
  text.
- No bench evidence from this: the 9308 was not on the bus on 2026-11-02 (only
  the 9309).

## Not verified

1. **macOS runtime** — the same libusb path, never executed there. Linux is
   measured on the Raspberry Pi (next section).
2. **This core in an Android app** — `java/android/` now supplies
   `AndroidTransport` + `AndroidTsReader` and compiles, but it has not run on a
   phone; the app evidence above used the vendor library.
3. **Frequency parameterisation** — Python replays 599.143 MHz only. The Java
   `Sequence.patched` substitutes the three frequency bytes but has not been
   validated on hardware, and a second channel was not available.
4. **Long-run stability** — no hours-long run, no USB-drop test.
5. **A clean feed for the CC figure** — the playout was dropping packets; see
   above.
6. **Off-air reception through this driver** — the bench feed was the DTA-115,
   not an antenna.

Suggested first run on a new machine:

```bash
python -m it9308 list
python -m it9308 probe
python -m it9308 play --seconds 30 --out first.ts
python tools/bench.py --analyze first.ts
```

If `probe` fails, run `python tools/audit_replay.py` and check the firmware
version first (`list` does not upload; `probe`/`play` do).
