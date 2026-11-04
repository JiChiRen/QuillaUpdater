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

"""Regression checks for the three reported problems.

1. config persistence (firmware/key path remembered across launches)
2. the upgrade no longer hangs after a committed write:
   - a device without a public key commits inside END and resets, so SIGN must
     be skipped instead of waiting SIGN_TIMEOUT for an ACK that cannot exist;
   - the one-shot commit/boot banners must survive frame parsing;
   - success is the boot stamp, matched against the literal stored in the image.
3. bilingual UI: every lookup key resolves in both zh and en, and the GUI can
   switch language live.

Run:  python tools/verify_fixes.py
"""

import os
import struct
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from quilla_updater import config, i18n, protocol as P  # noqa: E402
from quilla_updater.image import FirmwareImage  # noqa: E402
from quilla_updater.session import Result, Session, UpgradeError  # noqa: E402

FAILS = []
PASSES = []


def check(name, cond, extra=""):
    if cond:
        PASSES.append(name)
    else:
        FAILS.append("%s%s" % (name, (" | " + str(extra)) if extra else ""))


# ---------------------------------------------------------------- problem 1
def test_config_persistence():
    home = tempfile.mkdtemp(prefix="quillacfg")
    os.environ["HOME"] = home
    os.environ["USERPROFILE"] = home
    cfg_dir = os.path.join(home, ".quilla_updater")
    # re-point the module at the temp home (paths are resolved at import time)
    config._CONFIG_DIR = cfg_dir
    config._CONFIG_PATH = os.path.join(cfg_dir, "config.json")

    fw = os.path.join(home, "QAPP.bin")
    key = os.path.join(home, "private.hex")
    with open(fw, "wb") as f:
        f.write(b"\x00" * 16)
    with open(key, "w") as f:
        f.write("00" * 32)

    config.update(fw_path=fw, key_path=key, use_key=True,
                  port="COM7", baud="115200", lang="en")

    cfg = config.load_config()
    check("cfg.fw_path saved", cfg["fw_path"] == fw, cfg["fw_path"])
    check("cfg.key_path saved", cfg["key_path"] == key, cfg["key_path"])
    check("cfg.use_key saved", cfg["use_key"] is True)
    check("cfg.port saved", cfg["port"] == "COM7")
    check("cfg.baud saved", cfg["baud"] == "115200")
    check("cfg.lang saved", cfg["lang"] == "en")

    cfg2 = config.load_config()
    check("cfg.defaults merge", "last_dir" in cfg2 and "key_dir" in cfg2)

    config.update(port="COM9")
    cfg3 = config.load_config()
    check("cfg.partial update keeps fw", cfg3["fw_path"] == fw)
    check("cfg.partial update applies", cfg3["port"] == "COM9")

    with open(config._CONFIG_PATH, "w") as f:
        f.write("{not json")
    try:
        cfg4 = config.load_config()
        check("cfg.corrupt tolerated", isinstance(cfg4, dict))
    except Exception as exc:  # noqa: BLE001
        check("cfg.corrupt tolerated", False, exc)


# ---------------------------------------------------------------- problem 2
class _Img(object):
    def __init__(self, size=1024):
        self.size = size
        self.sha256 = bytes(32)


def _make_session():
    sess = Session("COM0")
    sess.seed = bytes(32)
    sess._send_frame = lambda cmd, payload: None
    return sess


def _stub_await(sess, kind, value=None):
    """Script the receive pump instead of faking a serial port."""
    sess._await = lambda timeout, **kw: (kind, value)


def test_sign_missing_ack_is_not_failure():
    """Device resets and drops the port right after SIGN -> no ACK 0x84.

    The old code waited 90 s and then declared failure even though the board
    was already running the new image; sign() must now return normally and
    leave the verdict to wait_app_stamp().
    """
    sess = _make_session()
    sess.port_lost = True
    sess._send_frame = lambda cmd, payload: None
    logs = []
    sess.on_log = lambda lvl, txt: logs.append((lvl, txt))

    try:
        sess.sign(_Img())
        check("sign.no-ack does not raise", True)
    except Exception as exc:  # noqa: BLE001
        check("sign.no-ack does not raise", False, repr(exc))

    check("sign.no-ack logged as info",
          any(lvl == "info" for lvl, _ in logs), logs)


