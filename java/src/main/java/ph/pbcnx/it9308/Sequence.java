package ph.pbcnx.it9308;

import java.io.DataInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/** Captured bring-up sequence, exported from the Python table. */
public final class Sequence {
    /** 599,143 kHz as encoded in the captured tune frames. */
    static final byte[] CAPTURED_FREQUENCY = {0x09, 0x24, 0x67};

    public static final class Step {
        public final int delayMs;
        public final byte[] frame;
        public final int reply;

        Step(int delayMs, byte[] frame, int reply) {
            this.delayMs = delayMs;
            this.frame = frame;
            this.reply = reply;
        }
    }

    private Sequence() {
    }

    public static List<Step> load() {
        InputStream stream = Sequence.class.getResourceAsStream("/it9308/sequence.bin");
        if (stream == null) {
            throw new IllegalStateException("sequence.bin resource missing");
        }
        try (DataInputStream input = new DataInputStream(stream)) {
            byte[] magic = new byte[4];
            input.readFully(magic);
            if (!new String(magic, StandardCharsets.US_ASCII).equals("SQ93")) {
                throw new IllegalStateException("bad sequence magic");
            }
            int count = Integer.reverseBytes(input.readInt());
            List<Step> steps = new ArrayList<>(count);
            for (int index = 0; index < count; index++) {
                int delay = Short.toUnsignedInt(Short.reverseBytes(input.readShort()));
                int length = Short.toUnsignedInt(Short.reverseBytes(input.readShort()));
                byte[] frame = new byte[length];
                input.readFully(frame);
                int reply = input.readUnsignedByte();
                steps.add(new Step(delay, length == 0 ? null : frame, reply));
            }
            return steps;
        } catch (IOException error) {
            throw new IllegalStateException("cannot read sequence", error);
        }
    }

    /** Returns a copy of the steps with the captured frequency field replaced. */
    public static List<Step> patched(List<Step> steps, int frequencyKhz) {
        if (frequencyKhz <= 0 || frequencyKhz > 0xFFFFFF) {
            throw new IllegalArgumentException("frequency out of range: " + frequencyKhz);
        }
        byte[] replacement = {(byte) (frequencyKhz >> 16), (byte) (frequencyKhz >> 8),
                (byte) frequencyKhz};
        if (java.util.Arrays.equals(replacement, CAPTURED_FREQUENCY)) {
            return new ArrayList<>(steps);
        }
        List<Step> result = new ArrayList<>(steps.size());
        for (Step step : steps) {
            byte[] frame = step.frame;
            if (frame != null && indexOf(frame, CAPTURED_FREQUENCY) >= 0) {
                frame = frame.clone();
                replace(frame, CAPTURED_FREQUENCY, replacement);
            }
            result.add(new Step(step.delayMs, frame, step.reply));
        }
        return result;
    }

    private static int indexOf(byte[] data, byte[] pattern) {
        outer:
        for (int start = 0; start + pattern.length <= data.length; start++) {
            for (int offset = 0; offset < pattern.length; offset++) {
                if (data[start + offset] != pattern[offset]) {
                    continue outer;
                }
            }
            return start;
        }
        return -1;
    }

    private static void replace(byte[] data, byte[] pattern, byte[] replacement) {
        int at;
        while ((at = indexOf(data, pattern)) >= 0) {
            System.arraycopy(replacement, 0, data, at, replacement.length);
        }
    }

    public static void replay(Transport transport, List<Step> steps, int timeoutMs,
                              double delayScale) {
        for (Step step : steps) {
            if (step.delayMs > 0 && delayScale > 0) {
                try {
                    Thread.sleep((long) (step.delayMs * delayScale));
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    throw new IllegalStateException("replay interrupted", interrupted);
                }
            }
            if (step.frame == null) {
                continue;
            }
            transport.write(step.frame, timeoutMs);
            try {
                transport.read(256, timeoutMs);
            } catch (RuntimeException ignored) {
                // a step without a reply may time out
            }
        }
    }
}
