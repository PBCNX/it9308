package com.pbcnx.drivers.it9308;

/**
 * ISDB-T Information Packet (IIP): the frame-ahead transmission-control packet.
 *
 * <p>One TSP per multiplex frame, multiplexed in the <em>invalid hierarchy</em> and not carried by any of
 * layers A/B/C. Per ARIB STD-B31 v2.2-E1 (Tables 5-8, 5-10) the 184-byte payload is a 16-bit pointer, a
 * 160-bit modulation-control block (MCCI), then branch numbers and the network-synchronization length.
 *
 * <p>Unlike TMCC, the IIP <em>does</em> carry the transmission mode and guard interval (Tables 5-10 and
 * 5-11: {@code current_mode} 01/10/11 = 2K/4K/8K, guard 00..11 = 1/32, 1/16, 1/8, 1/4) and the next
 * frame's copy of the EWBS flag (B26). The {@code CRC_32} is ISO/IEC 13818-1's CRC-32 over the first 16 of
 * the 20 MCCI bytes, stored big-endian.
 *
 * <p>Ported from the Python decoder ({@code it9308/iip.py}) and validated against the family's one-packet
 * fixture plus two real CAP-09 payloads; the bit order is MSB-first within each byte.
 */
public final class Iip {
    private static final String UNKNOWN = "?";
    private static final int UNUSED = 7;
    private static final String[] MODES = {"?", "2K", "4K", "8K"};
    private static final String[] GUARDS = {"1/32", "1/16", "1/8", "1/4"};
    private static final String[] MODULATIONS = {"DQPSK", "QPSK", "16QAM", "64QAM"};
    private static final String[] CODES = {"1/2", "2/3", "3/4", "5/6", "7/8"};
    private static final String[] INTERLEAVES = {"I0", "I1", "I2", "I4"};

    /** One hierarchical layer of the next frame. */
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
    }

    public final int pointer;
    public final String mode;
    public final String guard;
    public final String nextMode;
    public final String nextGuard;
    public final boolean ewbs;
    public final boolean partial;
    public final Layer layerA;
    public final Layer layerB;
    public final Layer layerC;
    public final int branch;
    public final int lastBranch;
    public final int netSyncLength;
    public final boolean crcOk;

    private Iip(int pointer, String mode, String guard, String nextMode, String nextGuard, boolean ewbs,
                boolean partial, Layer layerA, Layer layerB, Layer layerC, int branch, int lastBranch,
                int netSyncLength, boolean crcOk) {
        this.pointer = pointer;
        this.mode = mode;
        this.guard = guard;
        this.nextMode = nextMode;
        this.nextGuard = nextGuard;
        this.ewbs = ewbs;
        this.partial = partial;
        this.layerA = layerA;
        this.layerB = layerB;
        this.layerC = layerC;
        this.branch = branch;
        this.lastBranch = lastBranch;
        this.netSyncLength = netSyncLength;
        this.crcOk = crcOk;
    }

    /** Decode one IIP payload (the bytes after the 4-byte TSP header). */
    public static Iip decode(byte[] payload) {
        if (payload == null || payload.length < 25) {
            throw new IllegalArgumentException("IIP payload too short");
        }
        int pointer = ((payload[0] & 0xFF) << 8) | (payload[1] & 0xFF);
        Reader reader = new Reader(payload, 2, 20);   // the 160-bit MCCI block
        reader.take(1);                               // TMCC_synchronization_word
        reader.take(1);                               // AC_data_effective_position
        reader.take(2);                               // reserved
        reader.take(4);                               // initialization_timing_indicator
        String mode = name(MODES, reader.take(2));
        String guard = name(GUARDS, reader.take(2));
        String nextMode = name(MODES, reader.take(2));
        String nextGuard = name(GUARDS, reader.take(2));
        reader.take(2);                               // system_identifier
        reader.take(4);                               // count_down_index
        boolean ewbs = reader.take(1) != 0;           // B26 copy for the next frame
        boolean partial = reader.take(1) != 0;
        Layer layerA = layer(reader);
        Layer layerB = layer(reader);
        Layer layerC = layer(reader);
        reader.take(1);                               // next partial_reception_flag
        layer(reader);                                // next A
        layer(reader);                                // next B
        layer(reader);                                // next C
        reader.take(3);                               // phase correction
        reader.take(12);                              // TMCC reserved
        reader.take(10);                              // reserved_future_use
        reader.take(32);                              // CRC_32
        int crc = crc32Mpeg2(payload, 2, 16);
        int stored = ((payload[18] & 0xFF) << 24) | ((payload[19] & 0xFF) << 16)
                | ((payload[20] & 0xFF) << 8) | (payload[21] & 0xFF);
        return new Iip(pointer, mode, guard, nextMode, nextGuard, ewbs, partial, layerA, layerB, layerC,
                payload[22] & 0xFF, payload[23] & 0xFF, payload[24] & 0xFF, crc == stored);
    }

    /** ISO/IEC 13818-1 CRC-32 (STD-B31 Table 5-10 {@code CRC_32}), poly 0x04C11DB7. */
    public static int crc32Mpeg2(byte[] data, int offset, int length) {
        int crc = 0xFFFFFFFF;
        for (int i = 0; i < length; i++) {
            crc ^= (data[offset + i] & 0xFF) << 24;
            for (int bit = 0; bit < 8; bit++) {
                if ((crc & 0x80000000) != 0) {
                    crc = (crc << 1) ^ 0x04C11DB7;
                } else {
                    crc <<= 1;
                }
            }
        }
        return crc;
    }

    public String describe() {
        return "iip mode " + mode + "  guard " + guard + "  partial " + (partial ? 1 : 0)
                + "  ewbs " + (ewbs ? 1 : 0) + layerText("L0", layerA) + layerText("L1", layerB)
                + layerText("L2", layerC);
    }

    private static String layerText(String name, Layer layer) {
        if (!layer.present) {
            return "  " + name + ":-";
        }
        return "  " + name + ":" + layer.modulation + " " + layer.codeRate + " " + layer.interleave
                + " " + layer.segments + "seg";
    }

    private static Layer layer(Reader reader) {
        int modulation = reader.take(3);
        int code = reader.take(3);
        int interleave = reader.take(3);
        int segments = reader.take(4);
        boolean present = modulation != UNUSED && segments != 15;
        if (!present) {
            return new Layer(false, "-", "-", "-", 0);
        }
        return new Layer(true, name(MODULATIONS, modulation), name(CODES, code),
                name(INTERLEAVES, interleave), segments);
    }

    private static String name(String[] table, int index) {
        return index >= 0 && index < table.length ? table[index] : UNKNOWN;
    }

    /** MSB-first bit reader over a byte window. */
    private static final class Reader {
        private final byte[] data;
        private final int start;
        private final int end;
        private int position;

        Reader(byte[] data, int start, int length) {
            this.data = data;
            this.start = start;
            this.end = start + length;
            this.position = start * 8;
        }

        int take(int count) {
            int value = 0;
            for (int i = 0; i < count; i++) {
                int index = position >> 3;
                int bit = 7 - (position & 7);
                value = (value << 1) | ((data[index] >> bit) & 1);
                position++;
            }
            return value;
        }
    }
}
