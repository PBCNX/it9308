# it9308 — Java core (Android)

Pure-JVM implementation of the IT930x protocol. No Android dependency; the app
supplies a `Transport` for the **command endpoint only** and owns the TS reader.

## API

```java
It9308Device device = new It9308Device(transport);   // loads sequence.bin
String version = device.bringUp(firmwareImage);      // "0x01000000", uploads if blank
boolean ok     = device.tune(599143);                // frequency in kHz
SignalStatus s = device.status();                    // unknown() for now
device.setStreaming(true);                           // register 0xDA4C
device.setDelayScale(0);                             // tests only
```

`tune(khz)` replays the captured bring-up with the frequency field replaced
(3-byte big-endian kHz at the captured tune frames). The capture is two passes;
both are replayed, as on hardware. `status()` returns `SignalStatus.unknown()`
because RF lock/metrics are not decoded yet.

## Test

```bash
javac -d out $(find src -name '*.java')
java -cp "out:src/main/resources" ph.pbcnx.it9308.SelfTest
```

Expected: `it9308 java self-test: OK (952 steps)`.

The fake transport answers like the bridge and records writes; the test checks
the captured 599.143 MHz frames and the patched 473.143 MHz frames against the
Python driver's expected bytes.
