"""Bench measurement for the 048d:9308 stick.

Brings the stick up, reads the TS endpoint for a fixed time and prints the
numbers a claim needs: packets, framing loss ("sync errors"), bitrate, PSI and
continuity-counter errors.  --out keeps the emitted transport stream, and
--analyze re-runs the same measurements on a file without touching hardware.

    python tools/bench.py --seconds 20
    python tools/bench.py --seconds 20 --out capture.ts
    python tools/bench.py --analyze capture.ts

This measures the endpoint and the driver's PacketAligner, not a demodulator
register: if the endpoint delivers nothing there is no signal to report.
"""
import argparse
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from it9308.device import It9308Device  # noqa: E402
from it9308.transport import (Device, PacketAligner, PID_IT9308,  # noqa: E402
                              devices)

TS = 188


def _section(pkt):
    """PSI section carried by a PUSI packet, or None."""
    afc = (pkt[3] >> 4) & 3
    offset = 4
    if afc & 2:
        offset += 1 + pkt[4]
    if offset >= TS:
        return None
    section = pkt[offset + 1 + pkt[offset]:]
    if len(section) < 3:
        return None
    length = ((section[1] & 0x0F) << 8) | section[2]
    if 3 + length > len(section) or length < 4:
        return None
    return section[:3 + length]


def psi(packets):
    """PAT and PMT decode plus continuity counters.

    PAT entries start 8 bytes into the section; the first one is the network
    PID (program 0) and is not a program.  Both mistakes were made once here
    and produced a 4,000-entry "PAT"; the header length is the whole point.
    """
    cc_errors = Counter()
    last = {}
    pat = {}
    for start in range(0, len(packets) - TS + 1, TS):
        pkt = packets[start:start + TS]
        if pkt[0] != 0x47:
            continue
        pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
        afc = (pkt[3] >> 4) & 3
        cc = pkt[3] & 0x0F
        if pid in last and afc & 1:
            if cc != ((last[pid] + 1) & 0x0F):
                cc_errors[pid] += 1
        last[pid] = cc
        if pid != 0 or not (pkt[1] & 0x40):
            continue
        section = _section(pkt)
        if section is None or section[0] != 0x00:
            continue
        body = section[8:-4]
        for pos in range(0, len(body) - 3, 4):
            program = (body[pos] << 8) | body[pos + 1]
            ppid = ((body[pos + 2] & 0x1F) << 8) | body[pos + 3]
            if program:
                pat[program] = ppid

    pmt = {}
    wanted = set(pat.values())
    for start in range(0, len(packets) - TS + 1, TS):
        pkt = packets[start:start + TS]
        if pkt[0] != 0x47 or not (pkt[1] & 0x40):
            continue
        pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
        if pid not in wanted or pid in pmt:
            continue
        section = _section(pkt)
        if section is None or section[0] != 0x02:
            continue
        body = section[3:-4]
        if len(body) < 9:
            continue
        pcr = ((body[5] & 0x1F) << 8) | body[6]
        info_len = ((body[7] & 0x0F) << 8) | body[8]
        streams = []
        pos = 9 + info_len
        while pos + 5 <= len(body):
            stype = body[pos]
            epid = ((body[pos + 1] & 0x1F) << 8) | body[pos + 2]
            es_len = ((body[pos + 3] & 0x0F) << 8) | body[pos + 4]
            streams.append((stype, epid))
            pos += 5 + es_len
        pmt[pid] = (pcr, streams)
    return pat, pmt, cc_errors


def report(packets, endpoint_bytes, elapsed, framing_loss):
    emitted = len(packets)
    bad_sync = sum(1 for i in range(0, emitted, TS) if packets[i] != 0x47)
    pat, pmt, cc_errors = psi(packets)
    print("seconds          %.1f" % elapsed)
    print("endpoint bytes   %d" % endpoint_bytes)
    print("packets          %d" % (emitted // TS))
    print("framing loss     %d bytes (%d packets)" % (framing_loss, framing_loss // TS))
    print("bad sync bytes   %d" % bad_sync)
    print("bitrate          %s" % (
        "%.3f Mbps" % (endpoint_bytes * 8.0 / elapsed / 1e6) if elapsed else "n/a (file)"))
    print("PAT programs     %s" % ({k: "0x%04x" % v for k, v in pat.items()} or "none"))
    for pid, (pcr, streams) in pmt.items():
        print("PMT 0x%04x       PCR 0x%04x  streams %s" % (
            pid, pcr, ", ".join("0x%02x->0x%04x" % s for s in streams)))
    print("CC errors        %s" % (dict(cc_errors) or "none"))
    return 0 if emitted else 1


def analyze(path):
    data = open(path, "rb").read()
    whole = len(data) // TS * TS
    return report(data[:whole], len(data), 0.0, len(data) - whole)


def live(args):
    found = [d for d in devices() if d.idProduct == PID_IT9308]
    if args.index >= len(found):
        raise SystemExit("no IT9308 device (048d:9308) at index %d" % args.index)
    raw = Device(found[args.index]).open()
    aligner = PacketAligner()
    try:
        tuner = It9308Device(raw, lambda line: print(line, file=sys.stderr))
        tuner.start(args.firmware)
        started = time.time()
        endpoint_bytes = 0
        packets = bytearray()
        while time.time() - started < args.seconds:
            try:
                chunk = raw.read_stream(timeout=500)
            except Exception:
                continue
            if not chunk:
                continue
            endpoint_bytes += len(chunk)
            packets += aligner.push(chunk)
        elapsed = time.time() - started
    finally:
        raw.close()
    loss = endpoint_bytes - len(packets) - len(aligner.buffer)
    if args.out:
        with open(args.out, "wb") as handle:
            handle.write(packets)
        print("wrote            %s" % args.out)
    return report(bytes(packets), endpoint_bytes, elapsed, loss)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--firmware", metavar="PATH")
    parser.add_argument("--out", metavar="PATH", help="write the emitted TS here")
    parser.add_argument("--analyze", metavar="PATH", help="measure a file, no device")
    args = parser.parse_args(argv)
    return analyze(args.analyze) if args.analyze else live(args)


if __name__ == "__main__":
    raise SystemExit(main())
