# Android transport for the IT9308 Java core

`AndroidTransport` implements the core's `Transport` interface over Android's
`UsbDeviceConnection`; `AndroidTsReader` reads the TS endpoint. The design is
transcribed from the vendor AIRialTV GO 1.0.6/2.0.4
`com.adth.endeavoursony.Bus` (see
[`../../docs/vendor-apks-2026-11-02.md`](../../docs/vendor-apks-2026-11-02.md)):

| | |
|---|---|
| interface | 0, claimed with `claimInterface(intf, true)` |
| command OUT | `0x02` bulk |
| command IN | `0x81` bulk |
| TS IN | `0x84` bulk |
| command timeout | **500 ms**, exact length |
| TS batch | **15,040 B** = 4 x 3,760 = 80 x 188 |

The vendor selects endpoints by index; this adapter selects by address, which
is the stable part. It is compile-checked but **not yet run on a phone**.

## Use in an app

1. Copy `src/main/java/ph/pbcnx/it9308/android/` into the app, or add this
   directory as an Android source set. Add `src/main/res/xml/device_filter.xml`.
2. Declare USB host support and the device filter on the activity:

   ```xml
   <uses-feature android:name="android.hardware.usb.host" />
   <activity ...>
       <intent-filter>
           <action android:name="android.hardware.usb.action.USB_DEVICE_ATTACHED" />
       </intent-filter>
       <meta-data android:name="android.hardware.usb.action.USB_DEVICE_ATTACHED"
                  android:resource="@xml/device_filter" />
   </activity>
   ```

3. Ask for permission (`UsbManager.requestPermission` with a `PendingIntent`)
   before opening. `AndroidTransport.open` needs permission; it returns
   `IOException` for "no device", "permission", "claim failed" and "missing
   endpoint".
4. Drive the core, then start the reader:

   ```java
   AndroidTransport transport = AndroidTransport.open(usbManager, device);
   It9308Device tuner = new It9308Device(transport);
   tuner.bringUp(firmwareBytes);      // 6,498 B, supplied by the app
   tuner.tune(599143);
   tuner.setStreaming(true);
   AndroidTsReader reader = new AndroidTsReader(transport,
           (data, length) -> demux.write(data, 0, length));
   reader.start();
   ```

5. On detach or pause: `reader.stop(); transport.close();`.

## Ordering matters

Start the reader **after** `bringUp()`, `tune(khz)` and `setStreaming(true)`.
A tune resets the TS endpoint; ten queued requests armed before it never
complete (the blocking fallback hides this because it re-reads in a loop).
Before a retune, stop the reader and start it again afterwards:

```java
reader.stop();
tuner.tune(khz);          // full tune only; retune() was a measured no-op
tuner.setStreaming(true);
reader.restart();        // stop() + start(), re-queues the requests
```

The signal status read should be polled after the tune settles (a few hundred
milliseconds); a status read immediately after `tune()` is expected to say
"not locked".

## Firmware

The 6,498-byte bridge image is vendor material and is **not** in this repo.
Place it in the app's private storage or assets and pass the bytes to
`It9308Device.loadFirmware` / `bringUp`. The image, and the `0x22` version check,
are the same as the Python path; the SHA-256 is
`e4e94633b4ac47c6bba5ab90eedd4a7e5ffa2ce7e342884c91749c7464704a70`.

## Limits

- Ten queued `UsbRequest`s of 15,040 bytes are the default (the vendor's
  pipeline); if queue setup fails it falls back to the blocking read. The
  listener buffer is reused either way.
- A completion's transfer length is `ByteBuffer.position()` on API 34
  (confirmed: 0 / 512 / 15040). `pos=0` is an empty transfer, not an error.
- A 5-minute TV5 soak on the queued path: 1,441,407 packets, 0 bad sync,
  5 short reads, 58 continuity errors (~0.2/s), pipe drops 0.
- `Listener.onData` receives a **reused** buffer; copy or consume before
  returning.
- TS alignment (`0x47` every 188 bytes) is the app's job, as before. The vendor
  `Datagram` hands 15,040-byte slabs to its own demuxer the same way.
- `status()` reads lock and SNR from `0x64` (reg 0x10 bit 0; SNR 0x13/0x14).
  Poll at **1 Hz while streaming**; 60/60 reads left the TS untouched. The
  earlier "read while TS flows stops the stream" was the old page/bank shape.
  RF is a relative index (`0x64` reg `0x11`/`0x12`; 599/GMA 51-74, empty 0-12);
  `strength = min(100, index)`, 9175-style raw clamp, not dBm.

## Compile check

```bash
javac -source 8 -target 8 -cp "$ANDROID_SDK/platforms/android-34/android.jar" \
    -d out $(find ../src/main/java src/main/java -name '*.java')
```

On this bench the JDK is `D:\Profile\Tools\jdk-17` and the SDK is
`D:\Profile\Tools\android-sdk`; the command is run from `java/android`.

## Licence

MIT, same as the rest of the repo. No vendor code is copied: the endpoints,
timeouts and batch size are protocol facts, and the adapter is written against
the Android USB API.