def test_sign_nak_is_failure():
    """An explicit NAK from the device must still be a hard error."""
    sess = _make_session()
    _stub_await(sess, "frame", (P.NAK_SIGN, bytes([0x08])))
    raised = False
    try:
        sess.sign(_Img())
    except UpgradeError:
        raised = True
    except Exception as exc:  # noqa: BLE001
        check("sign.nak raises UpgradeError", False, repr(exc))
        return
    check("sign.nak raises UpgradeError", raised)


def test_sign_ack_status_nonzero_is_failure():
    sess = _make_session()
    _stub_await(sess, "frame", (P.ACK_SIGN, bytes([0x09])))
    raised = False
    try:
        sess.sign(_Img())
    except UpgradeError:
        raised = True
    check("sign.ack status!=0 raises", raised)


def test_sign_ok_ack_is_success():
    sess = _make_session()
    _stub_await(sess, "frame", (P.ACK_SIGN, bytes([0x00])))
    err = None
    try:
        sess.sign(_Img())
    except Exception as exc:  # noqa: BLE001
        err = exc
    check("sign.ack ok passes", err is None, repr(err))


def test_sign_unexpected_response_is_failure():
    sess = _make_session()
    _stub_await(sess, "frame", (0x7F, b""))
    raised = False
    try:
        sess.sign(_Img())
    except UpgradeError:
        raised = True
    check("sign.unexpected raises", raised)


def test_end_commit_skips_sign():
    """A device without a public key commits inside END and resets.

    Sending SIGN after that puts a QIAP frame into the APP shell; no ACK 0x84
    can ever follow, and the old code burned the whole 90 s SIGN_TIMEOUT before
    declaring a good upgrade failed. This is the reported hang.
    """
    sess = _make_session()
    sess._transact = lambda cmd, payload, ack, **kw: b"\x00"
    _stub_await(sess, "commit")
    sent = []
    sess._send_frame = lambda cmd, payload: sent.append(cmd)

    sess.end(1024, 0x1234)
    check("end.commit detected", sess.committed_at_end is True)

    stamp = sess.sign(_Img())
    check("end.commit skips SIGN", sent == [], sent)
    check("end.commit sign returns None", stamp is None, stamp)


def test_end_no_commit_keeps_sign():
    """A KEY device waits for SIGN: no announcement, so SIGN must still go out."""
    sess = _make_session()
    sess._transact = lambda cmd, payload, ack, **kw: b"\x00"
    _stub_await(sess, None)
    sent = []
    sess._send_frame = lambda cmd, payload: sent.append(cmd)

    sess.end(1024, 0x1234)
    check("end.nocommit flag clear", sess.committed_at_end is False)
    sess.sign(_Img())
    check("end.nocommit still signs", sent == [P.CMD_SIGN], sent)


def test_sign_wait_returns_stamp_early():
    """The boot stamp often lands during the SIGN wait; it must end the wait."""
    sess = _make_session()
    _stub_await(sess, "stamp", "[QAPP] Project V9.9.9999")
    stamp = sess.sign(_Img())
    check("sign.stamp short-circuits", stamp == "[QAPP] Project V9.9.9999", stamp)


def test_raw_log_survives_frame_parsing():
    """ACK and commit banner in one packet: the banner must survive the parser.

    The old _recv_frame() built a throwaway FrameParser per call and dropped
    every byte that was not part of a frame, so the one-shot banners were
    destroyed exactly when they were the answer being waited for.
    """
    sess = _make_session()
    frame = P.build_frame(P.ACK_END, b"\x00")
    packets = [frame + b"\r\n[QIAP] success. Rebooting...\r\n"]
    sess._read_some = lambda: packets.pop(0) if packets else b""

    kind, _ = sess._await(1.0, watch_commit=True)
    check("rx.frame wins the packet", kind == "frame", kind)
    kind2, _ = sess._await(0.05, want_frame=False, watch_commit=True)
    check("rx.commit survives the parser", kind2 == "commit", kind2)


def test_stamp_must_match_image():
    """A stale banner from the old firmware must not pass as the new image."""
    sess = _make_session()
    sess.expected_stamp = "[QAPP] Project V0.10.0002"
    sess._read_some = lambda: b"[QAPP] Project V0.10.0001\r\n"
    sess.reopen = lambda timeout=5.0: False
    raised = False
    try:
        sess.wait_app_stamp(timeout=0.4)
    except UpgradeError:
        raised = True
    check("stamp.stale rejected", raised)


