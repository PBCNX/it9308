package com.pbcnx.drivers.it9308;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * ISDB-T transmission parameters (TMCC) as this demod reports them.
 *
 * <p>The demod mirrors the TMCC bit stream closely enough that the ARIB STD-B31 layout applies
 * directly (Tables 3-22 and 3-23): each hierarchical layer is a 13-bit block - modulation 3, code rate
 * 3, interleave 3, segments 4 - and the blocks follow one another. Measured packing (2026-11-19,
 * controlled mux and real channels):
 *
 * <pre>
 * 0x24  bits 3:2 mode (2K=0, 8K=1, 4K=2), bits 1:0 guard (1/16=1, 1/8=2, 1/4=3, 1/32=0)
 * 0x32  bit 0 partial reception, bit 1 TMCC emergency flag (B26)
 * 0x33  bits 7:5 layer A modulation, 4:2 layer A code rate, 1:0 layer A interleave (high bits)
 * 0x34  bit 7 layer A interleave (low bit), 6:3 layer A segments, 2:0 layer B modulation
 * 0x35  bits 7:5 layer B code rate, 4:2 layer B interleave, 1:0 layer B segments (high bits)
 * 0x36  bits 7:6 layer B segments (low bits), 5:3 layer C modulation
 * </pre>
 *
 * <p>{@code 7} in a modulation field is the standard's "unused layer"; those print {@code "-"} and
 * anything outside the measured layout prints {@code "?"}.
 */
public final class Tmcc {
    private static final String UNKNOWN = "?";
    private static final int UNUSED = 7;

    /** One hierarchical layer. */
    public static final class Layer {
        public final boolean present;
        public final String modulation;
        public final String codeRate;
        public final String interleave;
        public final int segments;

        private Layer(boolean present, String modulation, String codeRate, String interleave,
                      int segments) {
            this.present = present;
            this.modulation = modulation;
            this.codeRate = codeRate;
            this.interleave = interleave;
            this.segments = segments;
        }

        private static Layer decode(int modulation, int code, int interleave, int segments) {
            boolean present = modulation != UNUSED;
            if (!present) {
                return new Layer(false, "-", "-", "-", 0);
            }
            return new Layer(true, modulationName(modulation), codeName(code),
                    interleaveName(interleave), segments);
        }
    }

    public final String mode;
    public final String guard;
    public final boolean partial;
    public final boolean ewbs;
    public final Layer layerA;
    public final Layer layerB;
    public final Layer layerC;
    public final Map<Integer, Integer> raw;

    /**
     * A reading is a channel only when at least one layer carries segments (1..13).
     *
     * <p>{@code 0x0000} is both a legitimate 2K / 1/32 configuration and what an <em>undecoded</em>
     * TMCC register reads; the layers are what tell them apart. Same rule as IT9175's {@code valid()}
     * (2026-11-20): a field that is zero by default is not evidence until something else agrees.
     */
    public boolean valid() {
        int total = 0;
        for (Layer layer : new Layer[]{layerA, layerB, layerC}) {
            if (layer.present) {
                total += layer.segments;
            }
        }
        return !UNKNOWN.equals(mode) && !UNKNOWN.equals(guard) && total >= 1 && total <= 13;
    }

    private Tmcc(String mode, String guard, boolean partial, boolean ewbs, Layer layerA,
                 Layer layerB, Layer layerC, Map<Integer, Integer> raw) {
        this.mode = mode;
        this.guard = guard;
        this.partial = partial;
        this.ewbs = ewbs;
        this.layerA = layerA;
        this.layerB = layerB;
        this.layerC = layerC;
        this.raw = raw;
    }

    /** Decode from the raw register bytes; {@code null} means the read failed. */
    public static Tmcc decode(Integer v24, Integer v32, Integer v33, Integer v34,
                              Integer v35, Integer v36) {
        return decode(v24, v32, v33, v34, v35, v36, null);
    }

