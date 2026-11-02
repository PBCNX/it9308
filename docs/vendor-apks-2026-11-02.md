# Vendor APK teardown — 2026-11-02

Four APKs, read on the bench machine with the shared toolchain:

| file | package | version | code |
|---|---|---|---|
| `AIRialTV+GO_0.2.6_APKPure.apk` | `tv.tolka.airial` | 0.2.6 | 6 |
| `AIRialTV+GO_1.0.6_APKPure.apk` | `tv.tolka.airial` | 1.0.6 | 14 |
| `AIRialTV+GO_2.0.4_APKPure.apk` | `tv.tolka.airial` | 2.0.4 | 24 |
| `com.tolka.abstv-1.0.38-free.apk` | `com.tolka.abstv` | 1.0.38 | 109 |

Method: `zipfile` extraction; a scanner for the IT930x scatter-record chain
(magic `0x03`, flag at `+1`, segment count at `+3`, `4 + 3*N + sum(length)`
bytes per record, maximal chain kept); jadx 1.5.6 under JDK 17 for the Java;
PyGhidra 3.2.0 + Ghidra 12.1.4 for the Sony ELF. Scratch output is in
`it9308/.tmp/apks/` and is not tracked.

## Firmware images

Each image is embedded in a vendor `.so`. The maximal-chain scan found:

| app | library | offset | size | records | SHA-256 (first 16) | image |
|---|---|---|---|---|---|---|
| 0.2.6 | `libendeavour-sony-jni.so` | `0x67530` | 6,498 | 137 | `e4e94633b4ac47c6` | known Sony 1.10 |
| 1.0.6 | `libendeavour-sony-jni.so` | `0x7e530` | 6,498 | 137 | `e4e94633b4ac47c6` | known Sony 1.10 |
| 1.0.6 | `libendeavour-mn88553h_el-jni.so` | `0x5a630` | 7,013 | 147 | `294a1d673a9d6e8b` | known Panasonic 1.12 |
| tolka 1.0.38 | `libendeavour-sony-jni.so` | `0x65530` | 6,498 | 137 | `e4e94633b4ac47c6` | known Sony 1.10 |
| tolka 1.0.38 | `libendeavour-mn88553h_el-jni.so` | `0x44630` | 7,013 | 147 | `294a1d673a9d6e8b` | known Panasonic 1.12 |
| tolka 1.0.38 | `libendeavour-jni.so` | `0x4e528` | 5,761 | 121 | `e4964f31050f0ef9` | **new** |

Conclusions:

- **The 9308 Sony image did not change** across 2016-2020 builds and three
  different apps: 6,498 bytes, 137 records, SHA `e4e94633…`, the image this
  repo already ships privately. There is no newer 9308 bridge firmware in these
  APKs to test.
- **The 9309 Panasonic image did not change** either: 7,013 bytes / 147 records.
- The **5,761-byte image** is new and belongs to `libendeavour-jni.so`, the
  generic/FC8300 backend, not to the 9308. It is a different generic image from
  the 2,169-byte `dvb-usb-it9303-01.fw` the it9306 session extracted. Its
  product is not established; it is flagged for it9306/other IT930x, not used
  here.

## The 2.0.4 build is packed

The 2.0.4 native libraries have the same size as 1.0.6 (±8 bytes) but almost
every byte differs: comparing `libendeavour-sony-jni.so`, **530,393 of 532,496
bytes** differ, throughout the file. That is whole-payload encryption, not a
patch. The 6,498-byte image is not visible to a static scan, and the tune/loader
functions cannot be read without unpacking.

Its **Java is not packed**: both `classes.dex` files carry the normal `dex\n`
magic and decompile. The 2.0.4 transport and dispatcher below are read from that
Java, not from the native library.

## Vendor USB transport (Android)

From `com.adth.endeavoursony.Bus` (1.0.6 and 2.0.4 are the same shape):

- `Bus.initial(UsbManager, Context, xmlResId)` parses `<usb-device
  vendor-id=… product-id=…>` entries from an XML resource, finds the matching
  device, takes **interface 0**, and claims it with `claimInterface(intf, true)`.
- Endpoints are selected **by index**, not by address: interface 0 endpoint 0 is
  the command IN (`0x81`), endpoint 1 the command OUT (`0x02`), endpoint 2 the
  TS IN (`0x84`). (The older `com.adth.endeavoursony.e` class in OpenDTVmod
  selected by address; both end at the same three endpoints.)
- `busTx` / `busRx` are `bulkTransfer(endpoint, buf, len, 500)` — **500 ms**,
  and the transfer must return exactly `len` or the call fails with
  `50332160` / `50332672`.
- TS is read in **15,040-byte** units = 4 × 3,760 = 80 × 188, through **ten
  queued `UsbRequest`s**, re-queued as they complete; `requestWait(500L)` on
  SDK 26+, blocking `requestWait()` below. The synchronous fallback is
  `bulkTransfer(tsEndpoint, buf, 15040, 500)` and also requires the full 15,040.
