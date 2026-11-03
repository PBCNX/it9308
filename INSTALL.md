# Install — all platforms

User-space driver for the **IT9308** ISDB-T stick (`048d:9308`). Source checkout
plus vendor firmware; no installer, no service, no GUI.

| platform | state |
|---|---|
| Windows 10/11 x64 | tested |
| Linux x86_64 / Raspberry Pi 5 | tested |
| macOS Intel x86_64 | tested 2026-11-03; Apple Silicon untested |
| Android | library only; tested via OpenDTV-MOD |

## Common

- **Python 3.9+**, 64-bit. Tested with 3.13.
- **pyusb is vendored** under `vendor/usb`; running from the checkout needs no
  `pip install`.
- **Firmware** `firmware.bin` (6,498 B) is required and is **not** in the public
  snapshot. The private checkout carries it at the root, or pass
  `--firmware PATH` / set `IT9308_FIRMWARE`.
- Run commands from the checkout root.
- The driver talks to the stick over USB only; no network, no telemetry.

```bash
python -m it9308 list
python -m it9308 probe --freq 497143
python -m it9308 play --freq 497143 --seconds 20 --out capture.ts
python -m it9308 play --freq 497143 --seconds 20 --out capture.ts --status-interval 2
python -m it9308 scan --start 473143 --stop 695143 --step 6000 --dwell 2
```

On Windows use `py -3` instead of `python`.

## Windows

1. Install **64-bit Python 3.9+**. Check: `py -3 --version`.
2. Plug in the stick. Run `py -3 -m it9308 list`.
3. If the stick is not listed, bind it to **WinUSB** with
   [Zadig](https://zadig.akeo.ie/): Options → List All Devices → `048d:9308` →
   WinUSB → Install Driver, then replug. Do this once.
4. Firmware: put `firmware.bin` in the checkout root.
5. The private checkout includes `vendor/windows/x64/libusb-1.0.dll`. If your
   copy does not (public snapshot), install libusb and point to it:

   ```powershell
   $env:IT9308_LIBUSB = "$env:USERPROFILE\libusb\libusb-1.0.dll"
   ```

6. Run:

   ```powershell
   py -3 -m it9308 probe --freq 599143
   py -3 -m it9308 play --freq 599143 --seconds 20 --out capture.ts
   ```

## Linux

Debian/Ubuntu/Raspberry Pi OS:

```bash
sudo apt install libusb-1.0-0
sudo cp udev/99-it9308.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Replug the stick, then:

```bash
python3 -m it9308 list
python3 -m it9308 probe --freq 497143
python3 -m it9308 play --freq 497143 --seconds 20 --out capture.ts
```

No kernel driver is used; the udev rule grants the logged-in user access.
Tested on a Raspberry Pi 5.

## macOS

1. Install libusb:

   ```bash
   brew install libusb
   brew --prefix libusb
   ```

2. Use a Python whose architecture matches libusb:
   - Apple Silicon: arm64 Python + `/opt/homebrew/...`
   - Intel: x86_64 Python + `/usr/local/...`

   Check: `uname -m` and `python3 -c 'import platform; print(platform.machine())'`.

3. If pyusb cannot find libusb:

   ```bash
   export IT9308_LIBUSB="$(brew --prefix libusb)/lib/libusb-1.0.dylib"
   ```

4. No udev is needed. Run:

   ```bash
   python3 -m it9308 list
   python3 -m it9308 probe --freq 497143
   python3 -m it9308 play --freq 497143 --seconds 20 --out capture.ts
   ```

macOS **Intel x86_64 is confirmed** (2026-11-03, Intel MacBook Pro, Python
3.13.2, libusb 1.0.30). Apple Silicon is still untested. If `open` fails, check
whether a kernel driver has claimed interface 0.

## Android

There is no installable APK here. Apps integrate the Java core in `java/` and
the Android transport in `java/android/`:

- JDK 17+, Android SDK/API 34 (`android.jar`);
- USB host + `device_filter.xml` for `048d:9308`;
- firmware supplied from app assets/private storage, not the repo;
- no vendor `.so` on the clean-room path.

OpenDTV-MOD is the reference integration. See `java/README.md` and
`java/android/README.md`.

## Firmware

The bridge has no flash: a replug clears it. `probe` and `play` upload it
automatically.

- Default: `firmware.bin` in the checkout root.
- Explicit: `--firmware PATH` or `IT9308_FIRMWARE`.
- SHA-256:
  `e4e94633b4ac47c6bba5ab90eedd4a7e5ffa2ce7e342884c91749c7464704a70`.
- Vendor material: do not redistribute; not in the public snapshot.

## Verify

```text
list   -> 048d:9308 ... supported
probe  -> firmware 0x010a0000, chip 0x6a, lock True, ts > 0
play   -> capture.ts grows, 0x47 sync
```

Empty mux: `lock: False`, SNR about −6 to −9 dB, little/no TS. That is expected.

## Troubleshooting

| symptom | cause |
|---|---|
| empty `list` | Windows: WinUSB not bound (Zadig); Linux: udev rule not loaded/replugged; macOS: wrong Python/libusb arch |
| libusb not found | set `IT9308_LIBUSB` (Windows/macOS) |
| firmware 0, upload fails | missing/wrong `firmware.bin`; check path and SHA |
| timeout after empty tune | bridge wedged; replug or USB reset |
| no lock/TS | wrong frequency, no antenna, or empty mux |
| status meter frozen | use current version; 1 Hz polling is verified |

## Licence

Driver code is MIT (`LICENSE`). The vendor firmware is outside the licence
(`NOTICE`); libusb and pyusb keep their own licences under `vendor/`.
