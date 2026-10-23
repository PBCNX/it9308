# IT930x bridge protocol

The ITE IT930x is the USB bridge in front of the demodulator. This file is the
shared transport knowledge: the command set, the frame layout, the firmware
format, the GPIO block and the TS path. `it9309` imports `it9308.transport`, so
a change here is a change for two devices - keep the public shape stable.

Everything below was read off captured USB traffic, the vendor code's *behaviour*,
or the stock Linux driver `nxdong520/avl6381` / `px4_drv` (GPL-2.0: facts and
register values are used, never its code). Where a claim is a measurement from
this bench it carries a date.

## Hardware

| | 048d:9308 (this repo) | 048d:9309 (shares the transport) |
|---|---|---|
| Bridge | IT930x, reports chip type `0x9306` | IT9303, reports chip type `0x9306` |
| Endpoints | `0x02` OUT commands, `0x81` IN responses, `0x84` IN TS | same, plus `0x85` IN (unused) |
| Bridge firmware | 6,498 B, 137 scatter records, reports `1.10.0.0` | 7,013 B, 147 records, reports `1.12.0.0` |
| Demod | Sony, I2C bus 2 at 7-bit `0x64`/`0x66`, page-switched | Panasonic MN88553H, bus 3 at `0x60`/`0x61`/`0x62` |

The bridge half is identical: firmware upload, register access, I2C, GPIO and the
TS block all work the same way on both. Only the demod profile differs.

## Command frames

Request:

```
[len] [cmd hi] [cmd lo] [seq] [body ...] [checksum hi] [checksum lo]
```

Response:

```
[len] [seq] [result] [data ...] [checksum hi] [checksum lo]
```

* `len` counts the bytes after itself, checksum included. (The stock driver
  calls the same value `len - 1` because it counts the whole frame, length byte
  included; the value on the wire is the same.)
* `seq` comes from a free-running 8-bit counter and the response must echo it.
* `result` is 0 for success. A non-zero result is the device reporting a failed
  command (`0x15` is an I2C NAK, for example).
* **Checksum**: one's complement of the sum of big-endian 16-bit words over the
  bytes after `len`, excluding the checksum itself. It is stored big-endian.

Both halves of that last sentence trip people up. Decoded from the 9309 capture
(`docs/9309-vendor-capture.txt`; the log's `TX 13` is the total transfer length,
one more than `len`):

```
frame  0c 0001 02 01 02 00 00 49 76 00 85 b4
       ^^ ^^^^ ^^ ^^^^^^^^^^^^^^^^^^^^^ ^^^^^
       len cmd seq         body            cksum
words 0001+0201+0200+0049+7600 = 7A4B, ~ = 85B4, bytes 85 B4
```

`it9309/docs/9309.md` and `it9309/bridge.py` describe the checksum as
little-endian; the wire bytes say big-endian. `transport.word_sum()` is correct.

## Commands

| cmd | name | body | notes |
|---|---|---|---|
| `0x00` | register read | `[len] [addr width] [addr 4B]` | response carries `len` bytes |
| `0x01` | register write | `[len] [addr width] [addr 4B] [data ...]` | `len` may be > 1: one command writes a register range |
| `0x21` | FW_DL | image bytes | bulk download; not used by the 9308/9309 flow |
| `0x22` | QUERYINFO | `[01]` | response 4 bytes, firmware version big-endian (`010a0000` = 1.10.0.0) |
| `0x23` | BOOT | none | starts the uploaded image |
| `0x24` | FW_DL_BEGIN | - | download session open; unused here |
| `0x25` | FW_DL_END | - | download session close; unused here |
| `0x29` | FW_SCATTER_WRITE | one scatter record | see *Firmware format* |
| `0x2a` | I2C read | `[len] [bus] [addr<<1]` | no register byte: the register pointer is a separate write |
| `0x2b` | I2C write | `[len] [bus] [addr<<1] [data ...]` | |
| `0x33/0x34/0x35/0x37` | UART read/write/baud/mode | - | present in the stock driver for a B-CAS reader |

`addr width` is the number of significant address bytes, 1 to 4 (`0x4976` -> 2,
`0xDA4C` -> 2, `0xF103` -> 2, `0x00` -> 1). `transport.address_bytes()` implements
exactly the stock driver's `it930x_reg_length()`.

`transport.py` exposes only single-byte `write_register`; the captured 9308
sequence needs multi-byte writes (`0xDD88` below), which is why `device.py`
replays raw frames instead of rebuilding them.

## I2C: the generic path, and why chip type matters

On a bridge reporting chip type `0x9306` the two I2C commands take the *generic*
body above. The older 5-byte sub-header path in the vendor library is not used.
Read the type as 3 bytes from register `0x1222`:

```
9308 (measured 2026-10-23): 01 06 93
9309 (recorded in it9309/docs/9309.md): 01 06 93
```

