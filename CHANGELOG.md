# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

## [0.2.0] - 2026-11-03

### Added

- Live 1 Hz lock/SNR/RF status on Windows, Raspberry Pi and Android; S/Q meter.
- Verified ten-request queued Android TS reader, including stale-completion
  handling and restart-before-retune ordering.
- Windows and Pi status evidence; 5-minute TV5 queued soak (0 bad sync).
- Visible provenance marker `it9308-pbcnx` (attribution, not telemetry).
- Project-author copyright: The IT9308 Open Driver Authors.

### Changed

- Status uses the corrected plain `0x64` read; RF is a 9175-style relative
  clamp (`min(100,index)`), not calibrated dBm.
- `retune()` is deprecated; full `tune()` is the only mux change.
- Android is hardware-verified through OpenDTV-MOD; no APK is shipped here.

### Fixed

- Queued reader no longer exits on a stale completion from the previous loop.
- The old “polling status kills TS” rule was a wrong page/bank read; 1 Hz
  polling is safe.

### Removed

- The 17-step fast-retune block, measured as a no-op.

### Security

- No telemetry, no network calls, no device/user identifiers. The 6,498-byte
  vendor firmware remains private and is not covered by the MIT licence.

## [0.1.0] - 2026-10-23

- Initial public release: firmware upload, 952-step bring-up, tune, TS capture,
  Python CLI, JVM core.
