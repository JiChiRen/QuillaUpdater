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
Firmware image inspection.

Reads a raw QAPP .bin and extracts the two things the host can know before it
talks to the device:

  * the exact byte length and SHA-256 of the image (the signed descriptor)
  * the anti-rollback security version stored in the .quilla_secver region

The security version lives at a fixed offset inside the image
(QUILLA_APP_SECVER_OFF = 0x400) as a little-endian pair:

    magic   uint32  "QAV1" (0x31564151)
    version uint32  QUILLA_APP_SECURITY_VERSION

QBOOT reads the same bytes at APP_START + 0x400 after the image is written and
rejects it when `version` is below the device's floor (NAK reason 0x0A). Showing
it in the UI before the write is the whole point: a downgrade is otherwise only
discovered after a full 40-second transfer.
"""

import hashlib
import os
import struct

from .protocol import SECVER_MAGIC_U32, SECVER_OFF

__all__ = ["FirmwareImage", "ImageError", "BOOT_STAMP_MARKER"]

#: First characters of the APP's one-shot boot stamp. The APP prints it exactly
#: once, at the very top of main():
#:
#:     shell_output("[QAPP] " QUILLA_PROJECT_NAME " V" <version> "\r\n> ");
#:
#: Every piece of that string is a compile-time literal, so the bytes the device
#: will print are already verbatim inside the .bin. That is what makes the stamp
#: checkable instead of merely observable: the host can tell "the NEW image just
#: booted" apart from "some old banner was still in the buffer".
BOOT_STAMP_MARKER = b"[QAPP]"

#: Bound on the stamp length scanned out of the image (the real one is ~30 B).
_STAMP_MAX = 96


class ImageError(Exception):
    """The file is not a usable QAPP image."""


class FirmwareImage:
    """A loaded .bin plus its precomputed descriptor fields."""

    def __init__(self, path, data):
        self.path = path
        self.data = data
        self.size = len(data)
        self.sha256 = hashlib.sha256(data).digest()

    # -- security version -----------------------------------------------------
    @property
    def secver(self):
        """The image's anti-rollback version, or None if the region is absent.

        None means QBOOT will reject the image with VER (0x09) once a public key
        is flashed; an unsigned/sealed-only build may still accept it.
        """
        if self.size < SECVER_OFF + 8:
            return None
        magic, version = struct.unpack_from("<II", self.data, SECVER_OFF)
        if magic != SECVER_MAGIC_U32:
            return None
        return version

    @property
    def has_secver(self):
        return self.secver is not None

    # -- boot stamp -----------------------------------------------------------
    @property
    def expected_stamp(self):
        """The exact boot stamp this image prints, or None if it has none.

        Example: ``[QAPP] Project V0.10.0001``. Used to confirm that the APP
        which just booted really is this image and not the previous one (a stale
        banner still sitting in the serial buffer, or a device that silently
        refused the write and restarted the old firmware).
        """
        i = self.data.find(BOOT_STAMP_MARKER)
        if i < 0:
            return None
        end = i
        limit = min(self.size, i + _STAMP_MAX)
        while end < limit and self.data[end] not in (0x0D, 0x0A):
            end += 1
        try:
            text = self.data[i:end].decode("ascii")
        except UnicodeDecodeError:
            return None
        if len(text) <= len(BOOT_STAMP_MARKER) + 1:
            return None
        return text

    # -- display helpers ------------------------------------------------------
    @property
    def name(self):
        return os.path.basename(self.path)

    def summary(self):
        """One-line description for the UI / log."""
        ver = self.secver
        ver_txt = ("secver=%d (0x%X)" % (ver, ver)) if ver is not None \
            else "secver=missing (QBOOT will reject it on a KEY build)"
        return "%s: %d B (%.1f KiB), SHA-256 %s..., %s" % (
            self.name, self.size, self.size / 1024.0,
            self.sha256.hex()[:16], ver_txt)

    # -- loading --------------------------------------------------------------
    @classmethod
    def load(cls, path):
        if not os.path.isfile(path):
            raise ImageError("no such file: %s" % path)
        with open(path, "rb") as f:
            data = f.read()
        if not data:
            raise ImageError("%s is empty" % path)
        return cls(path, data)
