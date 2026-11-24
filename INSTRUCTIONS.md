# How to use the IT9308 driver

This guide is for anyone who has the stick and wants to watch or record TV with it. You do not need to be a programmer.
Follow the numbered steps in order.

---

## 1. What you need

1. The stick itself. It is sold as **TVplus Go** and contains the **ITE IT930x** chip. Its USB ID is `048d:9308`.
2. A computer running Windows, Linux or macOS with **Python 3.9 or newer**. Typing `python --version` should show that
   number, or higher.
3. The **firmware file** for this stick. The stick is blank when it is first plugged in, and this file is what brings it
   to life. Section 2 tells you exactly where to put it.
4. The driver itself: this repository, downloaded as a ZIP or cloned with git.

You do **not** need to run `pip install`. Everything the driver needs to talk to the stick is already in the folder.

---

## 2. Where to put the firmware file

This file is the manufacturer's, and this repository never ships it. You get it from vendor software you already have
(the app that came with the stick): find its firmware file, copy it somewhere you will remember, and tell the driver
where it is. The driver looks for it in this order and stops at the first one it finds:

1. **On the command line, for one run.** Add `--firmware PATH` to the command, and it wins over the other two.

   ```bash
   python -m it9308 play --freq 497143 --firmware "C:\path\to\firmware.bin" --out capture.ts
   ```

2. **In an environment variable, for every run.** Set `IT9308_FIRMWARE` to the full path of the file.

   ```powershell
   setx IT9308_FIRMWARE "C:\path\to\firmware.bin"
   ```

   ```bash
   export IT9308_FIRMWARE="$HOME/Downloads/firmware.bin"
   ```

   On Windows you can also use *System properties → Environment Variables*. `setx` only affects terminals you open
   afterwards; close the window and open a new one.

3. **In the driver's own folder, as the default.** Put the file beside the `it9308` package, named exactly
   `firmware.bin` (the names `it930x-firmware.bin` and `it9308-firmware.bin` also work). Nothing else needs to be set.

**On Android** there is no file path: the app supplies the image itself. It asks the user for the file once, keeps it,
and passes it to the driver when it opens the stick.

The driver checks the file before it uses it: the image must be **6,498 bytes** with a known **SHA-256 fingerprint**. A
file that does not match is refused, not written to the stick. If that happens you see one line:

```text
error: firmware at <path> is not the expected 6,498-byte image
```

**You can do a lot without this file.** `--version` and `list` work without it. Anything that opens the stick needs it,
because the stick cannot receive until it has been loaded, and the driver stops before opening the stick if the image
is missing — that is the one-line message in section 8, not a crash.

---

## 3. Install

Open a terminal in the folder you downloaded, and stay in that folder for every command in this guide.

### Windows

Windows needs two different things, and one is not the other: **Zadig** tells Windows which driver to use for the
stick, and **libusb** is the library the driver itself loads. Do both.

1. Plug in the stick.
2. Download **Zadig** from <https://zadig.akeo.ie/> and run it.
3. In Zadig, open the drop-down list, choose the device whose USB ID is `048d:9308`.
4. Set the driver on the right to **WinUSB** and click **Install Driver**. Wait for "The driver was installed
   successfully".
5. Unplug the stick and plug it in again. You do this only once.
6. Get **libusb** from <https://libusb.info> (Downloads → Windows), and unzip it. You need the file `libusb-1.0.dll`
   from the 64-bit folder.
7. Put that file where the driver looks for it. The simplest way is to point the driver at it:

   ```powershell
   setx IT9308_LIBUSB "C:\path\to\libusb-1.0.dll"
   ```

   (Copying `libusb-1.0.dll` next to `python.exe` works too, and needs no variable.) Close the terminal and open a new
   one, because `setx` only affects terminals opened afterwards.
8. Run `python -m it9308 list` (section 4). You should see the stick, or `no 048d devices found` if it is not plugged
   in. Either answer means libusb was found; the error in section 8 means it was not.

### Linux

1. Copy the rule that lets your user reach the stick without being root:

   ```bash
   sudo cp udev/99-it9308.rules /etc/udev/rules.d/
   sudo udevadm control --reload
   sudo udevadm trigger
   ```

2. Unplug the stick and plug it in again.
3. If you are connected over SSH (no desktop session logged in), add your user to the `plugdev` group with
   `sudo usermod -aG plugdev $USER`, then log out and back in.

### macOS

1. Install libusb with Homebrew: `brew install libusb`.
2. On an Apple Silicon Mac, use an arm64 build of Python. A Python running under Rosetta will report that the USB backend
   is missing.

---

## 4. First run

Two commands tell you whether everything is in place. Run them in this order. (This driver has no simulated mode; the
first command needs no hardware at all.)

1. **Check the version.**

   ```bash
   python -m it9308 --version
   ```

   A good answer is one line:

   ```text
   it9308 0.3.0 (it9308-pbcnx)
   ```

2. **Find the stick.**

   ```bash
   python -m it9308 list
   ```

   A good answer names the stick and its address, for example:

   ```text
   048d:9308  bus 1 addr 31  supported
   ```

   If it says `no 048d devices found`, the stick is not plugged in, or Windows has not been told to use WinUSB for it
   (section 3). If it says the libusb backend is unavailable, do step 6 of section 3.

