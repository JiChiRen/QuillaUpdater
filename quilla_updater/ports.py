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
Serial port enumeration.

A USB-UART bridge is what makes a board look like COMx, so a plain COM list is
not useful on a bench with several of them. This module sorts likely-relevant
ports first and annotates the USB bridge so the operator can tell boards apart.

No driver-specific probing: everything comes from pyserial's list_ports, which
uses SetupAPI on Windows, /sys on Linux and IOKit on macOS.
"""

import re

__all__ = ["PortInfo", "list_ports", "describe"]

#: VID:PID of the USB-UART bridges commonly used on embedded boards.
KNOWN_BRIDGES = {
    (0x1A86, 0x7523): "CH340",
    (0x1A86, 0x5523): "CH341",
    (0x1A86, 0x55D4): "CH9102",
    (0x10C4, 0xEA60): "CP2102/CP2104",
    (0x10C4, 0xEA70): "CP2105",
    (0x0403, 0x6001): "FT232R",
    (0x0403, 0x6010): "FT2232",
    (0x0403, 0x6014): "FT232H",
    (0x067B, 0x2303): "PL2303",
    (0x0483, 0x374B): "STM32 VCP",
    (0x2E3C, 0x5740): "PY32 VCP",
    (0x1A86, 0x55D3): "CH343",
    (0x1A86, 0x8010): "WCH-Link",
    (0x1A86, 0x8012): "WCH-Link",
}

_VIDPID = re.compile(r"VID:PID=([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4})")


class PortInfo(object):
    """One serial port, with the USB bridge identified when possible."""

    __slots__ = ("device", "description", "hwid", "vid", "pid", "bridge")

    def __init__(self, device, description="", hwid="", vid=None, pid=None):
        self.device = device
        self.description = description or ""
        self.hwid = hwid or ""
        self.vid = vid
        self.pid = pid
        if vid is not None and pid is not None:
            self.bridge = KNOWN_BRIDGES.get((vid, pid), "")
        else:
            self.bridge = ""

    @property
    def is_usb_uart(self):
        return self.bridge != "" or self.vid is not None

    def label(self):
        """Dropdown text: 'COM7  CH340' or 'COM3  蓝牙链接上的标准串行'."""
        parts = [self.device]
        tag = self.bridge
        if not tag:
            # Unknown bridge: fall back to the driver description, minus the
            # redundant "(COMx)" suffix the driver appends.
            desc = self.description.strip()
            if desc and desc != "n/a":
                tag = desc.replace("(%s)" % self.device, "").strip()
                if tag in ("", "-"):
                    tag = desc
        if tag:
            parts.append(tag)
        return "  ".join(parts)

    def __repr__(self):
        return "<PortInfo %s %s%s>" % (
            self.device, self.description,
            (" " + self.bridge) if self.bridge else "")


def list_ports(usb_only=False):
    """Return PortInfo objects, USB-UART bridges first.

    Raises RuntimeError when pyserial is missing, with a readable hint.
    """
    try:
        from serial.tools import list_ports as _lp
    except ImportError:
        raise RuntimeError(
            "pyserial is not installed; run: pip install pyserial")

    out = []
    for p in _lp.comports():
        m = _VIDPID.search(p.hwid or "")
        vid = int(m.group(1), 16) if m else None
        pid = int(m.group(2), 16) if m else None
        out.append(PortInfo(p.device, p.description, p.hwid, vid, pid))

    if usb_only:
        out = [p for p in out if p.is_usb_uart]

    # USB-UART bridges first, then plain COMs, each group sorted by name.
    out.sort(key=lambda p: (not p.is_usb_uart, _natural_key(p.device)))
    return out


def _natural_key(s):
    """Sort COM2 before COM10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def describe():
    """Human-readable port listing, for the CLI --list-ports output."""
    ports = list_ports()
    if not ports:
        return "no serial ports found"
    return "\n".join("  " + p.label() for p in ports)
