"""Command line interface for the IT9308 driver."""
import argparse
import json
import os
import socket
import subprocess
import sys
import time

from . import PROVENANCE, __version__, firmware, tune
from .device import It9308Device
from .quality import QualityMeter
from .tmcc import describe, read_tmcc, watch
from .transport import Device, PID_IT9308, TransportError, devices

TS_PACKET = 188
UDP_CHUNK = 7 * TS_PACKET


def require_firmware(args):
    """Check the firmware image before touching the bus: one line, exit 2 (the guide's promise)."""
    try:
        firmware.load(getattr(args, "firmware", None))
    except (OSError, ValueError) as error:
        print("error: %s" % error, file=sys.stderr)
        raise SystemExit(2)


def open_device(index=0):
    found = [d for d in devices() if d.idProduct == PID_IT9308]
    if not found:
        raise SystemExit("no IT9308 device (048d:9308) found; bind it to WinUSB first")
    if index >= len(found):
        raise SystemExit("only %d device(s) found" % len(found))
    try:
        return Device(found[index]).open()
    except Exception as error:  # noqa: BLE001 - pyusb raises USBError
        # The player turns "cannot claim" into "the stick is busy: another
        # program is using it"; a Windows busy open says "Access denied".
        message = str(error)
        lowered = message.lower()
        if "busy" in lowered or "access" in lowered or "denied" in lowered \
                or "permission" in lowered:
            raise SystemExit("cannot claim the device (busy): %s" % message)
        raise


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
    require_firmware(args)
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


def drop_null_packets(data):
    """Drop whole MPEG-TS null packets (PID 0x1FFF); keep anything unaligned.

    Only complete 188-byte packets are inspected. A trailing partial packet is
    passed through untouched, so a caller that hands over an unaligned read does
    not lose bytes.
    """
    if not data:
        return data
    out = bytearray()
    whole = len(data) - len(data) % TS_PACKET
    for offset in range(0, whole, TS_PACKET):
        packet = data[offset:offset + TS_PACKET]
        if packet[0] == 0x47 and (((packet[1] & 0x1F) << 8) | packet[2]) == 0x1FFF:
            continue
        out += packet
    if whole < len(data):
        out += data[whole:]
    return bytes(out)


def null_padding(size):
    """Whole null TS packets that fill `size` bytes of a datagram tail."""
    count = size // TS_PACKET
    if count <= 0:
        return b""
    return (b"\x47\x1f\xff\x10" + b"\xff" * (TS_PACKET - 4)) * count


def status_line(packets, locked, strength, quality, snr):
    """The line the players parse; see the driver CLI contract.

    ``quality`` is the stream meter (the share of clean TS packets over the last
    5 s), the same definition the other drivers use; ``snr`` is the demod's
    SNR in dB on its own field.
    """
    return "ts packets %d  lock %s  strength %s  quality %s  snr %s" % (
        packets, locked, strength, quality, snr)


def known(value):
    """The contract allows `n/a` when a monitor is unknown (-1 in this driver)."""
    return "n/a" if value is None or value < 0 else value


def play_lock(status, flowing):
    """The stream decides: a lock bit with no packets in the interval is not a lock."""
    return bool(status.locked and flowing)


def scan_locked(status, packets):
    """A channel counts only when the demod locked and packets actually arrived."""
    return bool(status.locked and packets > 0)


class Sink:
    """TS output: a file, stdout, or 7 x 188-byte UDP datagrams.

    UDP output is buffered until a whole 1,316-byte datagram can be sent; a
    final short tail is padded with whole null packets, so every datagram is
    7 x 188 bytes. `packets` counts the packets handed on (after --drop-null).
    """

    def __init__(self, path=None, udp=None, drop_null=False):
        self.file = None
        self.sock = None
        self.addr = None
        self.pending = bytearray()
        self.packets = 0
        self.drop_null = drop_null
        if udp:
            host, _, port = udp.rpartition(":")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.addr = (host or "127.0.0.1", int(port))
        elif path and path != "-":
            self.file = open(path, "wb")
        else:
            self.file = sys.stdout.buffer

    def write(self, data):
        if not data:
            return
        if self.drop_null:
            data = drop_null_packets(data)
        if not data:
            return
        self.packets += len(data) // TS_PACKET
        if self.sock:
            self.pending += data
            while len(self.pending) >= UDP_CHUNK:
                self.sock.sendto(bytes(self.pending[:UDP_CHUNK]), self.addr)
                del self.pending[:UDP_CHUNK]
            return
        self.file.write(data)
        self.file.flush()

    def close(self):
        if self.sock:
            while self.pending:
                chunk = bytes(self.pending[:UDP_CHUNK])
                del self.pending[:UDP_CHUNK]
                self.sock.sendto(chunk + null_padding(UDP_CHUNK - len(chunk)),
                                 self.addr)
            self.sock.close()
        elif self.file and self.file is not sys.stdout.buffer:
            self.file.close()