- The JNI natives reach USB only through Java: `Endeavour.busTx/busRx` forward to
  `Bus`, and the TS buffer comes from `Bus.Datagram.getTs`. `JNI_OnLoad`
  registers the natives; the `testC2JCallback` declarations are part of that
  surface.

This is the recipe an android `Transport` for this repo needs. The vendor
callback itself is only needed to run the proprietary `.so`; the clean-room JVM
core needs the same USB calls, not the callback.

## Tune and init (from the Sony JNI)

- `Java_com_EW100_setIsdbtFrequency(khz, bandwidth)` stores `khz` at
  `ew100_tunerParam_ISDBT[0]` and maps bandwidth `5000/6000/7000/8000` Hz to
  code `5/6/7/8` (anything else → `1`), then calls the Sony tuner driver. So the
  frequency unit is kHz and the 6 MHz raster is the `6` case — consistent with
  the captured 24-bit kHz tune field. The PLL/NCO computation itself is in the
  Sony driver, but on this stick the 3-byte field is sufficient: patching it
  (with checksum) retuned to 473.143 (measured 2026-11-02).
- `sony_integ_isdbt_Tune` validates the band code (6/7/8), calls the common tune
  settings with a 100 ms gap, then waits for demod/TS lock.
- `Java_com_init` writes bridge `0xDA5A = 0x1F`, `0xD820 = 1`, sets the demod I2C
  address to **200 (`0x64 << 1`)**, and branches on a Sony chip revision/config
  value (`0x0D/0x10/0x13`; where that value comes from is not decoded).
- `sony_tunerdemod_ChipID` reads register `0xFD` and recognises variants
  `0x62`/`0x6A`. On this stick the captured replay's step 55 is that read and
  returns **`0x6A`**; a direct read after bring-up confirms it (2026-11-02).
- `_IT9300_loadFirmware` performs exactly the upload this repo implements:
  `0x24` BEGIN for a segment run, `0x29` per scatter record, `0x25` END, `0x23`
  BOOT, then `0x22` QUERYINFO; a zero version is error `0x3A`.

## PID dispatch is per app, not per PID

`com.adth.tv.TunerFactory` in AIRialTV 1.0.6 **and** 2.0.4:

| vendor | product | backend |
|---|---|---|
| 1165 (`0x048D`) | 37638 (`0x9306`) | `EndeavourSonyTunerUtility` |
| 1165 | 37640 (`0x9308`) | `EndeavourSonyTunerUtility` |
| 1165 | 37643 (`0x930B`) | `EndeavourMN88553HTunerUtility` |
| 1165 | 37641 (`0x9309`) | absent — falls to the default |

This does **not** contradict the it9306 brief: that brief is about the my|digital
TV app, whose 9306 open reaches `libEndeavour-jni` (IT9303 + MN88553H). Two
different vendor apps map the same PID to different backends. The PID is not the
model; the app's dispatcher is.

## fw_060 for the 9309: names only

`libendeavour-mn88553h_el-jni.so` in 1.0.6 and Tolka contains the strings
`fw_060`, `20160323`, `160304`, `160318`, `RgsHexPkg`, `PSEQ1_MN88553`,
`TMM3_TNCTL`, `.rgs` and `.hex` (1.0.6: 18 `fw_060`, 15 `160304`, 8 `160318`).
The **data is not there**:

- none of `pseq1-20160304.stad` (8,845 B), `tnctl-20150318.stad` (6,903 B),
  `chfile.csv` (21,314 B) or `MN88553.ini` (82,362 B) appears in either library;
- there is no Intel-HEX text (`^:10…` line starts: 0).

So the library names the device tree it expects
(`/sdcard/20160323_RgsHexPkg_forXtal372/fw_060/`) and does not carry a fallback.
That confirms the it9309 finding rather than solving it. 2.0.4's native code is
packed, so it cannot be checked statically.

## Not verified

1. The 2.0.4 native contents (packed; needs unpacking on a device).
2. The live chip revision branch (`0x0D/0x10/0x13`): the chip ID (`0xFD`) was
   read on 2026-11-02 and returns `0x6A`, but the revision register is not
   decoded.
3. Whether the 5,761-byte generic image boots, and on which product.
4. The tune register computation behind `sony_integ_isdbt_Tune`; the captured
   952-step sequence remains the register-level source.

## Evidence

- scan output + hashes: `it9308/.tmp/apks/firmware-scan.json`
- decompiled Java: `it9308/.tmp/apks/<app>/jadx|…`
- Sony decompilations: `it9308/.tmp/apks/airial-1.0.6/ghidra/` and `…/ghidra/tune/`
- this document is the durable record; the `.tmp` tree is disposable.
