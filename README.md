# it9308 — ITE IT930x ISDB-T dongle (`048d:9308`)

User-space driver for the ISDB-T dongle sold as **TVplus Go** (ITE IT930x bridge + Sony ISDB-T
demodulator). It speaks the dongle's own USB protocol, uploads its firmware, tunes, and streams MPEG-TS to a
file, stdout or UDP; it also reads the multiplex's transmission parameters (TMCC) and the IIP. Python over
libusb (pyusb is vendored, so there is nothing to install); a dependency-free Java core for Android lives in
`java/`.

**Our own code, no vendor code.**

## Device

| | |
|---|---|
| USB ID | `048d:9308` |
| Chip | ITE IT930x USB bridge with a Sony ISDB-T demodulator, 6 MHz raster |
| Product string | `DGI1011` |
| Endpoints | `0x02` OUT commands, `0x81` IN responses, `0x84` IN MPEG-TS |
| Status | lock, relative RF strength, SNR from the demod's own registers |
| TMCC | mode, guard interval, partial reception, EWBS, layers A/B/C (modulation, code rate, interleave, segments) |
| IIP | PID `0x1FF0`, one TSP per frame, CRC-32 checked |

## Platforms

Windows, Linux (aarch64), macOS (Intel) and Android are measured on hardware; Linux x86_64 and Apple Silicon are
not yet tested. No kernel driver is involved: libusb over WinUSB on Windows, udev on Linux, libusb on macOS.

## Install

From a checkout — pyusb is vendored, so no `pip install` is needed.

```bash
python -m it9308 --version      # it9308 0.3.0 (it9308-pbcnx)
python -m it9308 list           # finds the 048d devices present
python -m it9308 tmcc --freq 497143   # needs the stick (and firmware)
```

- **Windows**: bind the dongle to WinUSB with [Zadig](https://zadig.akeo.ie/) and replug it, then get
  `libusb-1.0.dll` from <https://libusb.info> and set `IT9308_LIBUSB` to its full path (or put it next to
  `python.exe`). Zadig is the device binding; libusb is the library the driver loads.
- **Linux**: `sudo cp udev/99-it9308.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo
  udevadm trigger`, then replug. The rule grants `uaccess` plus group `plugdev` (needed over SSH, where there
  is no logind seat).
- **macOS**: install libusb (`brew install libusb`); on Apple Silicon use an arm64 Python and libusb.

**Firmware.** The image is not in this repository — it is vendor material. Supply your own with `--firmware PATH`
or `IT9308_FIRMWARE`; it is checked for size and SHA-256 before use. `--version` and `list` work without it;
anything that opens the stick needs it.

## Use

```bash
python -m it9308 list
python -m it9308 probe
python -m it9308 tmcc  --freq 497143
python -m it9308 play  --freq 497143 --seconds 30 --out capture.ts
python -m it9308 recover
```

Android / JVM:

```java
Tuner tuner = provider.open(context, device, firmware, listener);
tuner.open();
tuner.tune(497143);
Tmcc tmcc = tuner.tmccSettled(8, 150);
```

The Java core in `java/` is plain Java (no Android types) and has no third-party dependencies; the Android
pieces add a `UsbDeviceConnection` transport and a queued reader. An Android app supplies the USB side and the
firmware image, and compiles the source it needs into its own build.

## License

MIT — see `LICENSE`. `NOTICE` lists what is not ours.
