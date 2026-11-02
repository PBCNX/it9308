package ph.pbcnx.it9308;

import java.util.ArrayList;
import java.util.List;

/**
 * Dependency-free checks. The fake transport answers like the bridge and
 * records every write, so the parameterised frames can be compared with the
 * Python driver's expected bytes.
 */
public final class SelfTest {
    private SelfTest() {
    }

    private static final class Fake implements Transport {
        final List<String> writes = new ArrayList<>();
        byte[] last;
        byte[] lastI2c;

        public void write(byte[] data, int timeoutMs) {
            writes.add(toHex(data));
            last = data;
            int command = ((data[1] & 0xFF) << 8) | (data[2] & 0xFF);
            if (command == Bridge.WRITE_I2C && data.length > 6) {
                lastI2c = new byte[data.length - 6];
                System.arraycopy(data, 4, lastI2c, 0, lastI2c.length);
            }
        }

        public byte[] read(int maxLength, int timeoutMs) {
            int command = ((last[1] & 0xFF) << 8) | (last[2] & 0xFF);
            int seq = last[3] & 0xFF;
            byte[] payload;
            if (command == Bridge.INFO) {
                payload = new byte[]{1, 0, 0, 0};
            } else if (command == Bridge.READ_I2C) {
                int expected = last[4] & 0xFF;
                payload = new byte[expected];
                if (lastI2c != null && lastI2c.length >= 4) {
                    int address = (lastI2c[2] & 0xFF) >> 1;
                    int register = lastI2c[3] & 0xFF;
                    if (address == 0x66 && register == 0xFD) {
                        payload[0] = 0x6A;
                    } else if (address == 0x64 && register == 0x10) {
                        payload[0] = 0x21;                 // locked
                    } else if (address == 0x64 && register == 0x13) {
                        payload[0] = 0x07;
                    } else if (address == 0x64 && register == 0x14) {
                        payload[0] = 0x44;                 // 0x0744 = 23.7 dB
                    } else if (address == 0x64 && register == 0x11) {
                        payload[0] = 0x08;
                    } else if (address == 0x64 && register == 0x12) {
                        payload[0] = 0x58;                 // RF index 66
                    }
                }
            } else {
                payload = new byte[0];
            }
            byte[] response = new byte[5 + payload.length];
            response[0] = (byte) seq;
            response[1] = 0;
            response[2] = 0;
            System.arraycopy(payload, 0, response, 3, payload.length);
            int sum = Bridge.checksum(response, response.length - 2);
            response[response.length - 2] = (byte) (sum >> 8);
            response[response.length - 1] = (byte) sum;
            return response;
        }
    }

    public static void main(String[] args) {
        checksumVector();

        Fake fake = new Fake();
        It9308Device device = new It9308Device(fake);
        device.setDelayScale(0);

        String version = device.bringUp(null);
        check(version.equals("0x01000000"), "version " + version);
        check(fake.writes.size() >= 900, "bring-up writes " + fake.writes.size());

        fake.writes.clear();
        check(device.tune(599143), "tune 599143");
        check(fake.writes.contains("14002b8a0c02cc5200006b4d0000092467fffeaf23"),
                "captured 599143 frame");
        int captured = fake.writes.size();

        fake.writes.clear();
        check(device.tune(473143), "tune 473143");
        check(fake.writes.contains("14002b8a0c02cc5200006b4d0000073837fffe9b55"),
                "patched 473143 first frame");
        check(fake.writes.contains("14002b840c02cc5200006b4d0000073837fffea155"),
                "patched 473143 second frame");
        check(fake.writes.size() == captured, "write count changed");

        fake.writes.clear();
        device.setStreaming(true);
        check(fake.writes.get(0).contains("da4c01"), "stream on " + fake.writes.get(0));
        fake.writes.clear();
        device.setStreaming(false);
        check(fake.writes.get(0).contains("da4c00"), "stream off " + fake.writes.get(0));

        SignalStatus status = device.status();
        check(status.known, "status known");
        check(status.locked, "status locked");
        check(status.rawSnr == 1860, "raw snr " + status.rawSnr);
        check(Math.abs(status.snrDb - 23.664) < 0.01, "snr " + status.snrDb);
        check(status.rawStrength == 66, "rf " + status.rawStrength);
        check(status.strength == 66, "strength " + status.strength);

        fake.writes.clear();
        check(device.chipId() == 0x6A, "chip id");
        check(fake.writes.size() == 2, "chip id writes " + fake.writes.size());
        check(fake.writes.get(0).contains("2b") && fake.writes.get(0).contains("0102ccfd"),
                "chip id write " + fake.writes.get(0));
        check(fake.writes.get(1).contains("2a") && fake.writes.get(1).contains("0102cc"),
                "chip id read " + fake.writes.get(1));

        System.out.println("it9308 java self-test: OK (" + device.stepCount() + " steps)");
    }

    private static void checksumVector() {
        Bridge bridge = new Bridge(new Fake());
        byte[] frame = bridge.build(Bridge.INFO, 1, new byte[]{1});
        check(toHex(frame).equals("0600220101fedc"), "info frame " + toHex(frame));
    }

    private static String toHex(byte[] data) {
        StringBuilder builder = new StringBuilder();
        for (byte value : data) {
            builder.append(String.format("%02x", value & 0xFF));
        }
        return builder.toString();
    }

    private static void check(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }
}