def test_image_expected_stamp():
    """The .bin carries the banner verbatim, so the host can predict it."""
    data = b"\x00" * 32 + b"[QAPP] Project V0.10.0001\r\n> " + b"\x00" * 8
    img = FirmwareImage("<mem>", data)
    check("image.expected_stamp",
          img.expected_stamp == "[QAPP] Project V0.10.0001", img.expected_stamp)
    check("image.no stamp -> None",
          FirmwareImage("<mem>", b"\x00" * 64).expected_stamp is None)


class _FakeBoard(object):
    """Just enough QBOOT to drive a whole run() without hardware.

    Mirrors the firmware behaviour the bug report hinges on:

      * no public key  -> END commits, prints the announcement, resets
      * public key     -> END only ACKs; the commit waits for SIGN
      * either path    -> the APP prints its boot stamp once, after boot
    """

    COMPRESSED = 0.01    # seconds between ACK and the commit announcement

    def __init__(self, key_on_device=False):
        self.key_on_device = key_on_device
        self._parser = P.FrameParser()
        self._out = bytearray()
        self._commit_at = None
        self._stamp_at = None
        self.sign_frames = 0
        self.end_frames = 0

    # -- device -> host
    def _emit(self, frame):
        self._out += frame

    def read(self):
        now = time.time()
        if self._commit_at is not None and now >= self._commit_at:
            self._commit_at = None
            self._out += b"\r\n[QIAP] success. Rebooting...\r\n"
            self._stamp_at = now + self.COMPRESSED
        if self._stamp_at is not None and now >= self._stamp_at:
            self._stamp_at = None
            self._out += b"\r\n[QAPP] Project V0.10.0001\r\n> "
        data = bytes(self._out)
        del self._out[:]
        return data

    # -- host -> device
    def write(self, data):
        for b in bytes(data):
            frame = self._parser.feed(b)
            if frame is not None:
                self._handle(frame)

    def _handle(self, frame):
        cmd, payload = frame
        if cmd == P.CMD_ENTER:
            self._emit(P.build_frame(P.ACK_ENTER, b"\x00"))
        elif cmd == P.CMD_DATA:
            self._emit(P.build_frame(P.ACK_DATA, payload[:4]))
        elif cmd == P.CMD_END:
            self.end_frames += 1
            self._emit(P.build_frame(P.ACK_END, b"\x00"))
            if not self.key_on_device:
                self._commit_at = time.time() + self.COMPRESSED
        elif cmd == P.CMD_SIGN:
            self.sign_frames += 1
            self._emit(P.build_frame(P.ACK_SIGN, b"\x00"))
            self._commit_at = time.time() + self.COMPRESSED


_FAKE_IMG = (b"\x00" * 32 + b"[QAPP] Project V0.10.0001\r\n> "
             + b"\x00" * 1000)


def _run_on_fake_board(fake):
    """run() against the fake, with the serial layer replaced."""
    sess = Session("COM0")
    sess.seed = bytes(32)
    sess._open = lambda: None
    sess.close = lambda: None
    sess._write_bytes = lambda data: (fake.write(data), True)[1]
    sess._read_some = fake.read
    sess.ensure_upgrade_mode = sess.enter
    return sess.run(FirmwareImage("<mem>", _FAKE_IMG))


def test_run_does_not_hang_when_end_commits():
    """The reported bug, end to end: board commits at END, host must not wait.

    A key is supplied (so the operator expects signing) but the device has no
    public key, which is the configuration that produced the 103-second hang.
    """
    fake = _FakeBoard(key_on_device=False)
    t0 = time.time()
    res = _run_on_fake_board(fake)
    took = time.time() - t0
    check("run.commit: finished", res is not None and "[QAPP]" in res.stamp, res)
    check("run.commit: no SIGN sent", fake.sign_frames == 0, fake.sign_frames)
    check("run.commit: under 10 s", took < 10.0, "%.1f s" % took)


def test_run_signs_on_key_device():
    """A KEY device ACKs END, then really does need the SIGN frame."""
    fake = _FakeBoard(key_on_device=True)
    res = _run_on_fake_board(fake)
    check("run.key: finished", res is not None and "[QAPP]" in res.stamp, res)
    check("run.key: SIGN sent once", fake.sign_frames == 1, fake.sign_frames)


def test_speed_uses_write_phase_only():
    """Throughput must come from the DATA window, not from the whole session.

    A real run reported "0.5 KiB/s" because 32.7 s of detection and signature
    wait were folded into the divisor of a 2 s transfer.
    """
    r = Result("[QAPP] x", elapsed=32.7, bytes_written=15688, signed=True,
               write_elapsed=2.0)
    check("result.speed from write window",
          abs(r.speed - (15688 / 1024.0) / 2.0) < 0.05, r.speed)
    check("result.total preserved", abs(r.elapsed - 32.7) < 1e-6, r.elapsed)

    legacy = Result("x", 10.0, 2048, False)
    check("result.speed falls back to total",
          abs(legacy.speed - 0.2) < 1e-6, legacy.speed)


