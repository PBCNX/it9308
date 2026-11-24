package com.pbcnx.drivers.it9308.android;

import android.content.Context;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbManager;
import android.util.Log;

import java.util.ArrayList;
import java.util.List;

import com.pbcnx.tuner.ScanListener;
import com.pbcnx.tuner.Tmcc;
import com.pbcnx.tuner.TsReader;
import com.pbcnx.tuner.Tuner;
import com.pbcnx.tuner.TunerException;
import com.pbcnx.tuner.TunerProvider;
import com.pbcnx.tuner.TunerStatus;
import com.pbcnx.drivers.it9308.It9308Device;
import com.pbcnx.drivers.it9308.SignalStatus;

/**
 * The IT9308 through the published door ({@code com.pbcnx.tuner:contract:1.0.0}).
 *
 * <p>Four construction arguments, exactly as the contract says: {@code (Context, UsbDevice, byte[] firmware,
 * TsReader.Listener)}. The firmware image is an argument because a package does not ship vendor firmware; a
 * missing image is answered by {@link TunerException} from {@code open()}, never by a guessed upload.</p>
 *
 * <p>This class sits beside {@link It9308Provider} in the same jar on purpose: the host app still uses a host-side SPI
 * while the door migration is one-driver-at-a-time, and both providers drive the same core.</p>
 */
public final class It9308DoorProvider implements TunerProvider {

    /**
     * True: a recovery on this part means a bridge reboot, which re-enumerates the USB device. A host should
     * suspend, let the attach arrive, then resume(newDevice) - the grant dialog belongs there, not inside
     * recover().
     */
    public static boolean recoveryReenumerates() {
        return true;
    }

    @Override
    public Tuner open(Context context, UsbDevice device, byte[] firmware, TsReader.Listener listener) {
        return new It9308DoorTuner(context, device, firmware, listener);
    }

    /** The door's Tuner: open -> tune(n)* -> close, one open per USB instance. */
    private static final class It9308DoorTuner implements Tuner {

        private static final String TAG = "IT9308DOOR";
        private static final long LOCK_WAIT_MS = 1500L;

        private final Context context;
        private UsbDevice device;
        private final byte[] firmware;
        private final TsReader.Listener listener;

        private UsbManager manager;
        private AndroidTransport transport;
        private AndroidTsReader reader;
        private It9308Device tuner;
        private int lastFrequency = -1;

        It9308DoorTuner(Context context, UsbDevice device, byte[] firmware, TsReader.Listener listener) {
            this.context = context;
            this.device = device;
            this.firmware = firmware == null ? new byte[0] : firmware;
            this.listener = listener;
        }

        @Override
        public void open() throws TunerException {
            if (firmware.length == 0) {
                throw new TunerException("no firmware image (the door passes it as an argument)");
            }
            try {
                manager = (UsbManager) context.getSystemService(Context.USB_SERVICE);
                transport = AndroidTransport.open(manager, device);
                tuner = new It9308Device(transport);
                long began = System.currentTimeMillis();
                String version = tuner.bringUp(firmware);
                lastFrequency = tuner.tunedFrequencyKhz();   // bring-up already landed here
                Log.i(TAG, "open: bringUp " + version + " at " + lastFrequency + " kHz in "
                        + (System.currentTimeMillis() - began) + " ms");
                armReader();
            } catch (Throwable error) {
                // a failed bring-up must not leave the interface claimed: the next open() would see a busy
                // device and the host would read it as a wedged stick
                disarmReader();
                AndroidTransport opened = transport;
                transport = null;
                tuner = null;
                if (opened != null) {
                    try {
                        opened.close();
                    } catch (Throwable ignored) {
                        // already gone
                    }
                }
                throw new TunerException("open failed: " + error, error);
            }
        }

        private void armReader() {
            if (transport == null || listener == null) {
                return;
            }
            AndroidTsReader stream = new AndroidTsReader(transport,
                    (data, length) -> listener.onData(data, length));
            stream.start();
            reader = stream;
        }

        private void disarmReader() {
            AndroidTsReader stream = reader;
            reader = null;
            if (stream != null) {
                stream.stop();
            }
        }

