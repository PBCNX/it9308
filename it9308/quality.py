"""Stream quality: the share of clean TS packets over a sliding window.

The same definition the studio's other driver lines use: a packet is **not clean** when
its transport_error_indicator is set, or when its continuity counter breaks on its PID
(a repeated counter is not a break). Null packets (PID 0x1FFF) and adaptation-only
packets are not counted at all. Quality is ``100 * clean / total`` over the last
``window`` seconds, and is **unknown** (``None``) until the first full window has been
observed, and again whenever the window is empty.

This is deliberately not the demodulator's SNR: it answers the player's question - "is
the stream I am receiving clean" - from the stream itself, so the number means the same
on every chip. The SNR-derived figure stays available separately.
"""
import math
import time
from collections import deque

TS_PACKET = 188
NULL_PID = 0x1FFF

# Packets are counted in 100 ms chunks: a near-exact sliding window without one object per
# packet (4.7 Mbit/s is ~3,100 packets a second, ~15,500 in a 5 s window).
CHUNK_SECONDS = 0.1


class QualityMeter:
    def __init__(self, window=5.0):
        self.window = float(window)
        self.chunks = deque()      # [start, total, clean]
        self.last_cc = {}          # PID -> continuity counter
        self.started = None

    def reset(self):
        self.chunks.clear()
        self.last_cc.clear()
        self.started = None

    def feed(self, data, now=None):
        """Count every whole packet in ``data``; ``now`` in seconds (default: monotonic)."""
        if now is None:
            now = time.monotonic()
        if self.started is None:
            self.started = now
        for offset in range(0, len(data) - TS_PACKET + 1, TS_PACKET):
            packet = data[offset:offset + TS_PACKET]
            if packet[0] != 0x47:
                continue
            pid = ((packet[1] & 0x1F) << 8) | packet[2]
            if pid == NULL_PID:
                continue
            adaptation = (packet[3] >> 4) & 0x03
            if adaptation in (0b00, 0b10):
                continue           # reserved, or adaptation only: no payload
            total, clean = 1, not (packet[1] & 0x80)
            counter = packet[3] & 0x0F
            previous = self.last_cc.get(pid)
            if previous is not None and counter != previous and counter != ((previous + 1) & 0x0F):
                clean = False
            self.last_cc[pid] = counter
            self._count(now, total, clean)

    def _count(self, now, total, clean):
        # floor(now / chunk) * chunk, not now % chunk: the modulo rounds 1.0 to 0.9 and moves a chunk
        # across the window edge. The Java QualityMeter uses Math.floor for the same reason.
        start = math.floor(now / CHUNK_SECONDS) * CHUNK_SECONDS
        if self.chunks and self.chunks[-1][0] == start:
            self.chunks[-1][1] += total
            self.chunks[-1][2] += clean
        else:
            self.chunks.append([start, total, clean])

    def percent(self, now=None):
        """Quality as a percentage, or ``None`` until a full window of data has been seen."""
        if now is None:
            now = time.monotonic()
        if self.started is None or now - self.started < self.window:
            return None
        horizon = now - self.window
        while self.chunks and self.chunks[0][0] < horizon:
            self.chunks.popleft()
        total = sum(chunk[1] for chunk in self.chunks)
        if not total:
            return None
        clean = sum(chunk[2] for chunk in self.chunks)
        return int(round(100.0 * clean / total))