---

## 5. Watch or record

The stick tunes to one channel at a time. A frequency is given in kHz, so `497143` means 497.143 MHz.

1. **Tune and see if there is a signal.** `play` prints the lock and the packet count while it runs:

   ```bash
   python -m it9308 play --freq 497143 --seconds 5
   ```

   A good answer includes a locked status and a growing packet count:

   ```text
   ts packets 14799  lock True  strength 74  quality n/a  snr 23.46
   ```

   `lock False` means the channel is empty or the signal is too weak where you are. Try another frequency, move the
   antenna, or use `python -m it9308 scan --start 473143 --stop 527143` to look across the band.

2. **Record 30 seconds to a file.**

   ```bash
   python -m it9308 play --freq 497143 --seconds 30 --out capture.ts
   ```

   You get `capture.ts` in the current folder. Any player that reads MPEG-TS can open it. Press `Ctrl-C` to stop early.

3. **Watch live in VLC, over UDP.** In one terminal:

   ```bash
   python -m it9308 play --freq 497143 --udp 127.0.0.1:1234
   ```

   And in a second terminal, or in VLC's *Open Network Stream* box:

   ```bash
   vlc udp://@:1234
   ```

   The picture appears in VLC within a few seconds. Stop the first command with `Ctrl-C` and VLC stops on its own.

---

## 6. TV signal info

Broadcasters describe how their signal is built. The stick reads that description from the air, and `tmcc` prints it:

```bash
python -m it9308 tmcc --freq 497143
```

You get one line that starts like this (the values depend on the channel):

```text
tmcc mode 8K  guard 1/4  partial 1  ewbs 0  L0:QPSK 3/4 I4 1seg  L1:QPSK 3/4 I2 12seg  L2:-
```

- **mode** — how many carriers the channel uses. It is a property of the broadcast, not something you choose.
- **guard** — the spacing between carriers, shown as a fraction such as `1/8`. Larger guards survive echoes better,
  which matters in cities and in moving vehicles.
- **partial** — `1` means the channel also carries a small low-resolution service for phones, alongside the main
  program.
- **ewbs** — `1` means the multiplex announces an emergency-warning service.
- **L0 / L1 / L2** — the layers of the channel. Each layer has a modulation (how densely the signal is packed), a
  number of segments (how much of the channel it occupies), a code rate (how much error correction it carries) and an
  interleave depth.

If it says `tmcc not decoded yet ...`, the stick has a signal but has not read the description yet — tune again and give
it a second or two. The driver prints a channel only when two readings agree, because a half-read block can look like a
real one.

---

## 7. Android

The same driver exists for Android as a small Java library, so an app can list, tune and play without writing the USB
protocol itself. The app opens the stick, hands it the firmware image (section 2), tunes a frequency, and receives the
video stream as it arrives. `README.md` shows the four lines of Java an app needs. Nothing in this folder has to be
built to use the command line on a computer.

---

## 8. When something goes wrong

Each of these is the exact first line the driver prints, what it means, and what to do about it.

| What you see | What it means | What to do |
|---|---|---|
| `error: libusb backend unavailable` | Your computer has no USB library the driver can use. | Windows: get `libusb-1.0.dll` from <https://libusb.info> and set `IT9308_LIBUSB` to its path (section 3, steps 6-7). macOS: `brew install libusb`. Linux: install `libusb-1.0-0`. |
| `no 048d devices found` | The stick is not visible to the driver. | Plug it in. On Windows, bind it to WinUSB with Zadig first. On Linux, install the udev rule and replug. |
| `no IT9308 device (048d:9308) found; bind it to WinUSB first` | A command that needs the stick did not find one. | Same as above; the hint on Windows is Zadig (section 3). |
| `error: IT9308 firmware not found at <path>. The image is vendor material and is not distributed ...` | The firmware file is missing, or the driver looked in the wrong place. | Section 2: the three places it looks, in order. |
| `error: firmware at <path> is not the expected 6,498-byte image` | The file exists but it is not the image this stick needs. | Check that you copied the file from the vendor app for this stick, and that the copy is complete. |
| `cannot claim the device (busy): ...` | Another program is using the stick, or your user is not allowed to. | Close other TV programs. On Linux, install the udev rule (section 3) and replug; over SSH add your user to `plugdev`. |
| `no signal: the scan never locked this channel and no stream arrived` | The channel is empty where you are, and the driver did not touch the stick. | Try another frequency, move the antenna, or scan the band. |
| `tmcc not decoded yet ...` | The stick has a signal but has not read the transmission parameters. | Tune again and wait a second or two; check the antenna if it persists. |

If the stick stops answering, `python -m it9308 recover` clears a stuck bridge in software; if it says the chip came
back blank it reloads the firmware. A stick that disappears from the computer is a replug — that is the platform, not
the driver.

---

## 9. Getting help

Open an issue at <https://github.com/PBCNX/it9308/issues>. Please say which command you ran, what it printed, and whether
`python -m it9308 list` finds the stick. That last answer tells us whether the problem is the stick or the computer.
