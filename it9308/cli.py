"""Command line interface for the IT9308 driver."""
import argparse
import socket
import sys
import time

from . import PROVENANCE, __version__, tune
from .device import It9308Device
from .transport import Device, PID_IT9308, TransportError, devices


def open_device(index=0):
    found = [d for d in devices() if d.idProduct == PID_IT9308]
    if not found:
        raise SystemExit("no IT9308 device (048d:9308) found; bind it to WinUSB first")
    if index >= len(found):
        raise SystemExit("only %d device(s) found" % len(found))
    return Device(found[index]).open()


def cmd_list(args):
    found = False
    for device in devices():
        found = True
        supported = "supported" if device.idProduct == PID_IT9308 else "unsupported"
        print("048d:%04x  bus %s addr %s  %s" % (
            device.idProduct, device.bus, device.address, supported))
    if not found:
        print("no 048d devices found")
    return 0


def cmd_probe(args):
    device = open_device(args.index)
    try:
        tuner = It9308Device(device, print)
        tuner.start(args.firmware, args.freq)
        try:
            print("demod chip id: 0x%02x" % tuner.chip_id())
        except TransportError as exc:
            print("demod chip id: unavailable (%s)" % exc)
        status = tuner.status()
        if status.known:
            snr = "%.2f dB" % status.snr_db if status.snr_db == status.snr_db else "n/a"
            print("lock: %s  snr: %s  rf: %d (relative index)" % (
                status.locked, snr, status.raw_strength))
        else:
            print("status: unavailable")
        total = 0
        for _ in range(8):
            data = tuner.read_ts()
            total += len(data)
            if total > 100000:
                break
        print("ts: %d bytes" % total)
        return 0 if total else 1
    finally:
        device.close()


class Sink:
    def __init__(self, path=None, udp=None):
        self.file = None
        self.sock = None
        self.addr = None
        if udp:
            host, _, port = udp.rpartition(":")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.addr = (host or "127.0.0.1", int(port))
        elif path and path != "-":
            self.file = open(path, "wb")
        else:
            self.file = sys.stdout.buffer

    def write(self, data):
        if self.sock:
            for i in range(0, len(data), 1316):
                self.sock.sendto(data[i:i + 1316], self.addr)
        else:
            self.file.write(data)
            self.file.flush()

    def close(self):
        if self.file and self.file is not sys.stdout.buffer:
            self.file.close()
        if self.sock:
            self.sock.close()


def cmd_play(args):
    device = open_device(args.index)
    sink = Sink(args.out, args.udp)
    try:
        tuner = It9308Device(device, print)
        tuner.start(args.firmware, args.freq)
        started = time.time()
        last_status = time.time()
        packets = 0
        while not args.seconds or time.time() - started < args.seconds:
            data = tuner.read_ts()
            if data:
                sink.write(data)
                packets += len(data) // 188
            if args.status_interval and time.time() - last_status >= args.status_interval:
                last_status = time.time()
                status = tuner.status()
                if status.quality >= 0:
                    quality = status.quality
                elif status.snr_db == status.snr_db:  # not NaN
                    quality = max(0, min(100, int(round(status.snr_db / 30.0 * 100.0))))
                else:
                    quality = -1
                print("ts packets %d  lock %s  strength %s  quality %s" % (
                    packets, status.locked, status.strength, quality),
                    file=sys.stderr)
        print("wrote %d packets" % packets, file=sys.stderr)
        return 0
    finally:
        sink.close()
        device.close()


def _quality(status):
    if status.quality >= 0:
        return status.quality
    if status.snr_db == status.snr_db:  # not NaN
        return max(0, min(100, int(round(status.snr_db / 30.0 * 100.0))))
    return -1


def cmd_scan(args):
    if args.step <= 0 or args.stop < args.start:
        print("invalid scan range", file=sys.stderr)
        return 2
    device = open_device(args.index)
    try:
        tuner = It9308Device(device, lambda message: print(message, file=sys.stderr))
        frequencies = list(range(args.start, args.stop + 1, args.step))
        tuner.start(args.firmware, frequencies[0])
        for frequency in frequencies:
            if frequency != frequencies[0]:
                tuner.start(None, frequency)
            started = time.time()
            while time.time() - started < args.dwell:
                tuner.read_ts()
            status = tuner.status()
            print("%7d kHz  %-7s strength %3d  quality %3d  dbm %4d" % (
                frequency, "LOCK" if status.locked else "no lock",
                status.strength, _quality(status), -1000), flush=True)
        return 0
    finally:
        device.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="it9308", description=__doc__)
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__ + " (" + PROVENANCE + ")")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list 048d devices")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("scan", help="scan a frequency range in one process")
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--firmware", metavar="PATH")
    p.add_argument("--start", type=int, default=473143, metavar="KHZ")
    p.add_argument("--stop", type=int, default=695143, metavar="KHZ")
    p.add_argument("--step", type=int, default=6000, metavar="KHZ")
    p.add_argument("--dwell", type=float, default=2.0, metavar="SECONDS")
    p.set_defaults(func=cmd_scan)

    for name, func, text in (("probe", cmd_probe, "bring up and read TS"),
                             ("play", cmd_play, "stream MPEG-TS")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--index", type=int, default=0)
        p.add_argument("--firmware", metavar="PATH")
        p.add_argument("--freq", type=int, default=tune.CAPTURED_KHZ, metavar="KHZ",
                       help="centre frequency in kHz (default 599143)")
        p.set_defaults(func=func)
        if name == "play":
            p.add_argument("--out", default="-", help="file, - for stdout")
            p.add_argument("--udp", help="HOST:PORT")
            p.add_argument("--seconds", type=float, default=0)
            p.add_argument("--status-interval", type=float, default=5.0,
                           help="print live lock/strength/quality every N seconds (0 to disable)")

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
