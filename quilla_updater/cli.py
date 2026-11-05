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
Command-line interface - the same engine the GUI drives, headless.

Kept because a production line, a CI job or a field script cannot click a
button, and because a bug report is far more useful with a text log than with a
screenshot of a progress bar.
"""

import argparse
import os
import sys
import time

from . import ports as ports_mod
from . import __version__
from . import i18n
from . import config
from .image import FirmwareImage, ImageError
from .session import Session, UpgradeError, UpgradeCancelled, Progress

_LEVEL_PREFIX = {"info": "[*]", "ok": "[+]", "warn": "[!]", "err": "[X]", "debug": "[.]"}


def _enable_utf8_console():
    """Make bilingual output survive the Windows console.

    This program emits UTF-8. A frozen build, however, inherits the host's ANSI
    code page (cp936 on a Chinese Windows), so port descriptions and every
    Chinese log line reach the terminal as GBK bytes and render as mojibake in
    Windows Terminal, VS Code, and any pipe that assumes UTF-8. Switching the
    console to code page 65001 and pinning the stream encoders keeps the bytes
    the program writes and the code page they are interpreted with in agreement.

    Harmless where it does not apply: non-Windows hosts return immediately, and
    a stream that cannot be reconfigured (an embedded caller passing a StringIO)
    is left untouched.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _phase_label(phase):
    return i18n.t("phase." + phase)


class Console(object):
    """Log sink that keeps the progress line and the log lines from colliding."""

    def __init__(self, verbose=True):
        self.verbose = verbose
        self._dirty = False

    def log(self, level, text):
        if not self.verbose and level in ("info", "debug"):
            return
        if self._dirty:
            sys.stderr.write("\n")
            self._dirty = False
        sys.stderr.write("%s %s\n" % (_LEVEL_PREFIX.get(level, "[*]"), text))
        sys.stderr.flush()

    def progress(self, phase, done, total):
        if phase == Progress.WRITE and total:
            pct = done * 100 // total
            sys.stderr.write("\r    %s %3d%%  (%d/%d B)" % (_phase_label(phase), pct, done, total))
            self._dirty = True
            if done >= total:
                sys.stderr.write("\n")
                self._dirty = False
        elif phase in (Progress.DETECT, Progress.ENTER, Progress.END,
                       Progress.SIGN, Progress.VERIFY, Progress.DONE):
            if self._dirty:
                sys.stderr.write("\n")
                self._dirty = False
            sys.stderr.write("[*] %s\n" % _phase_label(phase))
            sys.stderr.flush()


def cmd_list_ports(_args):
    print(ports_mod.describe())
    return 0


def cmd_self_test(_args):
    from . import ed25519
    from .protocol import (build_frame, crc16, FrameParser, CMD_ENTER,
                           CMD_DATA, CMD_END, UNLOCK_KEY, APP_START)
    import struct

    print("[self-test] frame codec + CRC round-trip ...")
    cases = [
        (CMD_ENTER, struct.pack("<I", APP_START) + UNLOCK_KEY),
        (CMD_DATA, struct.pack("<II", APP_START, APP_START + 47) + b"\xAA" * 48),
        (CMD_END, struct.pack("<I", 1234) + struct.pack("<H", 0xBEEF)),
    ]
    for cmd, payload in cases:
        frame = build_frame(cmd, payload)
        if frame[0] != 0xA5:
            print("FAIL: missing SOF")
            return 1
        parser = FrameParser()
        got = None
        for b in frame:
            got = parser.feed(b) or got
        if got is None or got[0] != cmd or got[1] != payload:
            print("FAIL: round-trip mismatch for cmd 0x%02X" % cmd)
            return 1
        print("  ok  cmd=0x%02X len=%d" % (cmd, len(payload)))

    print("[self-test] chained CRC accumulation ...")
    d0 = b"\x00" * 100
    d1 = b"\xAB\xCD\xEF" * 10
    if crc16(d0 + d1) != crc16(d1, crc16(d0)):
        print("FAIL: chained CRC does not match the device accumulation")
        return 1
    print("  ok")

    print("[self-test] corrupted frame is rejected ...")
    frame = bytearray(build_frame(CMD_DATA, b"\x11" * 48))
    frame[-1] ^= 0xFF
    parser = FrameParser()
    got = None
    for b in frame:
        got = parser.feed(b) or got
    if got is not None:
        print("FAIL: a corrupted frame was accepted")
        return 1
    print("  ok")

    print("[self-test] Ed25519 RFC 8032 vectors ...")
    failures = ed25519.self_test()
    if failures:
        for f in failures:
            print("FAIL: " + f)
        return 1
    print("  ok")

    print("\nself-test: PASS")
    return 0


def cmd_probe(args):
    console = Console(verbose=True)
    try:
        sess = Session(args.port, args.baud, on_log=console.log,
                       on_progress=console.progress,
                       reset_cmd=args.app_reset, reset_cmd_hex=args.app_reset_hex)
    except ValueError as e:
        print("[X] %s" % e, file=sys.stderr)
        return 2
    try:
        sess._open()
        banner = sess._drain_text(4.0)
        print("[banner] %r" % banner)
        for cmd in (b"part\n", b"help\n", b"pinfo\n"):
            out = sess._query_line(cmd, 2.0)
            print("[%-5s] %r" % (cmd.strip().decode(), out))
        print()
        print(i18n.t("cli.how_to_read"))
        print(i18n.t("cli.hint_qboot"))
        print(i18n.t("cli.hint_app1"))
        print(i18n.t("cli.hint_idle"))
        print(i18n.t("cli.hint_pinfo"))
        return 0
    except UpgradeError as e:
        print("[X] %s" % e, file=sys.stderr)
        return 1
    finally:
        sess.close()