        @Override
        public boolean tune(int frequencyKhz) {
            if (tuner == null) {
                return false;
            }
            try {
                // `lastFrequency` is the frequency the chip is on: bring-up sets it, and every change updates it
                long began = System.currentTimeMillis();
                if (frequencyKhz == lastFrequency) {
                    lastFrequency = frequencyKhz;
                    boolean locked = waitLock();          // already there: no replay at all
                    Log.i(TAG, "tune " + frequencyKhz + " (same) lock " + locked + " in "
                            + (System.currentTimeMillis() - began) + " ms");
                    return locked;
                }
                // Stop the stream around the retune. The tail is 252 bridge commands, and while TS flows the
                // demod answers each of them slowly: on the LEAP the same tail measured 1.99 s on a fresh open and
                // 15.1 s as the third tune of a run (the host app, 2026-11-23), i.e. the cost tracks the stream, not the
                // work. With the gate closed the same commands run at the fresh-open rate, and a channel change
                // has already broken continuity by definition.
                tuner.setStreaming(false);
                try {
                    tuner.fastRetune(frequencyKhz);       // a channel change is the tail, never a bring-up
                } finally {
                    // if the tail throws, a closed gate would leave a locked tuner delivering nothing -
                    // the exact "lock true, 0 KiB" shape we warn hosts about
                    tuner.setStreaming(true);
                }
                long replay = System.currentTimeMillis() - began;
                boolean locked = waitLock();
                Log.i(TAG, "tune " + frequencyKhz + " replay " + replay + " ms, lock " + locked + " total "
                        + (System.currentTimeMillis() - began) + " ms");
                lastFrequency = frequencyKhz;
                return locked;
            } catch (Throwable error) {
                Log.w(TAG, "tune: " + error);
                return false;
            }
        }

        /**
         * A channel change on the live handle. The reader is deliberately NOT stopped: this part tolerates a
         * retune while it runs (the bench app's ZAP measured 0.15 s that way), and stopping it can wait on
         * completions a busy multiplex has in flight - the host app measured 10-16 s on 479143 with the stop inside the
         * call (2026-11-22). The host drops its own queue around a tune; the stale batch is a demux concern,
         * not a reason to pay seconds here.
         */
        @Override
        public boolean zap(int frequencyKhz) {
            // tune() closes the stream gate around the tail; the reader keeps its queue and is not stopped
            long began = System.currentTimeMillis();
            boolean locked = tune(frequencyKhz);
            Log.i(TAG, "zap " + frequencyKhz + " lock " + locked + " in "
                    + (System.currentTimeMillis() - began) + " ms (reader kept running)");
            return locked;
        }

        private boolean waitLock() {
            long deadline = System.currentTimeMillis() + LOCK_WAIT_MS;
            while (System.currentTimeMillis() < deadline) {
                SignalStatus status = tuner.status();
                if (status != null && status.locked) {
                    return true;
                }
                sleep(40);
            }
            return false;
        }

        @Override
        public TunerStatus status() {
            SignalStatus status = tuner == null ? null : tuner.status();
            if (status == null || !status.known) {
                return new TunerStatus(false, -1, -1, -1);
            }
            int snr = Double.isNaN(status.snrDb) ? -1 : (int) Math.round(status.snrDb);
            return new TunerStatus(status.locked, status.strength, status.quality, snr);
        }

        @Override
        public Tmcc tmcc() {
            return convert();
        }

        @Override
        public Tmcc tmccSettled(int attempts, long delayMs) {
            Tmcc previous = null;
            for (int i = 0; i < Math.max(1, attempts); i++) {
                Tmcc current = convert();
                if (current != null && current.valid()) {
                    if (previous != null && same(previous, current)) {
                        return current;
                    }
                    previous = current;
                } else {
                    previous = null;
                }
                sleep(Math.max(1L, delayMs));
            }
            return null;
        }

        private Tmcc convert() {
            if (tuner == null) {
                return null;
            }
            try {
                com.pbcnx.drivers.it9308.Tmcc ours = tuner.tmcc();
                if (ours == null) {
                    return null;
                }
                int mode = mode(ours.mode);
                int guard = guard(ours.guard);
                List<Tmcc.Layer> layers = new ArrayList<>(3);
                addLayer(layers, ours.layerA);
                addLayer(layers, ours.layerB);
                addLayer(layers, ours.layerC);
                return new Tmcc(mode, guard, ours.partial, ours.ewbs ? 1 : 0,
                        layers.toArray(new Tmcc.Layer[0]));
            } catch (Throwable error) {
                Log.w(TAG, "tmcc: " + error);
                return null;
            }
        }

        private static void addLayer(List<Tmcc.Layer> layers,
                                     com.pbcnx.drivers.it9308.Tmcc.Layer layer) {
            if (layer == null || !layer.present || layer.segments <= 0) {
                return;
            }
            layers.add(new Tmcc.Layer(layer.segments, modulation(layer.modulation),
                    codeRate(layer.codeRate), interleaving(layer.interleave)));
        }

