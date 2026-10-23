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

        public void write(byte[] data, int timeoutMs) {
            writes.add(toHex(data));
            last = data;
        }

        public byte[] read(int maxLength, int timeoutMs) {
            int command = ((last[1] & 0xFF) << 8) | (last[2] & 0xFF);
            int seq = last[3] & 0xFF;
            int data = command == Bridge.INFO ? 4 : 0;
            byte[] response = new byte[5 + data];
            response[0] = (byte) seq;
            response[1] = 0;
            response[2] = 0;
            if (data == 4) {
                response[3] = 1;
            }
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
        check(fake.writes.contains("14002b8a0c02cc5200006b4d0000073837fffeaf23"),
                "patched 473143 first frame");
        check(fake.writes.contains("14002b840c02cc5200006b4d0000073837fffeb523"),
                "patched 473143 second frame");
        check(fake.writes.size() == captured, "write count changed");

        fake.writes.clear();
        device.setStreaming(true);
        check(fake.writes.get(0).contains("da4c01"), "stream on " + fake.writes.get(0));
        fake.writes.clear();
        device.setStreaming(false);
        check(fake.writes.get(0).contains("da4c00"), "stream off " + fake.writes.get(0));

        SignalStatus status = device.status();
        check(!status.known && !status.locked, "status " + status);

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