def stalled_hint(locked, stalled_seconds, limit):
    """State 3 detection: locked, device present, and no TS for ``limit`` seconds.

    Time-based (IT9175's ``--stall-seconds`` shape) rather than status-line counting, so the rule does not
    change when the status interval does. Silence alone is not a wedge - an unlocked tuner is just an empty
    channel - so the lock is part of the condition.
    """
    return bool(locked) and stalled_seconds >= limit


def reconnect_stream(args, log):
    """Wait for the stick to reappear and bring it back up (the vendor app's pattern, in-process).

    A mid-stream unplug is not a wedged chip: the handle is dead, and the only correct move is to stop
    using it, wait for the device to re-enumerate, open a fresh handle and replay the tune. Returns
    ``(device, tuner)`` or ``(None, None)`` when the stick does not come back inside ``args.reconnect``.
    """
    deadline = time.time() + args.reconnect
    while time.time() < deadline:
        found = [d for d in devices() if d.idProduct == PID_IT9308]
        if found:
            try:
                raw = Device(found[0]).open()
                tuner = It9308Device(raw, log)
                tuner.start(args.firmware, args.freq)
                log("reconnected (bus %d addr %d)" % (found[0].bus, found[0].address))
                return raw, tuner
            except (TransportError, OSError) as error:
                log("reopen failed: %s" % error)
        time.sleep(0.5)
    return None, None


def recovery_outcome(before_version, after_version, before_address, after_address):
    """Say what happened using only what was read - never the code path that ran.

    ``after_version`` is the version read on the **reopened handle before any recovery work**, so a zero
    means the reboot lost the image (it had to be rebuilt). Passing the version *after* the upload would
    always look like "preserved" - the exact narration bug this function exists to prevent.

    ``before_version is None``  the chip could not be read before the reboot (a wedge)
    ``after_version == 0``      the image was lost -> it had to be rebuilt
    address changed             the USB session was rebuilt (re-enumeration)
    """
    if before_version is None:
        image = "firmware unreadable before"
    elif after_version == 0:
        image = "image rebuilt (blank after the reboot)"
    elif before_version != after_version:
        image = "image changed (0x%08x -> 0x%08x)" % (before_version, after_version)
    else:
        image = "image preserved (0x%08x)" % after_version
    if before_address is None or after_address is None:
        bus = "address not recorded"
    elif before_address == after_address:
        bus = "same address %d" % after_address
    else:
        bus = "re-enumerated (addr %d -> %d)" % (before_address, after_address)
    return "recovered: %s; %s" % (image, bus)


def blind_reboot(args, log):
    """Send the vendor reboot and close at once; the reply may never come (the endpoint stalls).

    Logs the firmware version **before** the reboot (if the chip still answers) so the before/after pair
    says whether the reboot reset the chip or merely restarted the resident image.
    """
    raw = open_device(args.index)
    before_version = None
    before_address = getattr(getattr(raw, "usb", None), "address", None)
    try:
        try:
            before_version = raw.firmware_version()
            log("firmware before reboot: 0x%08x" % before_version)
        except (TransportError, OSError) as error:
            log("firmware before reboot: unreadable (%s)" % error)
        raw.reboot_blind()
        log("sent reboot; reopening to verify")
    finally:
        raw.close()
    time.sleep(1.0)
    return before_version, before_address


