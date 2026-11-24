package com.pbcnx.drivers.it9308;

import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.Map;

/**
 * Share of clean MPEG-TS packets over a sliding window.
 *
 * <p>The studio's shared definition: a packet is <b>not clean</b> when its
 * transport_error_indicator is set, or when its continuity counter breaks on its PID (a repeated
 * counter is not a break). Null packets (PID 0x1FFF) and adaptation-only packets are not counted at
 * all. Quality is {@code 100 * clean / total} over the last {@code window} seconds, and is
 * <b>unknown</b> ({@link Double#NaN}) until the first full window has been observed, and again
 * whenever the window is empty.
 *
 * <p>Plain class: no USB, no Android, no clock of its own. The caller owns the instance, feeds it
 * from wherever the TS bytes arrive, and passes the time in seconds.
 */
public final class QualityMeter {
    public static final int TS_PACKET = 188;
    private static final int NULL_PID = 0x1FFF;
    private static final double CHUNK_SECONDS = 0.1;

    private final double window;
    private final ArrayDeque<double[]> chunks = new ArrayDeque<>();
    private final Map<Integer, Integer> lastCounter = new HashMap<>();
    private boolean started;
    private double startedAt;

    public QualityMeter() {
        this(5.0);
    }

    public QualityMeter(double windowSeconds) {
        this.window = windowSeconds;
    }

    public void reset() {
        chunks.clear();
        lastCounter.clear();
        started = false;
    }

    /**
     * Count every whole packet in {@code data}.
     *
     * @param data        buffer holding whole TS packets
     * @param length      valid bytes in {@code data}
     * @param nowSeconds  monotonic time in seconds
     */
    public void feed(byte[] data, int length, double nowSeconds) {
        if (data == null || length <= 0) {
            return;
        }
        if (!started) {
            started = true;
            startedAt = nowSeconds;
        }
        int usable = Math.min(length, data.length);
        for (int offset = 0; offset + TS_PACKET <= usable; offset += TS_PACKET) {
            if ((data[offset] & 0xFF) != 0x47) {
                continue;
            }
            int pid = ((data[offset + 1] & 0x1F) << 8) | (data[offset + 2] & 0xFF);
            if (pid == NULL_PID) {
                continue;
            }
            int adaptation = (data[offset + 3] >> 4) & 0x03;
            if (adaptation == 0b00 || adaptation == 0b10) {
                continue;         // reserved, or adaptation only: no payload
            }
            boolean clean = (data[offset + 1] & 0x80) == 0;
            int counter = data[offset + 3] & 0x0F;
            Integer previous = lastCounter.get(pid);
            if (previous != null && counter != previous
                    && counter != ((previous + 1) & 0x0F)) {
                clean = false;
            }
            lastCounter.put(pid, counter);
            count(nowSeconds, clean ? 1 : 0);
        }
    }

    private void count(double nowSeconds, int clean) {
        double start = Math.floor(nowSeconds / CHUNK_SECONDS) * CHUNK_SECONDS;
        double[] last = chunks.peekLast();
        if (last != null && last[0] == start) {
            last[1] += 1;
            last[2] += clean;
        } else {
            chunks.addLast(new double[]{start, 1, clean});
        }
    }

    /**
     * Quality as a percentage, or {@link Double#NaN} until a full window of data has been seen and
     * whenever the window contains no packets.
     */
    public double percent(double nowSeconds) {
        if (!started || nowSeconds - startedAt < window) {
            return Double.NaN;
        }
        double horizon = nowSeconds - window;
        while (!chunks.isEmpty() && chunks.peekFirst()[0] < horizon) {
            chunks.removeFirst();
        }
        double total = 0;
        double clean = 0;
        for (double[] chunk : chunks) {
            total += chunk[1];
            clean += chunk[2];
        }
        if (total <= 0) {
            return Double.NaN;
        }
        return 100.0 * clean / total;
    }
}
