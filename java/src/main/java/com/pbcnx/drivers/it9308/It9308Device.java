// Copyright (c) 2026 The IT9308 Open Driver Authors
// MIT license; see LICENSE. Visible attribution marker: it9308-pbcnx
package com.pbcnx.drivers.it9308;

import java.util.List;

/**
 * Protocol core for IT930x dongles. {@link Transport} is the command endpoint
 * only; the transport stream is read by the app's own USB adapter.
 */
public final class It9308Device {
    /** Visible provenance marker: searchable attribution, not telemetry. */
    public static final String PROVENANCE = "it9308-pbcnx";
    /** Register that gates the TS path. */
    private static final int STREAM_GATE = 0xDA4C;
    /** First step of the fast-retune tail (measured: 750 works, 755 does not). */
    public static final int FAST_RETUNE_START = 700;

    /** Delay scale that made the tail switch in ~0.21 s (5% of the captured delays). */
    public static final double FAST_RETUNE_DELAY_SCALE = 0.05;

    private static final int DEMOD_BUS = 2;
    private static final int DEMOD_ADDRESS = 0x66;
    private static final int DEMOD_ADDRESS_PAGE0 = 0x64;
    private static final int DEMOD_CHIP_ID = 0xFD;
    private static final int STATUS_ADDRESS = 0x64;
    private static final int STATUS_REG = 0x10;
    private static final int SNR_REG_HI = 0x13;
    private static final int SNR_REG_LO = 0x14;

    private final Bridge bridge;
    private final Transport transport;
    private final List<Sequence.Step> steps;
    private double delayScale = 1.0;
    /** The frequency the chip is currently tuned to, or -1 when unknown. */
    private volatile int tunedFrequencyKhz = -1;

    public It9308Device(Transport transport) {
        this.transport = transport;
        this.bridge = new Bridge(transport);
        this.steps = Sequence.load();
    }