def recover_stream(args, log):
    """State 3 of the recovery contract: locked but no TS -> recover the chip and resume.

    Blind-reboots, reopens a fresh handle, starts the tuner (which uploads only if the chip came back
    blank), verifies the demod chip id, then resumes the stream. Returns ``(device, tuner)`` or
    ``(None, None)``.
    """
    try:
        blind_reboot(args, log)
    except (TransportError, OSError) as error:
        log("recover: reboot failed (%s)" % error)
    for _attempt in range(2):
        try:
            found = [d for d in devices() if d.idProduct == PID_IT9308]
            target = found[args.index]
        except (IndexError, TransportError, OSError) as error:
            log("recover: device not present (%s)" % error)
            return None, None
        log("recover: re-opening bus %d addr %d" % (target.bus, target.address))
        try:
            raw = Device(target).open()
            tuner = It9308Device(raw, log)
            tuner.start(args.firmware, args.freq)
            chip = tuner.chip_id()
            if chip in SONY_CHIP_IDS:
                log("recovered (chip 0x%02x, firmware 0x%08x); resuming" % (chip, tuner.version))
                return raw, tuner
            log("recover: unexpected chip id 0x%02x" % chip)
            raw.close()
        except (TransportError, OSError) as error:
            log("recover: reopen failed (%s)" % error)
            try:
                raw.close()
            except Exception:
                pass
        time.sleep(1.0)
    return None, None


def recover_present_device(args, log):
    """One software recovery attempt for a device that is present but not answering.

    ``recover_stream`` needs a stream loop; this is the same move for a one-shot command: close, blind
    reboot, reopen, ``start()`` (uploads only if blank), verify the chip id. Returns True on success.
    """
    log("device present but not answering; attempting recovery")
    try:
        blind_reboot(args, log)
    except (TransportError, OSError) as error:
        log("recovery reboot failed: %s" % error)
    for _attempt in range(2):
        found = [d for d in devices() if d.idProduct == PID_IT9308]
        if not found:
            time.sleep(1.0)
            continue
        raw = None
        try:
            raw = Device(found[0]).open()
            tuner = It9308Device(raw, log)
            tuner.start(args.firmware, args.freq)
            chip = tuner.chip_id()
            if chip in SONY_CHIP_IDS:
                log("recovered (chip 0x%02x); retrying the command" % chip)
                # the reopened device has just re-enumerated; give the stack a moment before a second
                # handle opens on it (seen on the Pi: an immediate retry times out)
                try:
                    raw.close()
                except Exception:
                    pass
                time.sleep(1.5)
                return True
            log("recovery: unexpected chip id 0x%02x" % chip)
        except (TransportError, OSError) as error:
            log("recovery attempt failed: %s" % error)
        finally:
            if raw is not None:
                try:
                    raw.close()
                except Exception:
                    pass
        time.sleep(1.0)
    return False


