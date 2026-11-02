# Verification

Evidence only: machine tests, bench runs, and Android runs. Dates are the run
dates; numbers are copied from the logs.

## Machine

```text
python -m unittest discover -s tests      ->  14 tests, OK
Java SelfTest                             ->  OK (952 steps)
java/android compile (JDK 17, API 34)     ->  exit 0
```

No hardware and no firmware image are needed for the tests. The firmware SHA-256
is pinned in `it9308/firmware.py`:
`e4e94633b4ac47c6bba5ab90eedd4a7e5ffa2ce7e342884c91749c7464704a70`.

Test coverage: transport checksum/aligner; sequence lengths/delays; firmware
size/hash errors; chip-ID I2C; tune patch (599.143 identical, 473.143 changed and
resealed); status lock/SNR/RF on `0x64`.

## Windows — 2026-10-23

Stick on bus 1, firmware `0x010a0000`, DTA-115 at 599.143 MHz.

- 952/952 replay commands accepted, 0 seq mismatches.
- 45.0 s: **177,043 packets, 5.92 Mbps, 0 bad sync bytes**.
- Feed dropped packets that day (16,728 CC; 6 in an earlier 44,002-packet
  capture), so the CC count is the playout, not the stick.
- PAT: 2624/2625/2648; H.264 on `0x0111`/`0x0121`/`0x0211`; audio on
  `0x0112`/`0x0122`/`0x0212`.

## Windows — 2026-11-02 (ABS-PANAY, 7 programs)

| run | duration | packets | bad sync | bitrate |
|---|---:|---:|---:|---:|
| A | 45.0 s | 294,162 | 0 | 9.834 Mbps |
| B | 45.0 s | 289,201 | 0 | 9.665 Mbps |

Read-size A/B (16,356 vs 15,040 bytes): no measurable difference (131,601 vs
131,681 packets, 0 bad sync). `TS_READ` stays 16,356.

Tune by patching the two 24-bit kHz fields and resealing checksums:

| path | frequency | run | packets | bad sync |
|---|---|---:|---:|---:|
| CLI `--freq` | 473.143 | 10 s | 66,003 | 0 |
| CLI `--freq` | 599.143 | 10 s | 65,282 | 0 |

## Status — Windows, 2026-11-03

- 599.143: `lock True`, SNR 21.25 dB, RF 51, TS 105,280 B.
- empty 503.143: `lock False`, SNR -6.02 dB, RF 12, 376 B.
- 1 Hz poll for 12 s while reading TS: 12/12 locked, SNR 21.3-21.8 dB,
  **48,239 packets, 0 bad sync**.

## Linux / Raspberry Pi 5 — 2026-11-02/03

Pi 5, aarch64, Python 3.13, pyusb 1.2.1; udev rule installed; 12/12 tests pass.

Real antenna, 3 s per channel:

| frequency | packets | bad sync | Mbps | programs |
|---|---:|---:|---:|---:|
| 479.143 GMA | 16,403 | 0 | 7.82 | 8 |
| 485.143 ALLTV | 7,842 | 0 | 3.83 | 1 |
| 491.143 IBC | 551 | 0 | 0.24 | 3 |
| 497.143 TV5 | 9,040 | 0 | 4.41 | 5 |
| 503.143 RPN | 2 | 0 | 0.001 | 0 |
| 509.143 A2Z | 7,600 | 0 | 3.68 | 3 |

20 s on 479.143: **110,162 packets, 0 bad sync, 8.28 Mbps**.

Status on 2026-11-03: 497.143 `lock True`, 14.77 dB, RF 49; 1 Hz poll 12/12
(SNR 14.3-18.0, RF 47-49), **37,280 packets, 0 bad sync**. Empty 503:
`lock False`, -9.03 dB, RF 0, no TS.

An empty-mux tune can wedge the bridge; a USB reset recovers it, then reopen.
`tools/scan.py` resets/retries a failed channel.

## Android clean-room — 2026-11-02/03 (OpenDTV-MOD)

- `bringUp` `0x010a0000`, chip `0x6A`, 952 steps.
- `tune(479143)` works; stream 8.27-8.28 Mbps; GMA video + audio played.
- Ten-request queued reader: **0 bad sync, 0 short reads**; 5-minute TV5 soak:
  **1,441,407 packets, 0 bad sync, 5 short reads, 58 CC (~0.2/s), max gap
  18-19 ms**.
- API-34 completion length is `ByteBuffer.position()` (0 / 512 / 15040); `pos=0`
  is an empty transfer, not a bug.
- Status: rawSnr 1625-2058 -> 23.08-24.10 dB; empty `0x0002` = -6.02 dB.
  A 1 Hz poll ran 60/60 while streaming, TS untouched.
- `retune()` is a no-op: retuning to empty 503 still delivered 11,360 GMA
  packets in 2 s. Full `tune()` only.
- TV5 audio is MPEG-1 Layer II (`0x03`), not selected by the app; app-side.

Status decode: `0x64` reg `0x10` bit 0 lock; SNR `0x13`/`0x14`
(`10*log10(raw)-9.031`); RF `0x11`/`0x12` relative index
(`strength=min(100,index)`, not dBm).

## Vendor Android path (evidence only)

OpenDTV's private path loads `libendeavour-sony-jni.so`; the 1.0.6/2.0.4 Java
gives interface 0, endpoints `0x02`/`0x81`/`0x84`, 500 ms commands, and
15,040-byte TS through ten queued `UsbRequest`s. No vendor code or `.so` is in
this repo. Vendor APK details: `docs/vendor-apks-2026-11-02.md`.

## Not verified

- macOS runtime (same libusb path; never executed).
- Long-run stability (no hours-long run, no USB-drop stress).
- Absolute RF/dBm (S is a relative 9175-style clamp).
- BER/PER (not decoded; no PER register).
- A clean CC reference on the 2026-10-23 feed (playout was dropping packets).
