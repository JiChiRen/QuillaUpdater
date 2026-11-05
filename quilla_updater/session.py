# -*- coding: utf-8 -*-
# Copyright (c) 2026, JiChiRen Info. Tech.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# ``AS IS`` AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
# TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# This file is part of QuillaUpdater.

"""
Upgrade session state machine.

This is the whole QBOOT handshake and transfer, decoupled from any UI:

    detect state -> (ENTER) -> DATA* -> END -> [SIGN] -> wait for the new APP

Two design constraints come straight from the firmware and are not negotiable
here, see protocol.py:

  * the transfer is stop-and-wait: one frame in flight, ACK before the next, so
    neither the QBOOT receive ring (256 B) nor the circular DMA ring behind it
    (1024 B) is ever pressured by bytes the device cannot consume;
  * the SIGN frame needs a long timeout because the device spends ~21 s
    (SHA-256 + Ed25519 @8 MHz) verifying it inline.

Entry conditions. The board can be in one of four states and the operator
should not have to know which:

  A. upgrade-idle with a leftover QIAP flag  -> send ENTER directly
  B. QBOOT interactive shell                 -> "qiap" then ENTER
  C. APP shell (running firmware)             -> "swqboot" reset, then B
  D. upgrade-idle, raw sink, no echo          -> send ENTER directly

A, B and D all answer differently to `part`; that fingerprint is what makes the
detection reliable. In state D the binary ENTER frame still reaches the state
machine even though text commands are swallowed, so ENTER is always tried
before assuming the board is in the APP.

Completion is decided BEFORE the reset, on QBOOT-side evidence
--------------------------------------------------------------
QIAP calls commit_app() (app_page_commit() -> flag=APP1 -> done=1) before it
sends its completion ACK, so the ACK that follows a commit is a completion
code, not merely "the frame arrived". All three QBOOT build variants reach a
commit before qboot_qiap_run() reboots, and all three can therefore be reported
complete without waiting for the new APP to boot:

  QBOOT_CHECK  (CHECK mode,  no public key)
      END commits -> ACK_END 0x83 -> `[QIAP] flash complete ...` -> reset
  QBOOT_SEALED (SEALED mode, public key)
      END ACKs only -> SIGN verifies -> commit -> ACK_SIGN 0x84 -> reset
  QBOOT_SEC    (SECURE mode, public key)
      same as SEALED; only the POST-reset boot policy differs (~20 s Ed25519)

The differences between the variants are all *after* the reset. A verdict that
depended on the `[QAPP]` boot stamp would take 0.6 s on SEALED and ~20 s on
SECURE, and would fail outright on an APP that prints on another UART. So the
stamp is a non-fatal post-confirmation only; run() reports completion at the
post-commit ACK (or the commit announcement) and never waits for a reboot.

Completion evidence, strongest first:
  * ACK_SIGN 0x84                    - keyed variants, after commit_app()
  * ACK_END 0x83 + commit announce  - CHECK variant, END committed
  * commit announcement alone       - ACK lost, done=1 still observed
  * matching [QAPP] boot stamp      - arrives only after the reset
  * port lost to the reset          - WEAK: the reset follows done=1, but a
                                      cable pull looks the same. Logged as weak
                                      so the operator can re-check the board.

Why END can be the end of the conversation
------------------------------------------
With no public key provisioned, the END handler commits, qboot_qiap_run() sees
`quilla_qiap_is_done()` and prints `[QIAP] flash complete. Rebooting into APP...`
before resetting. Sending SIGN after that lands in the APP's shell, which does
not speak QIAP, so no ACK 0x84 can ever come back. end() therefore listens for
the announcement and run() skips SIGN when it was seen. The receive path keeps
the raw byte stream alongside frame parsing, because these one-shot banners
travel through the same port as the ACK frames and must not be consumed by the
frame parser while it waits.

Why SIGN does not insist on receiving ACK 0x84
----------------------------------------------
On a composite debug probe (WCH-Link, J-Link) the MCU reset that follows a
successful SIGN pulls the whole USB device off the bus for a moment. The device
sends ACK 0x84 and then resets, and the ACK is routinely lost in the
re-enumeration. sign() watches the commit announcement and the boot stamp in the
same window, so a lost ACK still leaves two independent ways to confirm the
commit; only an explicit NAK is a hard reject.
"""

import struct
import time
import hashlib

from . import protocol as P
from . import ed25519
from . import i18n
from .image import BOOT_STAMP_MARKER

__all__ = [
    "UpgradeError", "UpgradeCancelled", "PortOpenError", "Session", "Progress",
    "Result", "classify_open_error", "describe_open_error",
    "ACK_TIMEOUT", "SIGN_TIMEOUT", "APP_STAMP_TIMEOUT", "POST_CONFIRM_TIMEOUT",
    "MAX_RETRIES",
]

#: Per-frame ACK timeout.
ACK_TIMEOUT = 2.0
#: SIGN ACK timeout. Must exceed the device's ~20.6 s inline verification.
SIGN_TIMEOUT = 90.0
#: Wait for the new APP's boot stamp after the upgrade reset. Kept for callers
#: that explicitly ask for it (wait_app_stamp()); the normal run no longer waits
#: for a reboot at all, because SECURE builds take ~20 s to reach the APP.
APP_STAMP_TIMEOUT = 45.0
#: Best-effort peek for a stamp that arrived in the same USB packet as the
#: completion code. Deliberately shorter than any boot path (CHECK ~0.1 s,
#: SEALED ~0.6 s, SECURE ~20 s): this never waits for the device to reboot.
POST_CONFIRM_TIMEOUT = 0.5
#: Retransmits on timeout or a CRC NAK.
MAX_RETRIES = 3

#: Write granularity for _write_paced().
#:
#: One frame goes out in one write. The 12 ms inter-chunk pause existed for the
#: old ping-pong DMA firmware, whose receiver stopped at every 64-byte boundary;
#: QBOOT now runs a CIRCULAR 1024-byte DMA, so the receive path never pauses and
#: the pause is pure dead time - 4 x 12 ms per 270-byte DATA frame, which would
#: cancel out the entire gain from CHUNK=256.
_WRITE_CHUNK = 1024
_WRITE_DELAY = 0.012

