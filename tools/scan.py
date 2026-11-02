"""Scan UHF channels with the 048d:9308 on a real antenna.

Each channel needs the full captured sequence (the two tune frames alone do not
retune), so expect ~5 s per channel plus the dwell. A channel is reported as a
hit when it delivers a clean TS with at least --min-packets packets.

A failed replay is recovered with a USB reset and one retry; a channel that
still fails is skipped and the device is reset again for the next one.

    python tools/scan.py --start 479143 --end 509143 --dwell 3
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import bench  # noqa: E402  (tools/bench.py, for the PSI decoder)
from it9308.device import It9308Device  # noqa: E402
from it9308.transport import Device, PID_IT9308, devices  # noqa: E402


def connect():
    found = [d for d in devices() if d.idProduct == PID_IT9308]
    if not found:
        raise SystemExit("no IT9308 device (048d:9308) found")
    return Device(found[0]).open()


def recover(device):
    """USB reset, then a fresh handle; the firmware is re-uploaded on start()."""
    try:
        device.usb.reset()
    except Exception as exc:
        print("  reset: %s" % exc)
    time.sleep(2)
    try:
        device.close()
    except Exception:
        pass
    return connect()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=473143, metavar="KHZ")
    parser.add_argument("--end", type=int, default=695143, metavar="KHZ")
    parser.add_argument("--step", type=int, default=6000, metavar="KHZ")
    parser.add_argument("--dwell", type=float, default=2.0, metavar="SECONDS")
    parser.add_argument("--min-packets", type=int, default=20)
    parser.add_argument("--firmware", metavar="PATH")
    args = parser.parse_args(argv)

    device = connect()
    try:
        device = recover(device)
    except Exception as exc:
        print("initial reset failed: %s" % exc)

    hits = []
    try:
        frequencies = list(range(args.start, args.end + 1, args.step))
        for index, frequency in enumerate(frequencies, 1):
            tuner = None
            for attempt in (1, 2):
                try:
                    tuner = It9308Device(device)
                    tuner.start(args.firmware, frequency)
                    break
                except Exception as exc:
                    print("%7d kHz  attempt %d failed: %s" % (
                        frequency, attempt, exc))
                    if attempt == 1:
                        try:
                            device = recover(device)
                        except Exception as exc2:
                            print("  recovery failed: %s" % exc2)
                            device = None
                            break
                    else:
                        tuner = None
            if device is None:
                break
            if tuner is None:
                try:
                    device = recover(device)
                except Exception as exc:
                    print("  recovery failed: %s" % exc)
                    break
                continue

            started = time.time()
            data = bytearray()
            while time.time() - started < args.dwell:
                data += tuner.read_ts(timeout=500)
            packets = len(data) // 188
            sync = sum(1 for i in range(0, packets * 188, 188) if data[i] == 0x47)
            pat, pmt, _cc = bench.psi(bytes(data))
            hit = packets >= args.min_packets and sync == packets
            print("%7d kHz  %6d pkt  %6d sync  %8.3f Mbps  programs %d  %s" % (
                frequency, packets, sync,
                len(data) * 8.0 / max(time.time() - started, 0.001) / 1e6,
                len(pat), "HIT" if hit else ""))
            if hit:
                hits.append((frequency, len(pat), sorted(pat), sorted(pmt)))
            if index < len(frequencies):
                print("  ...", flush=True)
    finally:
        try:
            device.close()
        except Exception:
            pass

    print("\n%d channel(s) with TS:" % len(hits))
    for frequency, programs, pat, pmt in hits:
        print("  %7d kHz  programs %d %s  PMT %s" % (
            frequency, programs, [hex(p) for p in pat], [hex(p) for p in pmt]))


if __name__ == "__main__":
    main()