def cmd_play(args):
    require_firmware(args)
    device = open_device(args.index)
    try:
        sink = Sink(args.out, args.udp, args.drop_null)
    except OSError as error:
        print("cannot open the output: %s" % error, file=sys.stderr)
        device.close()
        return 2
    meter = QualityMeter()
    try:
        # Everything the device says goes to stderr: stdout carries TS only.
        tuner = It9308Device(device, lambda message: print(message, file=sys.stderr,
                                                           flush=True))
        tuner.start(args.firmware, args.freq)
        # the pair belongs in every run that may recover: this is the "before" address
        print("device 048d:9308 bus %d addr %d" % (device.usb.bus, device.usb.address),
              file=sys.stderr, flush=True)
        started = time.time()
        last_status = time.time()
        last_packets = 0
        last_data = time.time()
        received = 0
        stalled = 0.0
        hinted = False
        switched = False
        while not args.seconds or time.time() - started < args.seconds:
            try:
                data = tuner.read_ts()
                if data:
                    last_data = time.time()
                    received += len(data) // TS_PACKET
                    meter.feed(data)
                    sink.write(data)
                elif args.reconnect and time.time() - last_data > 1.5:
                    # a pulled stick often returns empty reads instead of raising: the device simply
                    # disappears from the bus. Silence alone is not a disconnect (an empty channel is
                    # silent too), so require the device to be absent as well.
                    if not any(d.idProduct == PID_IT9308 for d in devices()):
                        print("device lost (gone from the bus)", file=sys.stderr, flush=True)
                        device.close()
                        device, tuner = reconnect_stream(args, lambda message: print(
                            message, file=sys.stderr, flush=True))
                        if device is None:
                            print("reconnect failed after %d s; unplug and replug the stick"
                                  % args.reconnect, file=sys.stderr, flush=True)
                            return 1
                        last_data = time.time()
                        last_status = time.time()
                        last_packets = received
                        continue
                if args.switch_to and not switched and time.time() - started >= args.switch_after:
                                switched = True
                                begun = time.time()
                                tuner.fast_retune(args.switch_to)
                                elapsed = time.time() - begun
                                print("switched to %d kHz in %.2f s" % (args.switch_to, elapsed),
                                      file=sys.stderr, flush=True)
                                # the block is transient for a few hundred ms after a switch; report it only when
                                # two reads agree (the same stability rule the tmcc command uses)
                                try:
                                    time.sleep(0.5)
                                    first = read_tmcc(device)
                                    time.sleep(0.2)
                                    second = read_tmcc(device)
                                    if first.valid and second.valid and describe(first) == describe(second):
                                        print("tmcc " + describe(second), file=sys.stderr, flush=True)
                                except (TransportError, OSError):
                                    pass
                if args.status_interval and time.time() - last_status >= args.status_interval:
                    last_status = time.time()
                    status = tuner.status()
                    flowing = received > last_packets
                    last_packets = received
                    stalled = time.time() - last_data if not flowing else 0.0
                    if not flowing and stalled_hint(status.locked, stalled, args.stall_seconds) \
                            and not hinted:
                        print("no TS while locked; attempting recover (not replugging yet)",
                              file=sys.stderr, flush=True)
                        device.close()
                        device, tuner = recover_stream(args, lambda message: print(
                            message, file=sys.stderr, flush=True))
                        if device is None:
                            print("recover did not bring the stream back; unplug and replug the stick",
                                  file=sys.stderr, flush=True)
                            return 1
                        hinted = True
                        last_status = time.time()
                        last_packets = received
                        continue
                    print(status_line(received, play_lock(status, flowing),
                                      known(status.strength), known_quality(meter.percent()),
                                      snr_text(status)), file=sys.stderr, flush=True)
            except (TransportError, OSError) as error:
                if not args.reconnect:
                    raise
                print("device lost: %s" % error, file=sys.stderr, flush=True)
                device.close()
                device, tuner = reconnect_stream(args, lambda message: print(
                    message, file=sys.stderr, flush=True))
                if device is None:
                    print("reconnect failed after %d s; unplug and replug the stick"
                          % args.reconnect, file=sys.stderr, flush=True)
                    return 1
                last_status = time.time()
                last_packets = received
                continue
        print("wrote %d packets" % sink.packets, file=sys.stderr)
        return 0
    finally:
        sink.close()
        if device is not None:
            device.close()


def known_quality(value):
    """The stream meter is None until a full window; the contract allows n/a."""
    return "n/a" if value is None else value


def snr_text(status):
    return "n/a" if status.snr_db != status.snr_db else "%.2f" % status.snr_db


def cmd_scan(args):
    require_firmware(args)
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
            # the meter spans the dwell, so a short scan still reports a stream Q
            meter = QualityMeter(window=max(0.5, args.dwell))
            # the dwell is time spent RECEIVING, not time spent tuning: a re-tuned channel
            # otherwise spends its whole dwell replaying the sequence and prints n/a
            started = None
            deadline = time.time() + args.dwell + 5.0
            packets = 0
            while time.time() < deadline:
                try:
                    data = tuner.read_ts()
                except (TransportError, OSError) as error:
                    # the vendor app interrupts a scan on detach; we do the same instead of a traceback
                    print("device lost during scan: %s" % error, file=sys.stderr, flush=True)
                    return 1
                if data:
                    if started is None:
                        started = time.time()
                    packets += len(data) // TS_PACKET
                    meter.feed(data)
                    if time.time() - started >= args.dwell:
                        break
            status = tuner.status()
            print("%7d kHz  %-7s strength %3s  quality %3s" % (
                frequency, "LOCK" if scan_locked(status, packets) else "no lock",
                known(status.strength), known_quality(meter.percent())), flush=True)
        return 0
    finally:
        device.close()


