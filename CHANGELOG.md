# Changelog

## 0.3.0 — 2026-11-24

- Package renamed to `com.pbcnx.drivers.it9308`; the Android door contract is `com.pbcnx.tuner` 2.0.0.
- `java/`: a dependency-free core, the Android transport and reader, and a door provider for the host app.
- TMCC: `valid()` and a settled read (two agreeing readings) close the zero trap; EWBS is reported where the part
  exposes it, and mode/guard are translated to the shared numbering.
- Channel change: the retune replays the tail of the captured sequence with the stream paused, measured at
  0.17-0.20 s; the first tune after opening costs nothing when it is the captured frequency.
- Recovery: the four-state ladder, and a door `recover()` that answers "not in software" instead of resetting the
  USB link (a reset re-enumerates the stick and needs a new permission grant).
- Reader: the transport counts zero-length completions, null completions and timeouts again, so "0 bad sync" has
  evidence behind it.
- CLI: a missing image is checked before the device is opened - one line, exit 2; any unexpected failure prints one
  line, never a traceback.
- `play`, `scan`: quality is the shared stream meter (5 s window over the TS), the demod's SNR reported separately.
- Firmware is verified for size and SHA-256 before use, and is never distributed in this repository.

## 0.2.1 — 2026-11-03

- Windows, macOS and Linux measurements; the supervisor that survives a replug; the TMCC and IIP decoders.

## 0.2.0 — 2026-11-03

- First release: firmware upload, tune, lock, MPEG-TS read, TMCC fields.

## 0.1.0 — 2026-10-23

- First working protocol against the dongle.
