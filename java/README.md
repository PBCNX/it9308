# it9308 — Java core

Pure-JVM port of the IT930x protocol. No Android dependency; the app supplies a
`Transport` for the command endpoint and owns the TS reader.

## API

```java
It9308Device device = new It9308Device(transport);   // loads sequence.bin
String version = device.bringUp(firmwareImage);      // uploads if blank
int chip       = device.chipId();                    // 0x6A on this stick
boolean ok     = device.tune(599143);                // kHz
SignalStatus s = device.status();                    // lock, SNR, RF
String raw     = device.readStatusRaw();             // debug line
device.setStreaming(true);                           // 0xDA4C
```

`tune(khz)` replays the 952 steps with the 3-byte kHz field replaced and each
frame’s checksum recomputed. Full replay only; `retune()` is a proven no-op and
delegates to `tune()`.

`status()` reads `0x64`: lock `0x10` bit 0; SNR `0x13`/`0x14`
(`10*log10(raw)-9.031`); RF `0x11`/`0x12` relative index
(`strength = min(100,index)`, **not dBm**). Poll at 1 Hz while streaming; 60/60
reads leave the TS untouched.

## Test

```bash
cd java
javac -d out $(find src -name '*.java')
java -cp "out:src/main/resources" ph.pbcnx.it9308.SelfTest
```

Expected: `it9308 java self-test: OK (952 steps)`.

## Android

[`android/`](android/README.md) has `AndroidTransport` and `AndroidTsReader`.
The clean-room path is verified in OpenDTV-MOD; no Android app is shipped here.

## Licence

MIT. No vendor code; endpoints/timeouts are protocol facts. Firmware is vendor
material and is not in this repo.