def cmd_tmcc(args):
    require_firmware(args)
    device = open_device(args.index)
    try:
        tuner = It9308Device(device, lambda message: print(message, file=sys.stderr))
        tuner.start(args.firmware, args.freq)
        time.sleep(args.settle)
        status = tuner.status()
        if not status.locked:
            print("no lock at %d kHz; tmcc needs a locked demod" % args.freq,
                  file=sys.stderr)
            return 1
        # a lock can precede TMCC decoding, and 0x0000 decodes to a plausible 2K / 1/32 / no layers;
        # a stale block can also pass the segment gate. So: retry until valid, then require two
        # consecutive reads to agree before calling it a channel (IT9175's "read it twice" advice).
        deadline = time.monotonic() + 2.0
        value = read_tmcc(device)
        while time.monotonic() < deadline:
            if value.valid:
                time.sleep(0.2)
                again = read_tmcc(device)
                if again.valid and describe(again) == describe(value):
                    value = again
                    break
                value = again
            else:
                time.sleep(0.25)
                value = read_tmcc(device)
        if not value.valid:
            print("tmcc not decoded yet (mode/guard/layers unreadable - the demod has not decoded "
                  "TMCC on this channel)", file=sys.stderr)
            return 1
        if args.watch:
            def read_locked():
                return read_tmcc(device) if tuner.status().locked else None

            watch(read_locked, interval=args.interval, seconds=args.seconds)
            return 0
        print(json.dumps(value.as_dict(), indent=1) if args.json else describe(value))
        return 0
    finally:
        device.close()


SONY_CHIP_IDS = (0x6A, 0x62)


def retry_recover(recover_once, attempts=3, sleep=time.sleep, emit=print):
    """Run ``recover_once`` up to ``attempts`` times with a pause between tries.

    ``recover_once`` opens the device, recovers, verifies it (chip id) and closes it - so a retry gets
    a **fresh handle**, which is the part that survives a re-enumeration. Returns ``(True, result)`` on a
    verified recovery, ``(False, None)`` after the last failure.
    """
    for attempt in range(1, attempts + 1):
        try:
            return True, recover_once(attempt)
        except Exception as error:  # noqa: BLE001 - every failure becomes a retry
            emit("recover attempt %d/%d failed: %s" % (attempt, attempts, error))
            if attempt < attempts:
                sleep(1.0)
    return False, None


def cmd_recover(args):
    require_firmware(args)
    log = lambda message: print(message, file=sys.stderr)

    def once(attempt):
        before_version, before_address = (None, None)
        if attempt == 1:
            # fire-and-forget: send the reboot, close immediately, and verify on a fresh handle - the
            # reply may never arrive because the reboot stalls the command endpoint
            before_version, before_address = blind_reboot(args, log)
        device = open_device(args.index)
        try:
            tuner = It9308Device(device, log)
            after_version = device.firmware_version()   # the state the reboot left, before any upload
            if attempt == 1 and not args.force:
                tuner.start(args.firmware, args.freq)   # uploads only if the chip came back blank
            else:
                tuner.recover(args.firmware, args.freq, force_upload=True)
            chip = tuner.chip_id()
            if chip not in SONY_CHIP_IDS:
                raise TransportError("demod chip id 0x%02x after recovery" % chip)
            after_address = getattr(getattr(device, "usb", None), "address", None)
            log("chip id 0x%02x, firmware 0x%08x" % (chip, tuner.version))
            # the sentence comes from the pair, never from the branch that ran
            return chip, tuner.version, tuner.status(), recovery_outcome(
                before_version, after_version, before_address, after_address)
        finally:
            device.close()

    ok, result = retry_recover(once)
    if not ok:
        print("recovery failed; unplug the stick and plug it back in (a USB reset does not clear "
              "its firmware state)", file=sys.stderr)
        return 1
    chip, version, status, outcome = result
    print("%s  chip 0x%02x  lock %s  strength %s  snr %s" % (
        outcome, chip, status.locked, known(status.strength), snr_text(status)))
    return 0