Byte 0 is a revision/config byte (`01` on both); bytes 1..2 are the type field
the vendor code calls `chip_type`, `06 93` -> **0x9306**. Both sticks therefore
take the same generic path, which is why one `transport.py` serves both.

Addressing is 7-bit shifted left one in the body (`0x64` -> `0xC8`). The bus
number is passed raw: `[len, bus, addr<<1, ...]`. Measured on the 9309: bus 2
answers only through bridge ports, the real tuner is bus 3; on the 9308 the Sony
demod is bus 2 at `0x64`/`0x66`. Never assume the bus.

An I2C NAK comes back as result `0x15`, not as a USB error.

## Firmware: scatter records, and RAM that a replug clears

The bridge has no flash. The image is downloaded into RAM and started:

1. `write_register(0xF103, 0x07)` - I2C port setup the vendor does first.
2. one `0x29` command per scatter record, in order.
3. `0x23` BOOT.
4. `0x22` QUERYINFO; `0x00000000` means the image did not start.

**Record format** (verified against both images, 137 and 147 records):

```
+0     0x03              magic
+1     0x00 / 0x01       0 for a data record, 1 for the last record
+2     0x00              reserved
+3     segments          N
+4     3*N bytes         N x (addr hi, addr lo, length)
+4+3N  payload           concatenated segment bytes
```

Record size is `4 + 3*N + sum(lengths)`. Addresses are 16-bit; the normal first
segment is `0x4100`. The final record on both images is the `+1 = 01` one, a
single 3-byte segment at `0x4100`; it is sent like any other record and is what
the BOOT then jumps to.

**A replug costs an upload.** Measured on the 9309: after a replug `0x22` reads
`0x00000000` and every later command times out; re-uploading the image and
booting fixes it. An early note in `it9309/docs/9309.md` says the firmware
"persists across a replug"; the rest of that tree's bench notes, and the
AGENDA, say otherwise, and the replug behaviour is the established one. The
9308 in this session reported `0x010a0000` at start-up, which is consistent
with it not having been replugged since its last upload - not with the bridge
having flash.

`firmware.py` pins the 9308 image by size (6,498) and SHA-256. The image is
vendor material: it lives in the private tree, and `release.ps1` withholds it
from the public snapshot.

## GPIO: 16 pins, four registers each, and a trap

The block is `0xd8ae..0xd8ef`. Each pin has four consecutive registers:

```
base+0  input      (read)
base+1  output     (write the level here)
base+2  mode       0 = input, 1 = output
base+3  enable     1 = drive the pin
```

Pin order is **not** linear:

| pin | base | pin | base |
|---|---|---|---|
| GPIO1 | `0xd8ae` | GPIO9 | `0xd8ca` |
| GPIO2 | `0xd8b6` | GPIO10 | `0xd8d6` |
| GPIO3 | `0xd8b2` | GPIO11 | `0xd8d2` |
| GPIO4 | `0xd8be` | GPIO12 | `0xd8de` |
| GPIO5 | `0xd8ba` | GPIO13 | `0xd8da` |
| GPIO6 | `0xd8c6` | GPIO14 | `0xd8e2` |
| GPIO7 | `0xd8c2` | GPIO15 | `0xd8e6` |
| GPIO8 | `0xd8ce` | GPIO16 | `0xd8ea` |

**The trap that cost hours: writing the output register alone does nothing.**
The pin must first be set to output (mode=1) and enabled (enable=1). The vendor
capture only makes sense once that is known:

```
0xd8d4 = 01   GPIO11 mode = output
0xd8d5 = 01   GPIO11 enable
0xd8d3 = 01   GPIO11 level high
0xd8b8 = 01   GPIO2  mode = output
0xd8b9 = 01   GPIO2  enable
0xd8b7 = 0,1,0,1   GPIO2 output, pulsed - not held
```

Documented meanings (stock driver, values only):

* **GPIO1** - "reset & power slave demod": output, enable, low, 30 ms, high,
  150 ms. Cycled on the 9309 with no change; the 9309's own capture raises
  GPIO2/GPIO11 instead.
* **GPIO2 / GPIO3** - tuner *input select*, not power enables: DVB-T is GPIO2
  high + GPIO3 low; DVB-C is both low. On the 9309 a GPIO2 pulse also revives a
  dead tuner bus; the capture pulses it `0,1,0,1` rather than holding it high.
* **GPIO6** - card-detect input and **GPIO14** - B-CAS reset are the stock
  driver's *own board* wiring; do not assume them on another board.

A GPIO sweep on the 9309 (each pin as a real output, both polarities) made no
new I2C device appear, so "some GPIO is holding the tuner off" is closed there.

## TS path

The bridge's TS block is written in the `0xDA`/`0xDD`/`0x49`/`0xD8` ranges. The
registers that matter, with the values measured read-back on the 9308 after its
952-step sequence (2026-10-23):