def cmd_flash(args):
    console = Console(verbose=not args.quiet)
    try:
        image = FirmwareImage.load(args.binfile)
    except ImageError as e:
        print("[X] %s" % e, file=sys.stderr)
        return 1

    console.log("info", i18n.t("cli.fw_summary", summary=image.summary()))
    if image.secver is None:
        console.log("warn", i18n.t("cli.warn_no_secver"))
    if not args.key:
        console.log("warn", i18n.t("cli.warn_no_key"))

    try:
        sess = Session(args.port, args.baud, key_path=args.key,
                       on_log=console.log, on_progress=console.progress,
                       reset_cmd=args.app_reset, reset_cmd_hex=args.app_reset_hex)
    except ValueError as e:
        print("[X] %s" % e, file=sys.stderr)
        return 2
    try:
        result = sess.run(image)
    except UpgradeCancelled:
        print("\n[!] " + i18n.t("cli.cancelled"), file=sys.stderr)
        return 130
    except UpgradeError as e:
        print("\n[X] %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[!] " + i18n.t("cli.interrupted"), file=sys.stderr)
        return 130
    finally:
        sess.close()

    print("[+] " + i18n.t("cli.success", result=result))
    return 0


def cmd_audit_i18n(_args):
    """Check the string table for missing translations and key collisions."""
    problems = i18n.audit()
    if not problems:
        print("[+] i18n audit: PASS (%d keys)"
              % len([k for k in i18n._STRINGS if not k.endswith("_en")]))
        return 0
    for p in problems:
        print("[X] " + p, file=sys.stderr)
    print("[X] i18n audit: %d problem(s)" % len(problems), file=sys.stderr)
    return 1


def _build_parser(default_lang):
    """Build the argument parser.

    The description and every --help string are frozen into the parser at
    construction time, so the language has to be resolved before this runs.
    """
    ap = argparse.ArgumentParser(
        prog="quflash",
        description=i18n.t("cli.desc"))
    ap.add_argument("port", nargs="?", help=i18n.t("cli.port_help"))
    ap.add_argument("binfile", nargs="?", help=i18n.t("cli.bin_help"))
    ap.add_argument("-b", "--baud", type=int, default=115200,
                    help=i18n.t("cli.baud_help"))
    ap.add_argument("--key", metavar="PATH", help=i18n.t("cli.key_help"))
    ap.add_argument("-q", "--quiet", action="store_true",
                    help=i18n.t("cli.quiet_help"))
    ap.add_argument("--probe", action="store_true", help=i18n.t("cli.probe_help"))
    ap.add_argument("--list-ports", action="store_true",
                    help=i18n.t("cli.list_ports_help"))
    ap.add_argument("--self-test", action="store_true",
                    help=i18n.t("cli.self_test_help"))
    ap.add_argument("--audit-i18n", action="store_true",
                    help=i18n.t("cli.audit_help"))
    ap.add_argument("--lang", choices=("auto", "zh", "en"), default=default_lang,
                    help=i18n.t("cli.lang_help"))
    ap.add_argument("--app-reset", metavar="TEXT", default="swqboot",
                    help=i18n.t("cli.app_reset_help"))
    ap.add_argument("--app-reset-hex", metavar="HEX", default=None,
                    help=i18n.t("cli.app_reset_hex_help"))
    ap.add_argument("--version", action="version", version="%(prog)s " + __version__)
    return ap


def _prescan_lang(argv, default_lang):
    """Find --lang in argv without going through argparse.

    argparse triggers its --help action during parsing, so a pre-pass with
    parse_known_args() would print the help in the wrong language. Scanning
    the raw argv keeps --help rendering in the requested language.
    """
    lang = default_lang
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            lang = argv[i + 1]
        elif a.startswith("--lang="):
            lang = a.split("=", 1)[1]
    return lang if lang in ("auto", "zh", "en") else default_lang


def main(argv=None):
    _enable_utf8_console()
    if argv is None:
        argv = sys.argv[1:]
    cfg = config.load_config()
    default_lang = cfg.get("lang", "auto")

    # The language has to be resolved BEFORE the parser is built: the
    # description and every --help text are frozen in at construction time.
    i18n.set_language(default_lang)
    i18n.set_language(_prescan_lang(argv, default_lang))

    ap = _build_parser(default_lang)
    args = ap.parse_args(argv)

    if args.audit_i18n:
        return cmd_audit_i18n(args)
    if args.self_test:
        return cmd_self_test(args)
    if args.list_ports:
        return cmd_list_ports(args)
    if args.probe:
        if not args.port:
            ap.error(i18n.t("cli.probe_needs_port"))
        return cmd_probe(args)
    if not args.port or not args.binfile:
        ap.error(i18n.t("cli.need_both"))
    return cmd_flash(args)


if __name__ == "__main__":
    sys.exit(main())