def test_query_line_returns_on_idle():
    """A shell reply is a burst; probes must not spin their full window."""
    sess = _make_session()
    packets = [b"part: app1\r\n"]
    sess._read_some = lambda: packets.pop(0) if packets else b""
    sess._flush_input = lambda: None
    sess._write_bytes = lambda data: True

    t0 = time.time()
    out = sess._query_line(b"part\n", timeout=2.0)
    took = time.time() - t0
    check("query_line got reply", b"app1" in out, out)
    check("query_line exits on idle", took < 1.0, "%.2f s" % took)


def test_app_shell_skips_blind_enter():
    """An APP shell that answers 'part' must not absorb 3 x 2 s ENTER retries."""
    sess = _make_session()
    sess._drain_text = lambda timeout=2.0, idle=None: b""
    sess._query_line = lambda cmd, timeout=2.0, idle=0.35: b"part: app1\r\n"
    called = {"enter": 0, "reset": 0}
    sess.enter = lambda: called.__setitem__("enter", called["enter"] + 1)

    def _reset():
        called["reset"] += 1
        raise UpgradeError("stop here")

    sess._reset_into_qboot = _reset
    try:
        sess.ensure_upgrade_mode()
    except UpgradeError:
        pass
    check("detect.app1 skips blind ENTER", called["enter"] == 0, called)
    check("detect.app1 resets into qboot", called["reset"] == 1, called)


def test_chunk_fits_device_payload_buffer():
    """CHUNK must stay within QUILLA_QIAP_MAX_PAYLOAD, and there is no margin.

    The device does not NAK an oversized frame: on `len > QUILLA_QIAP_MAX_PAYLOAD`
    it returns to SOF and drops the bytes, so the parser silently desyncs.
    Pinning the arithmetic here makes a future CHUNK/PAGE_SIZE edit fail loudly.
    """
    payload = (struct.pack("<II", P.APP_START, P.APP_START + P.CHUNK - 1)
               + bytes(P.CHUNK))
    check("chunk.payload == MAX_PAYLOAD", len(payload) == P.MAX_PAYLOAD, len(payload))
    check("chunk.page aligned", P.CHUNK == P.PAGE_SIZE, (P.CHUNK, P.PAGE_SIZE))

    frame = P.build_frame(P.CMD_DATA, payload)
    check("chunk.frame == payload+6", len(frame) == P.MAX_PAYLOAD + 6, len(frame))
    check("chunk.LEN field", struct.unpack_from("<H", frame, 2)[0] == len(payload))

    parser = P.FrameParser()
    got = None
    for b in frame:
        got = parser.feed(b) or got
    check("chunk.round-trip",
          got is not None and got[0] == P.CMD_DATA and got[1] == payload,
          None if got is None else len(got[1]))


def test_boot_stamp_is_success_criterion():
    """wait_app_stamp() must find the APP banner and return it."""
    sess = _make_session()
    sess._read_some = lambda: b"noise\r\n[QAPP] v0.10 build 2026-11-04\r\n"
    stamp = sess.wait_app_stamp(timeout=2.0)
    check("stamp.detected", stamp is not None and "[QAPP]" in stamp, stamp)


def test_boot_stamp_timeout_is_failure():
    sess = _make_session()
    sess._read_some = lambda: b"nothing here\r\n"
    sess.reopen = lambda timeout=5.0: False
    sess.port_lost = True
    raised = False
    try:
        sess.wait_app_stamp(timeout=0.3)
    except UpgradeError:
        raised = True
    check("stamp.timeout raises", raised)


