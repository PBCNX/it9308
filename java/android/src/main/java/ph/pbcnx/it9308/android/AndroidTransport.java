package ph.pbcnx.it9308.android;

import android.hardware.usb.UsbConstants;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbEndpoint;
import android.hardware.usb.UsbInterface;
import android.hardware.usb.UsbManager;

import java.io.IOException;
import java.util.Arrays;

import ph.pbcnx.it9308.Transport;

/**
 * Android USB transport for the IT930x command endpoints.
 *
 * The shape is taken from the vendor AIRialTV GO 1.0.6/2.0.4
 * {@code com.adth.endeavoursony.Bus}: interface 0, command endpoint 0x02 OUT
 * and 0x81 IN, 500 ms transfers, and the TS endpoint 0x84 read in 15,040-byte
 * batches. This class selects endpoints by address; the vendor selects them by
 * index, and the addresses are the stable part.
 *
 * The class lives outside {@code java/src} on purpose: the plain-JVM self-test
 * has no android.jar. See {@code java/android/README.md}.
 */
public final class AndroidTransport implements Transport {

    /** Measured vendor command timeout. */
    public static final int COMMAND_TIMEOUT_MS = 500;

    /** 4 x 3,760 = 80 x 188, the bridge's TS frame batch. */
    public static final int TS_BATCH_BYTES = 15040;

    public static final int EP_COMMAND_OUT = 0x02;
    public static final int EP_COMMAND_IN = 0x81;
    public static final int EP_TS_IN = 0x84;

    private final UsbDeviceConnection connection;
    private final UsbInterface usbInterface;
    private final UsbEndpoint commandOut;
    private final UsbEndpoint commandIn;
    private final UsbEndpoint tsIn;

    private AndroidTransport(UsbDeviceConnection connection, UsbInterface usbInterface,
                             UsbEndpoint commandOut, UsbEndpoint commandIn, UsbEndpoint tsIn) {
        this.connection = connection;
        this.usbInterface = usbInterface;
        this.commandOut = commandOut;
        this.commandIn = commandIn;
        this.tsIn = tsIn;
    }

    /**
     * Open the stick, claim interface 0 and find the three bulk endpoints.
     *
     * The caller must already hold USB permission for the device
     * ({@code UsbManager.requestPermission}).
     */
    public static AndroidTransport open(UsbManager manager, UsbDevice device) throws IOException {
        if (manager == null || device == null) {
            throw new IOException("no USB device");
        }
        UsbInterface usbInterface = device.getInterface(0);
        UsbDeviceConnection connection = manager.openDevice(device);
        if (connection == null) {
            throw new IOException("openDevice failed - USB permission?");
        }
        if (!connection.claimInterface(usbInterface, true)) {
            connection.close();
            throw new IOException("claimInterface(0) failed");
        }
        UsbEndpoint commandOut = null;
        UsbEndpoint commandIn = null;
        UsbEndpoint tsIn = null;
        for (int i = 0; i < usbInterface.getEndpointCount(); i++) {
            UsbEndpoint endpoint = usbInterface.getEndpoint(i);
            if (endpoint.getType() != UsbConstants.USB_ENDPOINT_XFER_BULK) {
                continue;
            }
            switch (endpoint.getAddress()) {
                case EP_COMMAND_OUT:
                    commandOut = endpoint;
                    break;
                case EP_COMMAND_IN:
                    commandIn = endpoint;
                    break;
                case EP_TS_IN:
                    tsIn = endpoint;
                    break;
                default:
                    break;
            }
        }
        if (commandOut == null || commandIn == null || tsIn == null) {
            connection.releaseInterface(usbInterface);
            connection.close();
            throw new IOException("missing bulk endpoint(s): need 0x02, 0x81, 0x84");
        }
        return new AndroidTransport(connection, usbInterface, commandOut, commandIn, tsIn);
    }

    @Override
    public void write(byte[] data, int timeoutMs) {
        int sent = connection.bulkTransfer(commandOut, data, data.length, timeoutMs);
        if (sent != data.length) {
            throw new IllegalStateException("command OUT: " + sent + "/" + data.length);
        }
    }

    @Override
    public byte[] read(int maxLength, int timeoutMs) {
        byte[] buffer = new byte[maxLength];
        int received = connection.bulkTransfer(commandIn, buffer, maxLength, timeoutMs);
        if (received <= 0) {
            throw new IllegalStateException("command IN failed: " + received);
        }
        return Arrays.copyOf(buffer, received);
    }

    /** The raw connection, for the TS reader. */
    public UsbDeviceConnection connection() {
        return connection;
    }

    /** The TS bulk-IN endpoint (0x84). */
    public UsbEndpoint tsEndpoint() {
        return tsIn;
    }

    public void close() {
        try {
            connection.releaseInterface(usbInterface);
        } catch (RuntimeException ignored) {
            // already released
        }
        connection.close();
    }
}
