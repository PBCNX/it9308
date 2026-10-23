package ph.pbcnx.it9308;

import java.util.List;

/**
 * Protocol core for IT930x dongles. {@link Transport} is the command endpoint
 * only; the transport stream is read by the app's own USB adapter.
 */
public final class It9308Device {
    /** Register that gates the TS path. */
    private static final int STREAM_GATE = 0xDA4C;

    private final Bridge bridge;
    private final Transport transport;
    private final List<Sequence.Step> steps;
    private double delayScale = 1.0;

    public It9308Device(Transport transport) {
        this.transport = transport;
        this.bridge = new Bridge(transport);
        this.steps = Sequence.load();
    }

    /** Test hook: 0 skips the captured delays, 1 replays them as captured. */
    public void setDelayScale(double delayScale) {
        this.delayScale = delayScale;
    }

    public long firmwareVersion() {
        return bridge.info();
    }

    /** Uploads a 6,498-byte scatter image and boots it. */
    public boolean loadFirmware(byte[] image) {
        if (image == null || image.length < 8) {
            return false;
        }
        bridge.exchange(Bridge.WRITE_REGISTER,
                new byte[]{1, 4, 0, 0, (byte) 0xF1, 0x03, 7}, 0);

        int offset = 0;
        while (offset + 4 <= image.length) {
            int segments = image[offset + 3] & 0xFF;
            int size = 4 + segments * 3;
            for (int index = 0; index < segments; index++) {
                size += image[offset + 6 + index * 3] & 0xFF;
            }
            if (offset + size > image.length) {
                return false;
            }
            byte[] block = new byte[size];
            System.arraycopy(image, offset, block, 0, size);
            bridge.exchange(Bridge.WRITE_FIRMWARE, block, 0);
            offset += size;
        }
        bridge.exchange(Bridge.BOOT, null, 0);
        return firmwareVersion() != 0;
    }

    /** Firmware check, then the captured bring-up (init + default tune). */
    public String bringUp(byte[] image) {
        long version = firmwareVersion();
        if (version == 0) {
            if (!loadFirmware(image)) {
                throw new IllegalStateException("firmware image missing or invalid");
            }
            version = firmwareVersion();
        }
        Sequence.replay(transport, steps, 2000, delayScale);
        return String.format("0x%08x", version);
    }

    /**
     * Replays the captured bring-up with the frequency field replaced.
     *
     * @param frequencyKhz centre frequency in kHz, e.g. 599143
     */
    public boolean tune(int frequencyKhz) {
        Sequence.replay(transport, Sequence.patched(steps, frequencyKhz), 2000, delayScale);
        return true;
    }

    /** RF lock and metrics are not decoded yet; returns unknown. */
    public SignalStatus status() {
        return SignalStatus.unknown();
    }

    /** Opens or closes the TS gate (register 0xDA4C). */
    public void setStreaming(boolean on) {
        bridge.writeRegister(STREAM_GATE, on ? 1 : 0);
    }

    public int stepCount() {
        return steps.size();
    }
}