# ---------------------------------------------------------------- problem 3
def test_i18n_coverage():
    """Every zh key must have an _en counterpart and vice versa."""
    zh_keys = {k for k in i18n._STRINGS if not k.endswith("_en")}
    en_keys = {k[:-3] for k in i18n._STRINGS if k.endswith("_en")}
    missing_en = sorted(k for k in zh_keys if k not in en_keys)
    missing_zh = sorted(k for k in en_keys if k not in zh_keys)
    check("i18n.zh keys have en", not missing_en, missing_en[:10])
    check("i18n.en keys have zh", not missing_zh, missing_zh[:10])

    probes = {
        "gui.fw_info_secver": dict(name="QAPP.bin", size=16.5,
                                   sha="0123456789abcdef", ver=3),
        "gui.fw_info_secver_none": dict(name="QAPP.bin", size=16.5,
                                        sha="0123456789abcdef"),
        "gui.fw_info": dict(name="QAPP.bin", size=16.5, sha="0123456789abcdef"),
        "gui.key_info": dict(pk="0011223344"),
        "gui.detail_speed": dict(speed=12.3),
    }
    for lang in ("zh", "en"):
        i18n.set_language(lang)
        for key, kw in probes.items():
            out = i18n.t(key, **kw)
            check("i18n.%s.%s formats" % (lang, key),
                  "{" not in out and "}" not in out, out)


def test_i18n_language_switch():
    i18n.set_language("zh")
    zh = i18n.t("gui.start")
    i18n.set_language("en")
    en = i18n.t("gui.start")
    check("i18n.zh/en differ", zh != en, "%s == %s" % (zh, en))
    check("i18n.get_language en", i18n.get_language() == "en")
    i18n.set_language("zh")
    check("i18n.get_language zh", i18n.get_language() == "zh")
    i18n.set_language("auto")
    check("i18n.auto resolves", i18n.get_language() in ("zh", "en"),
          i18n.get_language())


def test_gui_smoke():
    """Build the GUI headlessly and switch language live.

    A host without tkinter, or without a display (a bare Linux CI runner), is an
    environment property rather than a regression, so those two cases are
    reported as SKIP instead of failing the suite. Run under xvfb-run to get the
    real coverage on Linux.
    """
    try:
        import tkinter as tk
    except Exception as exc:  # noqa: BLE001
        print("  SKIP  tkinter not installed: %s" % exc)
        return
    try:
        root = tk.Tk()
    except Exception as exc:  # noqa: BLE001
        print("  SKIP  no display available: %s" % exc)
        return
    root.withdraw()
    try:
        from quilla_updater import gui as G
        app = G.UpdaterApp(root)
        root.update_idletasks()

        titles = [app.nb.tab(i, "text") for i in range(app.nb.index("end"))]
        check("gui.tabs present", len(titles) == 2, titles)
        check("gui.tab titles non-empty", all(t.strip() for t in titles), titles)

        # switch to english
        app.var_lang.set("English")
        app._on_lang_change()
        root.update_idletasks()
        en_titles = [app.nb.tab(i, "text") for i in range(app.nb.index("end"))]
        check("gui.en tab titles", all(t.strip() for t in en_titles), en_titles)
        check("gui.en differs from zh", en_titles != titles,
              "%s / %s" % (titles, en_titles))

        btn_text = app.upgrade.btn_start.cget("text")
        check("gui.start button english",
              ("Start" in btn_text) or ("Upgrade" in btn_text), btn_text)

        # back to chinese
        app.var_lang.set("中文")
        app._on_lang_change()
        root.update_idletasks()
        zh_titles = [app.nb.tab(i, "text") for i in range(app.nb.index("end"))]
        check("gui.zh restored", zh_titles == titles,
              "%s / %s" % (titles, zh_titles))

        cfg = config.load_config()
        check("gui.lang persisted", cfg.get("lang") == "zh", cfg.get("lang"))
    finally:
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass


def main():
    test_config_persistence()
    test_sign_missing_ack_is_not_failure()
    test_sign_nak_is_failure()
    test_sign_ack_status_nonzero_is_failure()
    test_sign_ok_ack_is_success()
    test_sign_unexpected_response_is_failure()
    test_end_commit_skips_sign()
    test_end_no_commit_keeps_sign()
    test_sign_wait_returns_stamp_early()
    test_raw_log_survives_frame_parsing()
    test_stamp_must_match_image()
    test_image_expected_stamp()
    test_chunk_fits_device_payload_buffer()
    test_speed_uses_write_phase_only()
    test_query_line_returns_on_idle()
    test_app_shell_skips_blind_enter()
    test_run_does_not_hang_when_end_commits()
    test_run_signs_on_key_device()
    test_boot_stamp_is_success_criterion()
    test_boot_stamp_timeout_is_failure()
    test_i18n_coverage()
    test_i18n_language_switch()
    test_gui_smoke()

    print("PASS: %d" % len(PASSES))
    for f in FAILS:
        print("FAIL: %s" % f)
    print("RESULT: %s" % ("OK" if not FAILS else "%d FAILURE(S)" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