    /** Decode including layer C (register 0x37). */
    public static Tmcc decode(Integer v24, Integer v32, Integer v33, Integer v34,
                              Integer v35, Integer v36, Integer v37) {
        Map<Integer, Integer> raw = new LinkedHashMap<>();
        put(raw, 0x24, v24);
        put(raw, 0x32, v32);
        put(raw, 0x33, v33);
        put(raw, 0x34, v34);
        put(raw, 0x35, v35);
        put(raw, 0x36, v36);
        put(raw, 0x37, v37);

        String mode = UNKNOWN;
        String guard = UNKNOWN;
        if (v24 != null) {
            mode = modeName((v24 >> 2) & 0x03);
            guard = guardName(v24 & 0x03);
        }
        boolean partial = v32 != null && (v32 & 0x01) != 0;
        boolean ewbs = v32 != null && (v32 & 0x02) != 0;

        Layer layerA = new Layer(false, "-", "-", "-", 0);
        Layer layerB = new Layer(false, "-", "-", "-", 0);
        Layer layerC = new Layer(false, "-", "-", "-", 0);
        if (v33 != null) {
            int r34 = v34 == null ? 0 : v34;
            int r35 = v35 == null ? 0xFF : v35;
            int r36 = v36 == null ? 0xFF : v36;
            int r37 = v37 == null ? 0xFF : v37;
            layerA = Layer.decode((v33 >> 5) & 0x07, (v33 >> 2) & 0x07,
                    ((v33 & 0x03) << 1) | ((r34 >> 7) & 0x01), (r34 >> 3) & 0x0F);
            layerB = Layer.decode(r34 & 0x07, (r35 >> 5) & 0x07, (r35 >> 2) & 0x07,
                    ((r35 & 0x03) << 2) | ((r36 >> 6) & 0x03));
            layerC = Layer.decode((r36 >> 3) & 0x07, r36 & 0x07,
                    (r37 >> 5) & 0x07, (r37 >> 1) & 0x0F);
        }
        return new Tmcc(mode, guard, partial, ewbs, layerA, layerB, layerC, raw);
    }

    private static void put(Map<Integer, Integer> raw, int register, Integer value) {
        if (value != null) {
            raw.put(register, value);
        }
    }

    private static String modeName(int value) {
        switch (value) {
            case 0: return "2K";
            case 1: return "8K";
            case 2: return "4K";
            default: return UNKNOWN;
        }
    }

    private static String guardName(int value) {
        switch (value) {
            case 0: return "1/32";
            case 1: return "1/16";
            case 2: return "1/8";
            case 3: return "1/4";
            default: return UNKNOWN;
        }
    }

    private static String modulationName(int value) {
        switch (value) {
            case 0: return "DQPSK";
            case 1: return "QPSK";
            case 2: return "16QAM";
            case 3: return "64QAM";
            default: return UNKNOWN;
        }
    }

    private static String codeName(int value) {
        switch (value) {
            case 0: return "1/2";
            case 1: return "2/3";
            case 2: return "3/4";
            case 3: return "5/6";
            case 4: return "7/8";
            default: return UNKNOWN;
        }
    }

    private static String interleaveName(int value) {
        switch (value) {
            case 0: return "I0";
            case 1: return "I1";
            case 2: return "I2";
            case 3: return "I4";
            default: return UNKNOWN;
        }
    }

    /** One line, in the shape the hosts asked for. */
    public String describe() {
        StringBuilder line = new StringBuilder();
        line.append("tmcc mode ").append(mode)
            .append("  guard ").append(guard)
            .append("  partial ").append(partial ? 1 : 0)
            .append("  ewbs ").append(ewbs ? 1 : 0);
        line.append(layerText("L0", layerA)).append(layerText("L1", layerB))
            .append(layerText("L2", layerC));
        return line.toString();
    }

    private static String layerText(String name, Layer layer) {
        if (!layer.present) {
            return "  " + name + ":-";
        }
        return "  " + name + ":" + layer.modulation + " " + layer.codeRate + " "
                + layer.interleave + " " + layer.segments + "seg";
    }
}