| register | value | meaning |
|---|---|---|
| `0xDA58` | `00` | serial input (bit 0 clear) |
| `0xDA51` | `00` | packet length field |
| `0xDA73` | `03` | TS aggregation (stock driver sets bit 0) |
| `0xDA78` | `47` | sync byte the bridge inserts/checks |
| `0xDA4C` | `01` | **TS enable** |
| `0xDA5A` | `1F` | ignore-fail mask |
| `0xDA14` / `0xDA17` | `01` / `1F` | PID filter config |
| `0xDD88` | `B0 0E` | frame size, **little-endian** `0x0EB0` = 3,760 = 20 x 188 |

`0xF001` is the PID table: a 0x7F-byte bitmap written by the vendor, followed by
the `0xDA14..0xDA17` filter registers. The 9308 sequence writes the table four
times as it repeats the init/tune phases.

**Trap:** `0xDD88`/`0xDD89` is one 16-bit little-endian value on the wire: `B0`
first, then `0E`. A table that writes `0x0E` to `0xDD88` and `0xB0` to `0xDD89`
stores `0xB00E` (45,070), not 3,760. The capture bytes are `dd88 b0 0e`.

The TS endpoint is `0x84` and delivers whole 188-byte packets once the demod
locks. `PacketAligner` finds the `0x47` phase; on a healthy feed it discards
nothing.

## Porting this transport to another IT930x device

1. `0x22` - if it reads 0, upload the device's scatter image, `0x23`, re-read.
2. Read `0x1222`; `06 93` (0x9306) means the generic I2C body above.
3. Configure the TS block: `0xDD88` frame size, `0xDA73`, `0xDA78`, filters,
   then `0xDA4C = 1`. These are bridge settings, independent of the demod.
4. The demod is a separate I2C device with its own bus and address. Get its
   address from the vendor capture, not from a sibling device.
5. A replug throws the firmware away; every tool must be able to upload before
   it can talk to the bridge.

## 048d:9308 bring-up

The 952-step sequence in `it9308/sequence.py` is the captured vendor bring-up
(950 command frames, 3,668 ms of captured delays):

1. **Firmware** - `0x22`; if 0, `0xF103 = 7`, the scatter records, `0x23`.
2. **Bridge init** - `0x4976`, `0x4BFB`, `0x4978`, `0x4977`, `0xF6A7`, `0xF103`,
   then the `0xDAxx`/`0xDDxx`/`0xD8xx` TS and GPIO block.
3. **Demod init/tune** - page-select writes to `0x66` (`00 00`, `00 10`,
   `00 11`, `00 16`) plus register traffic on `0x64` and `0x66`. The tune itself
   is an I2C write to `0x66` whose payload contains the frequency as 24-bit kHz:
   `09 24 67` = 599,143 kHz. The sequence captures this frequency twice.
4. **TS enable** - `0xF001` PID table, `0xDA14..0xDA17`, then `0xDA4C = 1`.

`device.py` replays the frames verbatim, delays included; it does not rebuild
them. A response audit (2026-10-23, `tools/audit_replay.py`) showed **952/952
commands result 0 and every response echoing the request sequence number** - the
bridge and the demod I2C path accept the whole sequence.

The tune is not parameterised in Python yet: `play` always replays 599.143 MHz.
The Java port has a `Sequence.patched(steps, frequencyKhz)` that substitutes the
three frequency bytes, but it has not been validated on hardware. Everything
else that is per-frequency lives in those same three bytes.

## Verified output

The mux is the same one this bench has used since 2026-10-23 00:34. PAT:

```
program 2624 -> PMT 0x0101   program 2625 -> PMT 0x0102   program 2648 -> PMT 0x1FC8
```

Each program is H.264 (`stream_type 0x1B`) on `0x0111` / `0x0121` / `0x0211`,
audio (`0x11`, AAC ADTS) on `0x0112` / `0x0122` / `0x0212`, with PCR on
`0x0100` / `0x0120` / `0x0210`.

Two dated captures, both at 599.143 MHz from the DTA-115 bench feed:

| | 2026-10-23 00:34 | 2026-10-23 12:57 |
|---|---|---|
| bytes / packets | 8,272,376 / 44,002 | 33,284,084 / 177,043 (33,299,072 on the wire) |
| duration | - | 45.0 s |
| bad sync bytes | 0 | 0 |
| framing loss | - | 14,960 B (~79 packets, one resync) |
| bitrate | - | 5.92 Mbps |
| CC discontinuities | 6 | 16,728 |

The 12:57 run is what the same stick, sequence and `bench.py` measure on
today's feed. Every emitted packet starts `0x47` and `transport_error_indicator`
is clear. The CC gaps are single or double packets, not the 20-packet burst a
dropped 3,760-byte USB frame would produce; one read also lost phase and the
aligner discarded that ~15 KB buffer. Both point at the playout/feed rather than
the USB path, and the 00:34 capture shows the same chain delivering a
near-perfect stream. These are recorded as bench observations, not driver
results.

