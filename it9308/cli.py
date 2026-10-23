"""Command line interface for the IT9308 driver."""
import argparse
import socket
import sys
import time

from . import __version__
from .device import It9308Device
from .transport import Device, PID_IT9308, devices


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
        tuner.start(args.firmware)
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
        tuner.start(args.firmware)
        started = time.time()
        packets = 0
        while not args.seconds or time.time() - started < args.seconds:
            data = tuner.read_ts()
            if data:
                sink.write(data)
                packets += len(data) // 188
        print("wrote %d packets" % packets, file=sys.stderr)
        return 0
    finally:
        sink.close()
        device.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="it9308", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list 048d devices")
    p.set_defaults(func=cmd_list)

    for name, func, text in (("probe", cmd_probe, "bring up and read TS"),
                             ("play", cmd_play, "stream MPEG-TS")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--index", type=int, default=0)
        p.add_argument("--firmware", metavar="PATH")
        p.set_defaults(func=func)
        if name == "play":
            p.add_argument("--out", default="-", help="file, - for stdout")
            p.add_argument("--udp", help="HOST:PORT")
            p.add_argument("--seconds", type=float, default=0)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
