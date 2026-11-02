# Android transport for the IT9308 Java core

`AndroidTransport` implements `Transport` over `UsbDeviceConnection`;
`AndroidTsReader` reads endpoint `0x84`. Verified in OpenDTV-MOD on a phone.

| | |
|---|---|
| interface | 0, claimed with `claimInterface(intf, true)` |
| command OUT / IN | `0x02` / `0x81`, bulk, 500 ms, exact length |
| TS IN | `0x84`, 15,040 B = 4 x 3,760 = 80 x 188 |
| endpoints | selected by address (the vendor selects by index) |

## Use

1. Add `src/main/java/ph/pbcnx/it9308/android/` and
   `src/main/res/xml/device_filter.xml` to the app.
2. Declare USB host and the device filter on the activity.
3. Request permission, then open:

```java
AndroidTransport transport = AndroidTransport.open(usbManager, device);
It9308Device tuner = new It9308Device(transport);
tuner.bringUp(firmwareBytes);      // 6,498 B vendor image
tuner.tune(599143);
tuner.setStreaming(true);
AndroidTsReader reader = new AndroidTsReader(transport,
        (data, length) -> demux.write(data, 0, length));
reader.start();
```

4. On pause/detach: `reader.stop(); transport.close();`.

## Ordering

Start the reader **after** bring-up, tune and `setStreaming(true)`. A tune resets
the TS endpoint, so requests armed before it never complete. Before a retune:

```java
reader.stop();
tuner.tune(khz);            // full tune only
tuner.setStreaming(true);
reader.restart();
```

Status after the tune settles (a few hundred ms); immediately after `tune()` it
can still say “not locked”.

## Limits

- Ten queued `UsbRequest`s of 15,040 B (vendor shape); blocking fallback.
- Completion length is `ByteBuffer.position()` (0 / 512 / 15040). `pos=0` is an
  empty transfer, not an error.
- `Listener.onData` gets a **reused** buffer; copy/consume before returning.
- TS alignment is the app’s job.
- Status can be polled at 1 Hz while streaming; RF is relative, not dBm.
- 5-minute TV5 queued soak: 1,441,407 packets, 0 bad sync.

## Firmware

Vendor 6,498-byte image, not in the public repo; supply it from app assets or
private storage. SHA-256:
`e4e94633b4ac47c6bba5ab90eedd4a7e5ffa2ce7e342884c91749c7464704a70`.

## Compile

```bash
cd java/android
javac -source 8 -target 8 \
  -cp "$ANDROID_HOME/platforms/android-34/android.jar" \
  -d out $(find ../src/main/java src/main/java -name '*.java')
```

## Licence

MIT, same as the repo. No vendor code copied; the adapter is written against
the Android USB API.