#: Printed by qboot_qiap_run() immediately before the reset that follows a
#: commit. Seeing it means the device already has the new image and is leaving.
#: Both spellings are accepted because the QBOOT banner was renamed; keeping
#: the old one means a host built from this tree still works with an older
#: QBOOT. tools/verify_fixes.py checks these against the firmware source.
_MARK_COMMITS = (b"[QIAP] flash complete", b"[QIAP] success")


def _has_commit_mark(raw):
    """True when `raw` carries QBOOT's pre-reset commit announcement."""
    return any(mark in raw for mark in _MARK_COMMITS)


#: How long end() listens for that announcement before deciding the device is
#: waiting for a SIGN frame. The print happens microseconds after the END ACK,
#: so anything beyond a round trip is waste; 1 s covers a slow USB bridge.
_COMMIT_PROBE_TIMEOUT = 1.0

#: Cap on the raw receive log. Long enough for a boot sequence plus several
#: banners, short enough that the scan below stays free.
_RAW_LIMIT = 8192


class UpgradeError(Exception):
    """A hard failure: the session must stop and the operator must intervene."""


class UpgradeCancelled(Exception):
    """The operator cancelled; the board is left recoverable (QIAP flag set)."""


class PortOpenError(UpgradeError):
    """The serial port could not be opened or configured.

    Separate from UpgradeError so the UI can offer port-specific help instead of
    a generic "upgrade failed". `kind` is one of "busy", "not_ready",
    "not_found", "other".
    """

    def __init__(self, message, kind="other", port=None):
        UpgradeError.__init__(self, message)
        self.kind = kind
        self.port = port


#: Windows/Posix error fingerprints -> a coarse cause. Matched against the text
#: of the exception because pyserial rewraps the OS error into a message string
#: and drops the original errno in the process.
_OPEN_ERROR_PATTERNS = (
    # another process holds the port with exclusive access
    ("busy", ("access is denied", "拒绝访问", "permission denied",
              "permissionerror(5", "errno 5)", "cannot open port")),
    # Windows ERROR_GEN_FAILURE: the device answers the open but refuses
    # SetCommState. On a composite debug probe (WCH-Link, J-Link, CMSIS-DAP)
    # this is what an active debug session looks like from the host side.
    ("not_ready", ("permissionerror(13", "not functioning",
                   "没有发挥作用", "gen_failure", "cannot configure port",
                   "semaphore timeout", "信号灯超时")),
    ("not_found", ("filenotfounderror", "could not find", "找不到",
                   "no such file", "系统找不到指定的文件")),
)


def classify_open_error(exc):
    """Return 'busy' | 'not_ready' | 'not_found' | 'other' for a pyserial error."""
    text = str(exc).lower()
    for kind, needles in _OPEN_ERROR_PATTERNS:
        for n in needles:
            if n in text:
                return kind
    return "other"


def describe_open_error(port, kind, exc):
    """An operator-facing message with concrete next steps.

    The port number in the Windows device tree says nothing about whether the
    port is usable: a WCH-Link with a live Keil debug session shows up as
    "status OK" and still fails every SetCommState. So the advice has to name
    the debugger, not just "close the other program".
    """
    detail = str(exc)
    if len(detail) > 150:
        detail = detail[:147] + "..."
    key = {
        "busy": "sess.port.busy",
        "not_ready": "sess.port.not_ready",
        "not_found": "sess.port.not_found",
    }.get(kind, "sess.port.other")
    return i18n.t(key, port=port, detail=detail)


class Progress(object):
    """Phase names passed to the on_progress callback."""
    DETECT = "detect"
    ENTER = "enter"
    WRITE = "write"
    END = "end"
    SIGN = "sign"
    VERIFY = "verify"
    DONE = "done"


class Result(object):
    """What run() returns on success."""

    def __init__(self, stamp, elapsed, bytes_written, signed,
                 write_elapsed=None):
        self.stamp = stamp
        #: Wall time for the whole session, detection and signature included.
        self.elapsed = elapsed
        self.bytes_written = bytes_written
        self.signed = signed
        #: Time actually spent streaming DATA. This is the only interval a
        #: throughput figure may use: dividing by `elapsed` charges port
        #: detection, banner drains and the 21 s signature window to the link,
        #: which made a 7.8 KiB/s transfer report as "0.5 KiB/s".
        self.write_elapsed = write_elapsed if write_elapsed is not None else elapsed

    @property
    def speed(self):
        """KiB/s over the DATA phase only."""
        return (self.bytes_written / 1024.0) / max(self.write_elapsed, 1e-6)

    def __str__(self):
        return "%s (%.1f KiB/s, %.1f s write, %.1f s total, %d B%s)" % (
            self.stamp, self.speed, self.write_elapsed, self.elapsed,
            self.bytes_written, ", signed" if self.signed else ", unsigned")


def _noop(*_a, **_k):
    pass


def parse_app_reset_command(text, hex_str):
    """Resolve the APP -> QBOOT trigger into the bytes written on the wire.

    text     : text command; sent as ``text + "\\n"`` (default "swqboot"). This
               is what the Quilla APP shell understands.
    hex_str  : when non-empty, raw hex bytes (space / comma / colon separated,
               e.g. "06 F0 5A 51 42 4F 54 80"). Takes precedence over *text*
               and is sent verbatim - no newline appended, because the target is
               an APP that does not run the Quilla shell and may speak a binary
               protocol where a stray CR/LF would be data rather than a frame
               terminator.

    Returns ``(is_text, payload)``. Raises ``ValueError`` on malformed hex.
    """
    h = (hex_str or "").strip()
    if h:
        cleaned = (h.replace(":", "").replace(",", "").replace(" ", "")
                   .replace("\t", ""))
        try:
            data = bytes.fromhex(cleaned)
        except ValueError:
            raise ValueError(
                "malformed hex reset command %r: use pairs of hex digits, "
                "e.g. '06 F0 5A 51 42 4F 54 80'" % hex_str)
        if not data:
            raise ValueError("hex reset command is empty")
        return (False, data)
    t = (text or "swqboot").strip() or "swqboot"
    return (True, (t + "\n").encode("utf-8"))