    /** Test hook: 0 skips the captured delays, 1 replays them as captured. */
    /**
     * State-3 recovery, first half: the vendor's {@code IT9300_reboot}, sent fire-and-forget.
     *
     * <p>Write the boot command, do not read the reply (it stalls on a wedged chip), then close this
     * transport, reopen the device, and verify there - call {@link #bringUp(byte[])} on the new session
     * (it uploads only if the chip came back blank) and confirm the demod chip id. The host owns the
     * close/reopen because it owns the USB handle.
     */
    public void rebootBlind() {
        bridge.bootBlind(1000);
    }

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
        // the captured bring-up ends tuned on the captured frequency; a host that asks for it again should
        // not pay a second 952-step replay (door first tune, measured 4.2 s of pure waste, 2026-11-22)
        tunedFrequencyKhz = capturedFrequencyKhz();
        return String.format("0x%08x", version);
    }

    /**
     * Replays the captured bring-up with the frequency field replaced.
     *
     * @param frequencyKhz centre frequency in kHz, e.g. 599143
     */
    public boolean tune(int frequencyKhz) {
        Sequence.replay(transport, Sequence.patched(steps, frequencyKhz), 2000, delayScale);
        tunedFrequencyKhz = frequencyKhz;
        return true;
    }

    /**
     * Fast channel change: replay only the tail of the sequence, with scaled delays.
     *
     * <p>Measured on hardware 2026-11-20: the full replay takes 4.4-4.6 s; from step 700 with the captured
     * delays 1.08 s; the same tail at 5% delay takes <b>0.21 s</b>, and the switch is verified by TMCC
     * (497 QPSK 3/4 -> 479 QPSK 7/8 + 16QAM). Starting after step 755 does <em>not</em> switch, so
     * {@link #FAST_RETUNE_START} carries margin over the measured boundary (750 works).
     *
     * @param frequencyKhz centre frequency in kHz
     * @param delayScale   1.0 = as captured, 0.05 = the measured fast default
     */
    public boolean fastRetune(int frequencyKhz, double delayScale) {
        java.util.List<Sequence.Step> patched = Sequence.patched(steps, frequencyKhz);
        Sequence.replay(transport, patched.subList(FAST_RETUNE_START, patched.size()), 2000, delayScale);
        tunedFrequencyKhz = frequencyKhz;
        return true;
    }

    /** Fast channel change with the measured 5% delay scale. */
    /** The frequency the chip is currently tuned to, or -1 when unknown. */
    public int tunedFrequencyKhz() {
        return tunedFrequencyKhz;
    }

    /** The frequency of the captured bring-up's default tune (599143 kHz on this part). */
    public static int capturedFrequencyKhz() {
        byte[] frequency = Sequence.CAPTURED_FREQUENCY;
        return ((frequency[0] & 0xFF) << 16) | ((frequency[1] & 0xFF) << 8) | (frequency[2] & 0xFF);
    }

    /** Length of the captured sequence, for callers that want to reason about the tail size. */
    public static int sequenceLength() {
        return Sequence.load().size();
    }

    public boolean fastRetune(int frequencyKhz) {
        return fastRetune(frequencyKhz, FAST_RETUNE_DELAY_SCALE);
    }

    /**
     * @deprecated the 17-step tune block was measured as a no-op: retuning to
     * an empty 503.143 still delivered GMA packets. Use {@link #tune(int)},
     * which replays the full sequence; this alias is kept for callers.
     */
    @Deprecated
    public boolean retune(int frequencyKhz) {
        return tune(frequencyKhz);
    }

    /**
     * Reads lock, SNR and a relative RF index from the Sony demod at 0x64.
     *
     * Measured on the phone, GMA 479.143 vs empty 503.143:
     * lock = reg 0x10, bit 0x01; SNR = reg 0x13 (high) / 0x14 (low),
     * {@code 10*log10(raw) - 9.031} dB; RF = reg 0x11 (high) / 0x12 (low),
     * vendor index {@code ((b1 >> 5) | (b0 << 3))}. The RF index is relative
     * (GMA 66, empty 7), not calibrated dBm. Read once between tune() and
     * setStreaming(); a read while TS flows stops the stream.
     */
    public SignalStatus readStatus() {
        try {
            byte[] lock = readDemodAt(STATUS_ADDRESS, STATUS_REG, 1);
            if (lock == null || lock.length < 1) {
                return SignalStatus.unknown();
            }
            boolean locked = (lock[0] & 0x01) != 0;

            byte[] high = readDemodAt(STATUS_ADDRESS, SNR_REG_HI, 1);
            byte[] low = readDemodAt(STATUS_ADDRESS, SNR_REG_LO, 1);
            int rawSnr = -1;
            double snrDb = Double.NaN;
            if (high != null && high.length >= 1 && low != null && low.length >= 1) {
                rawSnr = ((high[0] & 0xFF) << 8) | (low[0] & 0xFF);
                if (rawSnr > 0) {
                    snrDb = 10.0 * Math.log10(rawSnr) - 9.031;
                }
            }

            byte[] rfHigh = readDemodAt(STATUS_ADDRESS, 0x11, 1);
            byte[] rfLow = readDemodAt(STATUS_ADDRESS, 0x12, 1);
            int rfIndex = -1;
            if (rfHigh != null && rfHigh.length >= 1 && rfLow != null && rfLow.length >= 1) {
                rfIndex = ((rfLow[0] & 0xFF) >> 5) | ((rfHigh[0] & 0xFF) << 3);
            }

            return SignalStatus.of(locked, rfIndex, rawSnr, snrDb);
        } catch (RuntimeException error) {
            return SignalStatus.unknown();
        }
    }

    /**
     * The channel's transmission parameters (TMCC), read after lock: mode, guard, partial reception,
     * the EWBS activation bit and the layer fields the bench measured. Fields it did not measure are
     * {@code "?"}; {@link Tmcc#raw} carries every byte read, so a host can show what was seen.
     */
    public Tmcc tmcc() {
        return Tmcc.decode(readRegisterByte(0x24), readRegisterByte(0x32), readRegisterByte(0x33),
                readRegisterByte(0x34), readRegisterByte(0x35), readRegisterByte(0x36),
                readRegisterByte(0x37));
    }

    private Integer readRegisterByte(int register) {
        try {
            byte[] data = readDemodAt(STATUS_ADDRESS, register, 1);
            return data != null && data.length >= 1 ? (int) (data[0] & 0xFF) : null;
        } catch (RuntimeException error) {
            return null;
        }
    }

    /**
     * One raw status read for hardware debugging: the exact bytes of
     * 0x64 reg 0x10, 0x13, 0x14, or "null" when a read was NAKed.
     */
    public String readStatusRaw() {
        StringBuilder out = new StringBuilder();
        try {
            byte[] lock = readDemodAt(STATUS_ADDRESS, STATUS_REG, 1);
            byte[] high = readDemodAt(STATUS_ADDRESS, SNR_REG_HI, 1);
            byte[] low = readDemodAt(STATUS_ADDRESS, SNR_REG_LO, 1);
            byte[] rfHigh = readDemodAt(STATUS_ADDRESS, 0x11, 1);
            byte[] rfLow = readDemodAt(STATUS_ADDRESS, 0x12, 1);
            out.append("lock=").append(hex(lock))
                    .append(" snr=").append(hex(high)).append(hex(low))
                    .append(" rf=").append(hex(rfHigh)).append(hex(rfLow));
        } catch (RuntimeException error) {
            out.append("error=").append(error);
        }
        return out.toString();
    }

    private static String hex(byte[] data) {
        if (data == null) {
            return "null";
        }
        StringBuilder out = new StringBuilder();
        for (byte value : data) {
            out.append(String.format(java.util.Locale.US, "%02x", value & 0xFF));
        }
        return out.toString();
    }

    private static void sleep(int milliseconds) {
        try {
            Thread.sleep(milliseconds);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    /**
     * Pre-gate register sweep for hardware debugging.
     *
     * Call once after tune() and before setStreaming(true): reads page 0..3,
     * reg 0x00..0x3f on both demod addresses 0x66 and 0x64, one byte each, and
     * returns a compact table ("66 p0:...."). Compare a known signal with an
     * empty mux to find the register that actually changes.
     */
    public String statusSweep() {
        StringBuilder out = new StringBuilder();
        for (int address : new int[]{0x66, 0x64}) {
            out.append(String.format(java.util.Locale.US, "%02x:", address));
            for (int register = 0; register < 0x40; register++) {
                byte[] value = readDemodAt(address, register, 1);
                if (value == null || value.length < 1) {
                    out.append("--");
                } else {
                    out.append(String.format(java.util.Locale.US, "%02x", value[0] & 0xFF));
                }
            }
            out.append('\n');
        }
        return out.toString();
    }

    private byte[] readDemodAt(int address, int register, int length) {
        bridge.writeI2c(DEMOD_BUS, address, new byte[]{(byte) register});
        return bridge.readI2c(DEMOD_BUS, address, length);
    }

    private byte[] readDemod(int page, int register, int length) {
        int address = page == 0 ? DEMOD_ADDRESS_PAGE0 : DEMOD_ADDRESS;
        return readDemodAt(address, register, length);
    }

    private void writeDemod(int page, int register, int... values) {
        int address = page == 0 ? DEMOD_ADDRESS_PAGE0 : DEMOD_ADDRESS;
        byte[] payload = new byte[1 + values.length];
        payload[0] = (byte) register;
        for (int i = 0; i < values.length; i++) {
            payload[1 + i] = (byte) values[i];
        }
        bridge.writeI2c(DEMOD_BUS, address, payload);
    }

    /** RF lock and metrics, read from the Sony demod. */
    public SignalStatus status() {
        return readStatus();
    }

    /**
     * Sony demod chip ID: register 0xFD on bus 2 / 0x66.
     *
     * Measured 0x6A on the 048d:9308 (the vendor's sony_tunerdemod_ChipID
     * recognises 0x62/0x6A). Call after {@link #bringUp}; the captured
     * sequence's step 55 is the same read.
     */
    public int chipId() {
        bridge.writeI2c(DEMOD_BUS, DEMOD_ADDRESS, new byte[]{(byte) DEMOD_CHIP_ID});
        byte[] value = bridge.readI2c(DEMOD_BUS, DEMOD_ADDRESS, 1);
        if (value == null || value.length < 1) {
            throw new IllegalStateException("demod chip ID read failed");
        }
        return value[0] & 0xFF;
    }

    /** Opens or closes the TS gate (register 0xDA4C). */
    public void setStreaming(boolean on) {
        bridge.writeRegister(STREAM_GATE, on ? 1 : 0);
    }

    public int stepCount() {
        return steps.size();
    }
}