        private static boolean same(Tmcc a, Tmcc b) {
            if (a.mode != b.mode || a.guard != b.guard || a.partial != b.partial || a.ewbs != b.ewbs) {
                return false;
            }
            if (a.layers.length != b.layers.length) {
                return false;
            }
            for (int i = 0; i < a.layers.length; i++) {
                Tmcc.Layer x = a.layers[i];
                Tmcc.Layer y = b.layers[i];
                if (x.segments != y.segments || x.modulation != y.modulation
                        || x.codeRate != y.codeRate || x.interleaving != y.interleaving) {
                    return false;
                }
            }
            return true;
        }

        /**
         * The warm rung, answered honestly: this part has no in-place recovery. Its only reset is the bridge
         * reboot, and that re-enumerates the USB device - a NEW instance that needs a NEW permission grant, which
         * cannot be obtained inside this call (measured by the host app, 2026-11-22 23:14: openDevice failed - USB
         * permission?). Starting that reset here would make the host discover a detach from the kernel and ask
         * for a grant nobody expected.
         *
         * <p>So it answers {@code false} and leaves the ladder to the host: <b>may return false when the device
         * re-enumerated; the host must re-grant and call resume(newDevice)</b> - that is where the grant dialog
         * belongs. Use {@link It9308DoorProvider#recoveryReenumerates()} to know this before calling.</p>
         */
        @Override
        public boolean recover() {
            Log.i(TAG, "recover: no in-place rung on this part (its reset re-enumerates); "
                    + "host should suspend and let the attach rebuild");
            return false;
        }

        @Override
        public void suspend() {
            disarmReader();
            if (transport != null) {
                transport.close();
                transport = null;
            }
        }

        @Override
        public boolean resume(UsbDevice device) throws TunerException {
            if (device == null) {
                throw new TunerException("resume without a device");
            }
            this.device = device;
            try {
                if (manager == null) {
                    manager = (UsbManager) context.getSystemService(Context.USB_SERVICE);
                }
                transport = AndroidTransport.open(manager, device);
                tuner = new It9308Device(transport);
                tuner.bringUp(firmware);
                armReader();
                if (lastFrequency > 0) {
                    return tune(lastFrequency);
                }
                return true;
            } catch (Throwable error) {
                disarmReader();
                AndroidTransport opened = transport;
                transport = null;
                tuner = null;
                if (opened != null) {
                    try {
                        opened.close();
                    } catch (Throwable ignored) {
                        // already gone
                    }
                }
                throw new TunerException("resume failed: " + error, error);
            }
        }

        /** The verdict is the stream: each frequency is tuned, locked checked, then reported. */
        @Override
        public void scan(int startKhz, int stopKhz, int stepKhz, int seconds, ScanListener listener) {
            int total = 0;
            int found = 0;
            for (int frequency = startKhz; frequency <= stopKhz; frequency += Math.max(1, stepKhz)) {
                total++;
                boolean locked = tune(frequency);
                if (locked) {
                    found++;
                }
                if (listener != null) {
                    listener.onFrequency(frequency, locked, status());
                }
                sleep(Math.max(0L, seconds) * 1000L);
            }
            if (listener != null) {
                listener.onDone(found, total);
            }
        }

        @Override
        public void close() {
            disarmReader();
            if (transport != null) {
                transport.close();
                transport = null;
            }
            tuner = null;
        }

        private static int mode(String name) {
            if ("2K".equals(name)) return 0;
            if ("4K".equals(name)) return 1;
            if ("8K".equals(name)) return 2;
            return -1;
        }

        private static int guard(String name) {
            if ("1/32".equals(name)) return 0;
            if ("1/16".equals(name)) return 1;
            if ("1/8".equals(name)) return 2;
            if ("1/4".equals(name)) return 3;
            return -1;
        }

        private static int modulation(String name) {
            if ("DQPSK".equals(name)) return 0;
            if ("QPSK".equals(name)) return 1;
            if ("16QAM".equals(name)) return 2;
            if ("64QAM".equals(name)) return 3;
            return -1;
        }

        private static int codeRate(String name) {
            if ("1/2".equals(name)) return 0;
            if ("2/3".equals(name)) return 1;
            if ("3/4".equals(name)) return 2;
            if ("5/6".equals(name)) return 3;
            if ("7/8".equals(name)) return 4;
            return -1;
        }

        private static int interleaving(String name) {
            if ("I1".equals(name)) return 0;
            if ("I2".equals(name)) return 1;
            if ("I3".equals(name)) return 2;
            if ("I4".equals(name)) return 3;
            return -1;
        }

        private static void sleep(long millis) {
            try {
                Thread.sleep(millis);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
        }
    }
}