class Session(object):
    """One upgrade run. Not reusable: construct a new one per attempt.

    Callbacks are invoked from the thread that calls run(); a GUI must marshal
    them to its own thread (the bundled Tk UI pushes them onto a queue).

    on_log(level, text)      level in {"info", "ok", "warn", "err"}
    on_progress(phase, done, total)   done/total are bytes during WRITE,
                                      else 0/0 for phase-only updates
    cancel() -> bool         polled between frames and inside read loops
    """

    def __init__(self, port, baud=115200, key_path=None,
                 on_log=None, on_progress=None, cancel=None,
                 banner_timeout=15.0,
                 reset_cmd="swqboot", reset_cmd_hex=None):
        self.port = port
        self.baud = int(baud)
        self.key_path = key_path
        self.on_log = on_log or _noop
        self.on_progress = on_progress or _noop
        self.cancel = cancel or (lambda: False)
        self.banner_timeout = banner_timeout

        # APP -> QBOOT trigger. Defaults to the Quilla APP-shell command
        # "swqboot"; a raw hex command can be supplied for APPs that do not run
        # that shell. _app_reset_desc is the human-readable form for logs.
        self._app_reset_is_text, self._app_reset_bytes = parse_app_reset_command(
            reset_cmd, reset_cmd_hex)
        if reset_cmd_hex and reset_cmd_hex.strip():
            self._app_reset_desc = "%s (%d B)" % (
                reset_cmd_hex.strip(), len(self._app_reset_bytes))
        else:
            self._app_reset_desc = reset_cmd or "swqboot"

        self.ser = None
        self.seed = None
        self.public_key = None
        #: Set when a read/write failed because the device left the bus (reset,
        #: replug). Cleared on every successful re-open.
        self.port_lost = False

        #: One parser for the whole session. Creating it per _recv_frame() threw
        #: away a partially received frame on every call, so a frame that
        #: straddled two reads could never be reassembled.
        self._parser = P.FrameParser()
        #: Raw byte log of everything read since the last reset_rx_log(). Text
        #: banners and ACK frames share the port; the parser consumes the frames
        #: and used to discard the rest, which is how the one-shot commit and
        #: boot banners vanished while the host was waiting for an ACK.
        self._raw = bytearray()
        #: The boot stamp this run must see, taken from the image being written.
        self.expected_stamp = None
        #: True once QBOOT-side evidence proves the image is committed: the
        #: post-commit ACK, the pre-reset announcement, or a matching boot
        #: stamp. When set, a SIGN frame would go nowhere.
        self.committed_at_end = False
        #: Short description of the evidence behind the completion verdict, for
        #: the log and the success dialog. None until one is seen.
        self.completion_code = None
        #: True when the verdict rests only on a port lost to the reset. The
        #: reset does follow done=1, but a cable pull looks identical, so this
        #: is reported as a weak verdict instead of a clean one.
        self.completion_is_weak = False

        # Partition bounds: APP_START is MCU-independent, APP_END is fetched
        # from the device (it depends on SOC_FLASH_END) and must never be
        # hard-coded here.
        self.app_start = P.APP_START
        self.app_end = 0x0801FFFF          # PY32F040xB fallback, overwritten by pinfo
        self.app_size = self.app_end - self.app_start + 1
        self.max_image_size = None         # None => host does not enforce a ceiling

    # ---------------------------------------------------------------- plumbing
    def _log(self, level, text):
        self.on_log(level, text)

    def _check_cancel(self):
        if self.cancel():
            raise UpgradeCancelled()

    def _serial_open(self, reset_buffers=True):
        """Open and configure the port. Raises PortOpenError on failure.

        A composite probe that just came out of debug mode often fails the very
        first SetCommState and then works. Two quick retries cost under a second
        and avoid sending the operator to replug the cable for nothing.
        """
        try:
            import serial
        except ImportError:
            raise UpgradeError("pyserial is not installed; run: pip install pyserial")

        last = None
        kind = "other"
        delays = (0.15, 0.5)
        for attempt in range(len(delays) + 1):
            try:
                self.ser = serial.Serial(self.port, self.baud, timeout=0.1,
                                         dsrdtr=False, rtscts=False)
                last = None
                break
            except Exception as e:
                last = e
                kind = classify_open_error(e)
                if kind != "not_ready" or attempt == len(delays):
                    break
                self._log("warn", i18n.t("sess.port_not_configurable",
                                         port=self.port, kind=kind,
                                         delay=delays[attempt]))
                time.sleep(delays[attempt])

        if last is not None:
            self.ser = None
            raise PortOpenError(describe_open_error(self.port, kind, last),
                                kind=kind, port=self.port)

        self.port_lost = False
        # Force DTR/RTS low: some USB-UART boards reset the MCU on a line
        # transition, which would kick the board out of the upgrade-idle state.
        try:
            self.ser.dtr = False
            self.ser.rts = False
        except Exception:
            pass
        if reset_buffers:
            try:
                self._flush_input()
                self.ser.reset_output_buffer()
            except Exception:
                pass
        time.sleep(0.1)

    def _open(self):
        self._serial_open()
        self._log("info", i18n.t("sess.opened", port=self.port, baud=self.baud))

    def port_present(self):
        """True when the OS still enumerates this port."""
        try:
            from serial.tools import list_ports
            return any(p.device == self.port for p in list_ports.comports())
        except Exception:
            return False

    def reopen(self, timeout=20.0):
        """Close and re-open the port, waiting for it to come back.

        Needed because 'swqboot' resets the MCU, and on a composite probe
        (WCH-Link, and J-Link with a CDC channel) the reset can pull the whole
        USB device off the bus: the COM port disappears and every call on the
        old handle raises. A plain USB-UART never shows this, so the wait must
        also succeed quickly when nothing was lost.
        """
        self.close()
        t0 = time.time()
        announced = False
        while time.time() - t0 < timeout:
            self._check_cancel()
            if self.port_present():
                try:
                    self._serial_open(reset_buffers=False)
                    self._log("info", i18n.t("sess.reopen_back", port=self.port,
                                             elapsed=time.time() - t0))
                    return True
                except PortOpenError:
                    pass
            if not announced:
                announced = True
                self._log("info", i18n.t("sess.reopen_wait", port=self.port,
                                         timeout=timeout))
            time.sleep(0.25)
        self._log("err", i18n.t("sess.reopen_fail", port=self.port, timeout=timeout))
        return False

    def close(self):
        """Release the port (idempotent, safe on every exit path)."""
        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:
            pass
        self.ser = None

    # ------------------------------------------------------------------- I/O
    def _flush_input(self):
        """Drop whatever is buffered; a handle that just died is not an error."""
        try:
            if self.ser is not None:
                self.ser.reset_input_buffer()
        except Exception:
            self.port_lost = True

    def _read_some(self):
        """Read what is buffered right now; b'' when idle or when the port died.

        Every read goes through here. A reset can remove the USB CDC device
        while a read loop is running, and pyserial then raises on in_waiting
        itself (ClearCommError). Letting that escape would turn a recoverable
        "the board just reset" into a stack trace, so it is flattened into
        "no data" and remembered in self.port_lost.
        """
        if self.ser is None:
            self.port_lost = True
            return b""
        try:
            n = self.ser.in_waiting
            if n:
                return self.ser.read(n)
        except Exception:
            self.port_lost = True
            time.sleep(0.05)
        return b""

    def _write_bytes(self, data):
        """Write raw bytes; returns False if the port is gone."""
        if self.ser is None:
            self.port_lost = True
            return False
        try:
            self.ser.write(data)
            self.ser.flush()
            return True
        except Exception as e:
            self.port_lost = True
            self._log("warn", i18n.t("sess.write_failed", err=e))
            return False

    def _drain_text(self, timeout=2.0, idle=None, first=None):
        """Collect whatever text arrives in `timeout` seconds (banner / echo).

        With `idle`, return as soon as `idle` seconds pass with nothing new
        after at least one byte arrived. A shell reply is a burst: `part` and
        `pinfo` answer in a few milliseconds, so spinning the full window for
        them costs two seconds per probe and collects nothing.

        With `first`, return b"" when not a single byte shows up within that
        many seconds. A board already sitting in the APP shell printed its
        banner long ago, so the window would otherwise idle for its full
        length before the probe even starts. Once the first byte does arrive
        the full `timeout` applies -- a booting board is never cut short.
        """
        buf = b""
        t0 = time.time()
        last = t0
        while time.time() - t0 < timeout:
            self._check_cancel()
            chunk = self._read_some()
            if chunk:
                buf += chunk
                last = time.time()
            elif buf and idle is not None and (time.time() - last) >= idle:
                return buf
            elif not buf and first is not None and (time.time() - t0) >= first:
                return buf
            else:
                time.sleep(0.02)
        return buf

    def _query_line(self, cmd, timeout=2.0, idle=0.35):
        """Send one shell command line and return everything read back.

        In the upgrade-idle state these bytes are swallowed by the frame parser
        with no echo, which is exactly what distinguishes idle from the shells.
        """
        self._flush_input()
        self._write_bytes(cmd)
        return self._drain_text(timeout, idle=idle)

    def _wait_text(self, needle, timeout=3.0):
        """Return True when `needle` shows up within `timeout` seconds."""
        t0 = time.time()
        acc = b""
        while time.time() - t0 < timeout:
            self._check_cancel()
            acc += self._read_some()
            if needle in acc:
                return True
            time.sleep(0.02)
        return False

    def reset_rx_log(self):
        """Forget everything read so far.

        Called when a phase starts, so a stale banner from the previous firmware
        cannot be mistaken for evidence about this one.
        """
        self._raw = bytearray()
        self._parser = P.FrameParser()

    def _feed_raw(self, chunk):
        """Append to the raw receive log, keeping it bounded."""
        if not chunk:
            return
        self._raw += chunk
        excess = len(self._raw) - _RAW_LIMIT
        if excess > 0:
            del self._raw[:excess]

    def _find_stamp(self, expected=None):
        """Return the boot stamp found in the raw log, or None.

        `expected` is the stamp extracted from the image being written. When it
        is known, a `[QAPP]` line that does not match is discarded and the scan
        continues: a leftover banner from the old firmware (or a device that
        refused the write and restarted the old APP) must not be reported as a
        successful upgrade.
        """
        while True:
            i = self._raw.find(BOOT_STAMP_MARKER)
            if i < 0:
                return None
            end = i
            limit = min(len(self._raw), i + 96)
            while end < limit and self._raw[end] not in (0x0D, 0x0A):
                end += 1
            text = bytes(self._raw[i:end]).decode("ascii", "replace")
            if expected is None or text.strip() == expected.strip():
                return text
            self._log("debug", i18n.t("sess.stamp_mismatch", stamp=text,
                                      expected=expected))
            del self._raw[:end]
            if not self._raw:
                return None

    def _await(self, timeout, want_frame=True, watch_commit=False,
               watch_stamp=False):
        """Pump the port for up to `timeout` seconds.

        Returns (kind, value) where kind is one of:

            "frame"   value = (cmd, payload)
            "commit"  value = None    device announced the QIAP commit
            "stamp"   value = text    the new APP printed its boot stamp
            None      value = None    timeout, cancel, or port gone

        One pump feeds both the frame parser and the raw log, so a banner that
        arrives while an ACK is awaited is preserved instead of consumed.

        Markers already sitting in the raw log are honoured before any read.
        That matters when an ACK and a banner arrive in the same USB packet: the
        ACK wins the frame race, the call returns, and the banner is still in
        the log for whoever looks next - no second byte has to arrive for it to
        be noticed.
        """
        if watch_commit and _has_commit_mark(self._raw):
            return "commit", None
        if watch_stamp:
            stamp = self._find_stamp(self.expected_stamp)
            if stamp is not None:
                return "stamp", stamp

        t0 = time.time()
        while time.time() - t0 < timeout:
            self._check_cancel()
            chunk = self._read_some()
            if chunk:
                self._feed_raw(chunk)
                if want_frame:
                    for b in chunk:
                        frame = self._parser.feed(b)
                        if frame is not None:
                            return "frame", frame
                if watch_commit and _has_commit_mark(self._raw):
                    return "commit", None
                if watch_stamp:
                    stamp = self._find_stamp(self.expected_stamp)
                    if stamp is not None:
                        return "stamp", stamp
                continue
            if self.port_lost:
                # Nothing more can arrive on this handle; a reset on a composite
                # probe looks exactly like this and the caller decides whether
                # to re-open.
                return None, None
            time.sleep(0.004)
        return None, None

    def _recv_frame(self, timeout=ACK_TIMEOUT):
        """Return (cmd, payload) for the next valid frame, or None on timeout.

        Bails out as soon as the port is detected gone (self.port_lost): waiting
        the full `timeout` on a dead handle only wastes time, because a reset on
        a composite probe drops the port for a moment and no frame will ever
        arrive on the old handle.
        """
        kind, value = self._await(timeout)
        return value if kind == "frame" else None

    def _write_paced(self, data, chunk=_WRITE_CHUNK, delay=_WRITE_DELAY):
        """Write the frame in one go, splitting only past `chunk` bytes.

        A DATA frame is 270 bytes (8 B addresses + 256 B page) and a SIGN frame
        is 70; both fit one write, so neither ever hits the delay. The split
        survives for the pathological case of a future frame larger than the
        driver buffer, where a pause is still cheaper than a truncated write.
        """
        n = len(data)
        for i in range(0, n, chunk):
            if not self._write_bytes(data[i:i + chunk]):
                raise UpgradeError(i18n.t("sess.write_broke", port=self.port))
            if i + chunk < n:
                time.sleep(delay)

    def _send_frame(self, cmd, payload):
        self._write_paced(P.build_frame(cmd, payload))

    def _transact(self, cmd, payload, ack_cmd, retries=MAX_RETRIES,
                  timeout=ACK_TIMEOUT):
        """Send a command and wait for its ACK; return the ACK payload.

        A CRC NAK (reason 0x03) is the only retransmittable rejection; every
        other reason is a parameter or flash fault, so retrying just wastes
        time and hides the real cause.
        """
        last = None
        for attempt in range(1, retries + 1):
            self._check_cancel()
            self._send_frame(cmd, payload)
            resp = self._recv_frame(timeout=timeout)
            if resp is None:
                last = UpgradeError(
                    i18n.t("sess.ack_timeout", cmd=ack_cmd, attempt=attempt,
                           retries=retries))
                self._log("warn", str(last))
                continue
            rcmd, rpayload = resp
            if rcmd == ack_cmd:
                return rpayload
            if rcmd in P.NAK_CMDS:
                reason = rpayload[0] if rpayload else 0
                txt = P.REASON.get(reason, "unknown(0x%02X)" % reason)
                if reason == P.REASON_CRC:
                    last = UpgradeError(
                        i18n.t("sess.nak_retransmit", cmd=rcmd, reason=reason, txt=txt))
                    self._log("warn", str(last))
                    continue
                raise UpgradeError(i18n.t("sess.nak_hard", cmd=rcmd, reason=reason, txt=txt))
            last = UpgradeError(i18n.t("sess.unexpected_resp", cmd=rcmd, ack=ack_cmd))
            self._log("warn", str(last))
        raise last or UpgradeError("transaction failed")

    # ------------------------------------------------------- state detection
    def fetch_partition(self):
        """Ask the QBOOT shell for the partition layout (`pinfo`).

        Only works in the QBOOT shell, not in the upgrade raw sink. On failure
        the host-side ceiling is skipped and the device's ADDR NAK(0x01) is the
        authority - safer than assuming a PY32F040xB value on a GD32.
        """
        self._flush_input()
        out = self._query_line(b"pinfo\n", timeout=2.0)
        txt = out.decode("latin1", errors="replace")
        import re
        m_s = re.search(r"APP_START=0x([0-9A-Fa-f]+)", txt)
        m_e = re.search(r"APP_END=0x([0-9A-Fa-f]+)", txt)
        if m_s and m_e:
            self.app_start = int(m_s.group(1), 16)
            self.app_end = int(m_e.group(1), 16)
            self.app_size = self.app_end - self.app_start + 1
            self.max_image_size = self.app_size
            self._log("info", i18n.t("sess.partition_ok", start=self.app_start,
                                     end=self.app_end, size=self.app_size))
            return True
        self._log("warn", i18n.t("sess.partition_fail"))
        return False

    def ensure_upgrade_mode(self):
        """Detect the board state and land in the upgrade state machine."""
        self._log("info", i18n.t("sess.reading_banner"))
        # A board already running the APP printed its banner seconds ago, so
        # the full window would sit idle and collect nothing -- four seconds
        # on the path every ordinary upgrade takes. Probe for a quiet line
        # first. A board that really is booting shows its first byte within
        # milliseconds and then still gets the whole window, so the
        # upgrade-idle and just-powered-on cases are unchanged. The idle gap
        # stays at a full second: a booting board can pause between the boot
        # banner and the shell prompt, and cutting that off would lose the
        # "enter upgrade mode" line that identifies the upgrade-idle state.
        banner = self._drain_text(4.0, idle=1.0, first=0.5)
        self._log("debug", "banner=%r" % banner)
        text0 = banner.decode("latin1", errors="replace")

        if "enter upgrade mode" in text0:
            self._log("info", i18n.t("sess.already_upgrade"))
            self._flush_input()
            self.enter()
            return

        self._flush_input()
        part = self._query_line(b"part\n", timeout=2.0)
        self._log("debug", "part=%r" % part)
        part_txt = part.decode("latin1", errors="replace")
        in_qboot = ("qboot" in part_txt) or ("[BOOT]" in text0)

        if not in_qboot:
            # Two very different states answer nothing to 'part':
            #   D. upgrade-idle, raw sink installed -> a binary ENTER still
            #      reaches the state machine, so try that first;
            #   C. APP shell -> it answers 'part' with app1, which is checked
            #      below before wasting three 2 s ACK timeouts on an ENTER that
            #      cannot possibly be parsed by a text shell.
            if part_txt.strip():
                self._log("info", i18n.t("sess.app_shell_reset",
                                         cmd=self._app_reset_desc))
                self._reset_into_qboot()
            else:
                self._log("info", i18n.t("sess.not_qboot_try_enter"))
                try:
                    self.enter()
                    return
                except UpgradeCancelled:
                    raise
                except Exception as e:
                    self._log("warn", i18n.t("sess.direct_enter_failed", err=e))

                self._reset_into_qboot()

        self.fetch_partition()

        for attempt in range(1, 4):
            self._check_cancel()
            if self.port_lost and not self.reopen():
                raise UpgradeError(i18n.t("sess.err_port_gone_qiap", port=self.port))
            self._flush_input()
            if not self._write_bytes(b"qiap\n"):
                raise UpgradeError(i18n.t("sess.qiap_write_fail", port=self.port))
            if self._wait_text(b"enter upgrade mode", timeout=3.0):
                self._log("info", i18n.t("sess.entered_upgrade", n=attempt))
                self._flush_input()
                self.enter()
                return
            self._log("warn", i18n.t("sess.qiap_attempt", n=attempt))

        raise UpgradeError(i18n.t("sess.err_cannot_enter", banner=banner, part=part))

    def _clear_device_line(self):
        """Terminate whatever the device shell has buffered but not yet parsed.

        A binary ENTER frame is meaningless to a text shell: its payload bytes
        (``app_start`` 0x08007000 contributes 0x70 = 'p', followed by the
        "QULLOTA1" unlock key) are printable, so they land in the shell's
        128-byte line buffer with no terminator. A "swqboot\\n" sent afterwards
        is glued behind that garbage, never matches a command name, and the
        board quietly stays in the APP. The symptom looks like "swqboot does
        nothing", not like a parsing problem, which is what makes it expensive
        to find.

        pyserial's reset_input_buffer() only empties the host-side queue; the
        device's line buffer is cleared by an actual CR or LF arriving on the
        wire, so this has to be written, not flushed.
        """
        self._flush_input()
        self._write_bytes(b"\r\n")
        time.sleep(0.1)

    def _reset_into_qboot(self):
        """Issue the APP -> QBOOT trigger, then confirm we landed in QBOOT.

        The trigger is configurable (see parse_app_reset_command): the default
        text command "swqboot" targets the Quilla APP shell, and a raw hex
        command (e.g. "06 F0 5A 51 42 4F 54 80") targets an APP that does not
        run that shell.

        The reset is the part that used to be wrong here: on a composite debug
        probe (WCH-Link, J-Link with a CDC channel) the MCU reset pulls the whole
        USB device off the bus. The COM port vanishes for a couple of seconds,
        then re-enumerates under the same name. The old code spent 6 s waiting
        for a "[BOOT]" banner on a handle that was already dead, so it could
        never see one - that is why every run ended in "qiap did not enter
        upgrade mode" even though the reset had worked.

        So: write the command, notice the device is gone, wait for it to come
        back, then ask the board which shell it is in. 'part' survives the
        re-enumeration; a banner does not.
        """
        desc = self._app_reset_desc
        for attempt in (1, 2):
            self._check_cancel()
            self._log("info", i18n.t("sess.swqboot_attempt", n=attempt, cmd=desc))
            # A failed binary ENTER may have left an unterminated line in a text
            # shell, and the shell would swallow the command as part of it. That
            # clear is meaningless (and potentially harmful) for a raw hex
            # trigger aimed at a binary protocol, so only do it in text mode.
            if self._app_reset_is_text:
                self._clear_device_line()
            wrote = self._write_bytes(self._app_reset_bytes)

            # Give the MCU time to actually reset, then look at the port. The
            # read is what detects a dead handle, so it has to be attempted
            # explicitly rather than inferred from the write.
            time.sleep(0.6)
            self._read_some()

            if self.port_lost or not wrote:
                self._log("info", i18n.t("sess.port_dropped_wait", port=self.port,
                                         timeout=20.0))
                if not self.reopen(timeout=20.0):
                    raise PortOpenError(
                        i18n.t("sess.err_swqboot_fail", cmd=desc), kind="not_found",
                        port=self.port)

            banner = self._drain_text(1.5)
            if banner:
                self._log("info", i18n.t("sess.post_reset_output", data=banner))

            part = self._query_line(b"part\n", timeout=2.0)
            txt = part.decode("latin1", errors="replace")
            self._log("info", i18n.t("sess.post_swqboot_part", data=part))

            # 'qboot' wins over 'app1': a QBOOT shell may legitimately mention
            # the active partition name in its answer, and mistaking that for
            # "still in the APP" would send us into a pointless second reset.
            if "qboot" in txt:
                self._log("ok", i18n.t("sess.board_qboot"))
                return
            if "app1" in txt:
                self._log("warn", i18n.t("sess.still_app", n=attempt, cmd=desc))
                continue
            if not txt.strip() and not banner:
                self._log("warn", i18n.t("sess.no_echo_assume"))
            else:
                self._log("ok", i18n.t("sess.board_qboot"))
            return

        raise UpgradeError(i18n.t("sess.err_swqboot_fail", cmd=desc))

    # -------------------------------------------------------------- commands
    def enter(self):
        payload = struct.pack("<I", self.app_start) + P.UNLOCK_KEY
        self._log("info", i18n.t("sess.enter_sent", start=self.app_start))
        self.on_progress(Progress.ENTER, 0, 0)
        r = self._transact(P.CMD_ENTER, payload, P.ACK_ENTER)
        status = r[0] if r else 0
        if status != 0:
            raise UpgradeError(i18n.t("sess.err_enter_status", status=status))
        self._log("ok", i18n.t("sess.enter_accepted"))

    def send_data(self, data):
        """Stream the image. Returns (total_len, chained_crc16)."""
        total_len = 0
        total_crc = 0
        n = len(data)
        nchunks = (n + P.CHUNK - 1) // P.CHUNK
        self.on_progress(Progress.WRITE, 0, n)

        for i in range(nchunks):
            self._check_cancel()
            start_addr = self.app_start + i * P.CHUNK
            chunk = data[i * P.CHUNK:(i + 1) * P.CHUNK]
            end_addr = start_addr + len(chunk) - 1
            payload = struct.pack("<II", start_addr, end_addr) + chunk
            r = self._transact(P.CMD_DATA, payload, P.ACK_DATA)
            echoed = struct.unpack("<I", r[:4])[0]
            if echoed != start_addr:
                # Structural misalignment: a whole frame was lost, so resending
                # this chunk cannot self-heal. Fail cleanly instead of looping.
                raise UpgradeError(
                    i18n.t("sess.err_data_mismatch", i=i, exp=start_addr, got=echoed))
            total_len += len(chunk)
            total_crc = P.crc16(chunk, total_crc)     # chained, matches the device
            self.on_progress(Progress.WRITE, total_len, n)

        return total_len, total_crc

    def end(self, total_len, total_crc):
        payload = struct.pack("<I", total_len) + struct.pack("<H", total_crc)
        self._log("info", i18n.t("sess.end_sent", length=total_len, crc=total_crc))
        self.on_progress(Progress.END, 0, 0)
        r = self._transact(P.CMD_END, payload, P.ACK_END)
        status = r[0] if r else 0
        if status != 0:
            raise UpgradeError(i18n.t("sess.err_end_status", status=status))
        self._log("ok", i18n.t("sess.end_accepted"))

        # A device without a provisioned public key commits right here: the END
        # handler writes the flag, the QIAP loop prints the commit announcement
        # and resets. Listen for it, otherwise the caller sends a SIGN frame
        # into an APP that does not speak QIAP and then waits SIGN_TIMEOUT for
        # an ACK that cannot exist.
        kind, _ = self._await(_COMMIT_PROBE_TIMEOUT, want_frame=False,
                              watch_commit=True)
        if kind == "commit":
            # QBOOT_CHECK: END committed (quilla-qboot-secure.c reports no
            # public key), and the announcement is printed after done=1.
            self.committed_at_end = True
            self.completion_code = "ACK_END 0x83 + commit announcement"
            self._log("info", i18n.t("sess.end_committed"))

    def sign(self, image):
        """Send the Ed25519 signature over (len || SHA-256(image)).

        One attempt only: the device spends ~21 s verifying inline, so a
        retransmit would make it verify twice and desync the state machine.

        Returns the boot stamp when the wait happened to observe it, else None.
        ACK 0x84 is the completion code for the keyed variants (SEALED / SECURE):
        commit_app() runs before send_ack(), so receiving it means the image is
        committed. The commit announcement and a matching boot stamp are watched
        in the same window, so a lost ACK on a composite probe still leaves two
        independent ways to confirm the commit. Only an explicit NAK is a hard
        reject. Every positive branch records completion evidence; run() then
        decides the verdict before the device finishes rebooting.
        """
        if self.committed_at_end:
            self._log("info", i18n.t("sess.sign_skipped_committed"))
            return None
        if self.port_lost:
            # The END probe already saw the device leave. Sending now would
            # raise "port went away mid-write" and hide a good upgrade.
            self._log("info", i18n.t("sess.sign_skipped_gone"))
            return None

        sig = ed25519.sign_descriptor(self.seed, image.size, image.sha256)
        self._log("info", i18n.t("sess.sign_sent"))
        self.on_progress(Progress.SIGN, 0, 0)
        self._send_frame(P.CMD_SIGN, sig)

        kind, value = self._await(SIGN_TIMEOUT, watch_commit=True,
                                  watch_stamp=True)
        if kind == "stamp":
            # The device already committed, reset and booted the new image.
            # This is stronger than an ACK, so it must not be discarded: the
            # old code returned here without recording any completion evidence
            # and run() then reported a hard failure on a finished upgrade.
            self.committed_at_end = True
            self.completion_code = "matching [QAPP] boot stamp"
            self._log("ok", i18n.t("sess.stamp_found", stamp=value))
            return value
        if kind == "commit":
            # ACK 0x84 was lost (composite probe) but done=1 was announced.
            self.committed_at_end = True
            self.completion_code = "commit announcement"
            self._log("info", i18n.t("sess.end_committed"))
            return None
        if kind is None:
            if self.port_lost:
                # WEAK evidence: the reset follows done=1, but a cable pull
                # looks the same. Keep the verdict, flag it for the operator.
                self.committed_at_end = True
                self.completion_code = "reset (port lost, weak evidence)"
                self.completion_is_weak = True
                self._log("warn", i18n.t("sess.sign_no_ack_reset"))
            else:
                self._log("warn", i18n.t("sess.sign_no_ack_alive", timeout=SIGN_TIMEOUT))
            return None

        rcmd, rpayload = value
        if rcmd == P.ACK_SIGN:
            status = rpayload[0] if rpayload else 0
            if status != 0:
                raise UpgradeError(i18n.t("sess.err_sign_status", status=status))
            # 0x84 is sent only after commit_app(): this is the completion code.
            self.committed_at_end = True
            self.completion_code = "ACK_SIGN 0x84"
            self._log("ok", i18n.t("sess.sign_accepted"))
            return None
        if rcmd in P.NAK_CMDS:
            reason = rpayload[0] if rpayload else 0
            txt = P.REASON.get(reason, "unknown(0x%02X)" % reason)
            raise UpgradeError(i18n.t("sess.err_sign_rejected", cmd=rcmd,
                                      reason=reason, txt=txt))
        raise UpgradeError(i18n.t("sess.sign_unexpected", cmd=rcmd))

    def wait_app_stamp(self, timeout=APP_STAMP_TIMEOUT, allow_reopen=True,
                       quiet=False):
        """Look for the new APP's boot stamp. Not a success criterion.

        QIAP commits before it ACKs, so run() decides completion on QBOOT-side
        evidence and never calls this as a gate. It remains available for
        callers that explicitly want to watch the new firmware boot; the normal
        path only uses _post_confirm(), which swallows every failure.

        A stamp already sitting in the raw log is returned immediately. SIGN
        makes the device reset, so on a composite probe the port may be gone -
        re-open once if the handle dies and `allow_reopen` is set. The short
        non-fatal peek disables that: a 20 s re-open would defeat the point of
        reporting completion before the reboot. `quiet` suppresses the phase
        and tick logs for that same peek - completion has already been
        announced, so a late VERIFY phase would make the UI flicker backwards.
        """
        if not quiet:
            self.on_progress(Progress.VERIFY, 0, 0)

        stamp = self._find_stamp(self.expected_stamp)
        if stamp is not None:
            self._log("ok", i18n.t("sess.stamp_found", stamp=stamp))
            return stamp

        t0 = time.time()
        last_tick = -1
        reopened = False
        while time.time() - t0 < timeout:
            self._check_cancel()
            chunk = self._read_some()
            self._feed_raw(chunk)
            stamp = self._find_stamp(self.expected_stamp)
            if stamp is not None:
                self._log("ok", i18n.t("sess.stamp_found", stamp=stamp))
                return stamp
            if self.port_lost and not reopened and allow_reopen:
                reopened = True
                self._log("info", i18n.t("sess.port_dropped_stamp"))
                if not self.reopen(timeout=20.0):
                    raise PortOpenError(
                        i18n.t("sess.err_stamp_timeout", timeout=timeout),
                        kind="not_found", port=self.port)
                continue
            elapsed = time.time() - t0
            tick = int(elapsed // 5.0)
            if not quiet and tick != last_tick:
                last_tick = tick
                self._log("info", i18n.t("sess.wait_stamp_tick", elapsed=elapsed,
                                         timeout=timeout))
            time.sleep(0.02)
        raise UpgradeError(i18n.t("sess.err_stamp_timeout", timeout=timeout))

    def _post_confirm(self, ack_text):
        """Non-blocking peek for a boot stamp that arrived with the completion.

        The verdict is already made before this runs. The window is shorter than
        every boot path (CHECK ~0.1 s, SEALED ~0.6 s, SECURE ~20 s), so this
        never waits for the device to reboot: a stamp is recorded when it
        happens to share the USB packet with the completion code, and its
        absence is informational, never a warning and never a failure.
        """
        try:
            return self.wait_app_stamp(timeout=POST_CONFIRM_TIMEOUT,
                                       allow_reopen=False, quiet=True)
        except UpgradeCancelled:
            raise
        except UpgradeError:
            return i18n.t("sess.completion_no_stamp", ack=ack_text)

    # ------------------------------------------------------------------- run
    def run(self, image):
        """Full upgrade. `image` is an image.FirmwareImage."""
        if self.key_path:
            self.seed = ed25519.load_seed_hex(self.key_path)
            self.public_key = ed25519.pubkey_from_seed(self.seed)
            self._log("info", i18n.t("sess.signing_key", path=self.key_path,
                                     pk=self.public_key.hex()[:16]))
        else:
            self._log("warn", i18n.t("sess.no_key"))

        t_start = time.time()
        self._open()
        try:
            self.on_progress(Progress.DETECT, 0, 0)
            self.ensure_upgrade_mode()
            # Detection is the slowest and least visible phase (banner drain,
            # part probe, possible swqboot re-enumeration). Log its cost so a
            # 30 s session is not mistaken for a slow link.
            self._log("info", i18n.t("sess.phase_detect",
                                     elapsed=time.time() - t_start))

            # Everything read until now belongs to the board's previous life
            # (old APP banner, QBOOT banner, shell echoes). Dropping it here is
            # what makes the stamp check meaningful: from this point on, any
            # [QAPP] line can only come from the image being written.
            self.reset_rx_log()
            self.expected_stamp = image.expected_stamp
            if self.expected_stamp:
                self._log("info", i18n.t("sess.expect_stamp",
                                         stamp=self.expected_stamp))
            else:
                self._log("warn", i18n.t("sess.no_expect_stamp"))

            if self.max_image_size is not None and image.size > self.max_image_size:
                raise UpgradeError(i18n.t("sess.err_image_above_ceiling",
                                          size=image.size, max=self.max_image_size))

            secver = image.secver
            if secver is not None:
                self._log("info", i18n.t("sess.image_secver", ver=secver))
            else:
                self._log("warn", i18n.t("sess.image_no_secver"))

            t_write = time.time()
            total_len, total_crc = self.send_data(image.data)
            write_elapsed = time.time() - t_write
            self._log("info", i18n.t("sess.phase_write", size=total_len,
                                     elapsed=write_elapsed,
                                     speed=(total_len / 1024.0)
                                     / max(write_elapsed, 1e-6)))
            self.end(total_len, total_crc)

            stamp = None
            if self.seed is not None:
                stamp = self.sign(image)
            elif not self.committed_at_end and not self.port_lost:
                # END acknowledges without committing only when the device has
                # a public key burned (doc/upgrade-flow.md section 10): no flag
                # write, no reset, and an unsigned host has nothing left to
                # send. Without a SIGN frame there is no completion code, so
                # this is still a hard failure - do not paper over it.
                raise UpgradeError(i18n.t("sess.err_key_needed"))

            # Verdict BEFORE the reset. QBOOT_CHECK commits inside END
            # (ACK 0x83 + announcement); SEALED / SECURE commit inside SIGN
            # (ACK 0x84). All three are settled here, while QBOOT is still
            # alive - the boot policy differences are entirely after the reset.
            if not (self.committed_at_end or self.port_lost):
                raise UpgradeError(i18n.t("sess.err_no_commit_ack"))
            if self.completion_code is None:
                # No ACK, no announcement, no stamp: only a port lost during
                # the END probe. Keep it as a verdict, but label it weak.
                self.completion_code = "reset (port lost, weak evidence)"
                self.completion_is_weak = True
            ack_text = self.completion_code
            self._log("ok", i18n.t("sess.ack_complete", ack=ack_text))
            if self.completion_is_weak:
                self._log("warn", i18n.t("sess.completion_weak"))

            elapsed = time.time() - t_start
            self.on_progress(Progress.DONE, image.size, image.size)
            self._log("ok", i18n.t("sess.upgrade_finished",
                                   size=total_len,
                                   write_elapsed=write_elapsed,
                                   speed=(total_len / 1024.0)
                                   / max(write_elapsed, 1e-6),
                                   elapsed=elapsed))
            # Optional, non-blocking peek. It cannot change the verdict, and
            # its 0.5 s window finishes long before any of the three boot
            # paths would print a [QAPP] banner.
            if stamp is None:
                stamp = self._post_confirm(ack_text)
            return Result(stamp, elapsed, total_len, self.seed is not None,
                          write_elapsed)
        finally:
            self.close()