def rerun_in_fresh_process(argv):
    """Re-execute this command in a new process, once.

    On some USB stacks (the Pi's, measured 2026-11-20) a bridge that has just been recovered does not accept
    a second handle in the same process: the fresh handle works, so the fix is a fresh *process*. We mark the
    environment so a second failure reports rather than recursing.
    """
    environment = dict(os.environ)
    environment["IT9308_RECOVERED"] = "1"
    print("recovered; re-running the command in a fresh process", file=sys.stderr, flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    # execv keeps inherited descriptors: libusb usbfs handles would survive into the new image and
    # keep the interface claimed, so every command times out (Pi, 2026-11-20). Close them, then exec.
    try:
        os.closerange(3, 1024)
    except OSError:
        pass
    os.execve(sys.executable, [sys.executable, "-m", "it9308"] + [str(a) for a in argv], environment)
    return 1  # not reached


def main(argv=None):
    raw_argv = list(sys.argv[1:] if argv is None else argv)
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
            p.add_argument("--drop-null", action="store_true",
                           help="drop MPEG-TS null packets (PID 0x1FFF) before writing")
            p.add_argument("--status-interval", type=float, default=5.0,
                           help="print live lock/strength/quality every N seconds (0 to disable)")
            p.add_argument("--switch-to", type=int, metavar="KHZ",
                           help="change channel after --switch-after seconds (fast tail replay)")
            p.add_argument("--switch-after", type=float, default=5.0, metavar="SECONDS",
                           help="when to switch with --switch-to (default 5)")
            p.add_argument("--stall-seconds", type=float, default=2.0, metavar="SECONDS",
                           help="locked with no TS for this long counts as a wedge and starts recovery")
            p.add_argument("--reconnect", "--supervise-seconds", dest="reconnect", type=float,
                           default=10.0, metavar="SECONDS",
                           help="after a mid-stream unplug, wait this long for the stick to come back "
                                "and reopen it (0 disables; the long form --supervise-seconds is an "
                                "accepted synonym)")

    p = sub.add_parser("tmcc", help="read the channel's transmission parameters")
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--firmware", metavar="PATH")
    p.add_argument("--freq", type=int, default=tune.CAPTURED_KHZ, metavar="KHZ")
    p.add_argument("--settle", type=float, default=2.0, metavar="SECONDS",
                   help="wait after the tune before reading (default 2)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--watch", action="store_true",
                   help="poll and print ALERT/CLEAR when the EWBS flag changes")
    p.add_argument("--interval", type=float, default=1.0, metavar="SECONDS",
                   help="poll interval for --watch (default 1)")
    p.add_argument("--seconds", type=float, default=0, metavar="SECONDS",
                   help="stop --watch after N seconds (default: until interrupted)")
    p.set_defaults(func=cmd_tmcc)

    p = sub.add_parser("recover", help="clear a stuck bridge in software (blind reboot, reload if blank)")
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--firmware", metavar="PATH")
    p.add_argument("--freq", type=int, default=tune.CAPTURED_KHZ, metavar="KHZ")
    p.add_argument("--force", action="store_true",
                   help="upload the firmware even if the chip answers (forced bring-up)")
    p.set_defaults(func=cmd_recover)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (TransportError, OSError) as error:
        # the failure path is part of the driver: a USB error is a message, not a traceback
        print("error: %s" % error, file=sys.stderr)
        if hasattr(args, "freq"):
            log = lambda message: print(message, file=sys.stderr, flush=True)
            try:
                recovered = recover_present_device(args, log)
            except (TransportError, OSError) as again:
                # the environment itself cannot reach a bus (e.g. no libusb backend): one line, no traceback
                print("error: %s" % again, file=sys.stderr)
                return 1
            if recovered:
                if os.environ.get("IT9308_RECOVERED"):
                    print("recovered, but the command still failed; unplug and replug the stick",
                          file=sys.stderr)
                    return 1
                time.sleep(2.5)   # the reopened bridge needs a moment before a new process talks to it
                return rerun_in_fresh_process(raw_argv)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
