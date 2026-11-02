# it9308 — Java core (Android)

Pure-JVM implementation of the IT930x protocol. No Android dependency; the app
supplies a `Transport` for the **command endpoint only** and owns the TS reader.
`java/android/` now supplies that transport (compile-checked, not yet run on a
phone).

## API

```java
It9308Device device = new It9308Device(transport);   // loads sequence.bin
String version = device.bringUp(firmwareImage);      // "0x01000000", uploads if blank
int chip       = device.chipId();                    // Sony demod 0xFD -> 0x6A
boolean ok     = device.tune(599143);                // frequency in kHz
SignalStatus s = device.status();                    // lock + raw SNR
String raw     = device.readStatusRaw();             // lock/snr bytes for logs
String sweep   = device.statusSweep();               // pre-gate page/reg dump
device.setStreaming(true);                           // register 0xDA4C
device.setDelayScale(0);                             // tests only
```

`chipId()` writes `0xFD` to bus 2 / `0x66` and reads one byte; it is the same
read as step 55 of the capture and returns `0x6A` on the 048d:9308.
`Bridge.readI2c` / `writeI2c` expose the generic I2C verbs for other diagnostics.

`tune(khz)` replays the captured bring-up with the frequency field replaced
(3-byte big-endian kHz at the captured tune frames). The capture is two passes;
both are replayed, as on hardware. `Sequence.patched` replaces the field and
**recomputes each frame's checksum**; 473.143 is covered by the self-test.
`status()` reads lock and SNR from the demod at **0x64**: reg `0x10` bit 0,
SNR reg `0x13`/`0x14` -> `10*log10(raw) - 9.031` dB. Poll at **1 Hz while
streaming** (60/60 verified); the earlier "read stops TS" was the old page/bank
shape. RF is
relative: `0x64` reg `0x11`/`0x12` -> vendor index (599/GMA 51-74, empty 0-12), and
`strength = min(100, index)`; this is the **9175-style raw clamp**, not dBm.
`retune()` is deprecated: the
17-step block was a measured no-op (retune to an empty 503 still delivered GMA),
so it now delegates to the full `tune()`.

## Test

```bash
javac -d out $(find src -name '*.java')
java -cp "out:src/main/resources" ph.pbcnx.it9308.SelfTest
```

Expected: `it9308 java self-test: OK (952 steps)`.

The fake transport answers like the bridge and records writes; the test checks
the captured 599.143 MHz frames and the patched 473.143 MHz frames against the
Python driver's expected bytes.

## Android transport

[`android/`](android/README.md) contains `AndroidTransport` (implements
`Transport` over `UsbDeviceConnection`) and `AndroidTsReader` (the `0x84`
endpoint). It follows the vendor `Bus` shape measured from AIRialTV GO
1.0.6/2.0.4: interface 0, `0x02`/`0x81` command endpoints, 500 ms transfers,
15,040-byte TS batches. It is compiled against Android's `android.jar` but not
yet run on a device.
