# -*- coding: utf-8 -*-
# Copyright 2026 JiChiRen Info. Tech.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# This file is part of QuillaUpdater.

"""
QBOOT serial upgrade protocol (QIAP) - wire format, constants and codec.

Everything here is a direct mirror of the firmware side:
  os/services/quilla-qboot/quilla-qiap.c   (frame parser / command dispatch)
  os/lib/crc16.c                           (crc16_add / crc16_data)
  os/services/quilla-qboot/quilla-qboot-hal.h (partition layout, page size)

Frame (host -> MCU and MCU -> host are identical):

    SOF(0xA5) | CMD(1B) | LEN(2B LE) | PAYLOAD(LEN) | CRC16(2B LE)

The CRC covers [CMD][LEN][PAYLOAD] - not the SOF byte. The algorithm is
CCITT 0x1021 reflected with an initial accumulator of 0 (see crc16_add).

Commands:
    ENTER 0x01 : app_start(4B LE) + unlock_key(8B)         -> ACK 0x81 status(1B)
    DATA  0x02 : start(4B) + end(4B) + data(<=CHUNK)       -> ACK 0x82 start(4B)
    END   0x03 : total_len(4B) + total_crc16(2B)           -> ACK 0x83 status(1B)
    SIGN  0x04 : signature(64B Ed25519)                    -> ACK 0x84 status(1B)

A rejection is CMD = 0xC0 | phase  with a 1-byte reason payload:
    0xC1 ENTER / 0xC2 DATA / 0xC3 other / 0xC4 SIGN

This module is transport-agnostic: it knows nothing about pyserial or a GUI,
so it can be unit-tested offline (see tools/selftest.py).
"""

import struct

__all__ = [
    "SOF", "CMD_ENTER", "CMD_DATA", "CMD_END", "CMD_SIGN",
    "ACK_ENTER", "ACK_DATA", "ACK_END", "ACK_SIGN",
    "NAK_ENTER", "NAK_DATA", "NAK_OTHER", "NAK_SIGN", "NAK_CMDS",
    "REASON", "REASON_CRC", "UNLOCK_KEY", "PAGE_SIZE", "CHUNK",
    "MAX_PAYLOAD", "APP_START", "SECVER_OFF", "SECVER_MAGIC_U32",
    "crc16_add", "crc16", "build_frame", "FrameParser",
]

# ---------------------------------------------------------------- frame format
SOF = 0xA5

CMD_ENTER = 0x01
CMD_DATA = 0x02
CMD_END = 0x03
CMD_SIGN = 0x04

ACK_ENTER = 0x81
ACK_DATA = 0x82
ACK_END = 0x83
ACK_SIGN = 0x84

NAK_ENTER = 0xC1
NAK_DATA = 0xC2
NAK_OTHER = 0xC3
NAK_SIGN = 0xC4
NAK_CMDS = (NAK_ENTER, NAK_DATA, NAK_OTHER, NAK_SIGN)

# NAK reason codes - kept in sync with os/services/quilla-qboot/quilla-qiap.h
REASON = {
    0x01: "ADDR  address out of the APP region",
    0x02: "KEY   unlock key mismatch",
    0x03: "CRC   frame/field CRC error",
    0x04: "ERASE Flash page erase failed",
    0x05: "PROG  Flash program/readback failed",
    0x06: "LEN   total length or total CRC mismatch",
    0x07: "SZ    length field does not match data length",
    0x08: "SIGN  signature did not verify (unsigned or mismatched)",
    0x09: "VER   image has no usable security-version region "
          "(missing .quilla_secver section / magic mismatch)",
    0x0A: "ROLLBACK  firmware security version is below the device floor "
          "(downgrade rejected)",
}
#: A CRC failure is the only retransmittable rejection.
REASON_CRC = 0x03

# ------------------------------------------------------------------- constants
#: QUILLA_QBOOT_UNLOCK_KEY, default "QULLOTA1".
UNLOCK_KEY = b"QULLOTA1"

#: QUILLA_QBOOT_PAGE_SIZE - flash erase granularity.
PAGE_SIZE = 256

#: Bytes of image data per DATA frame - one full flash page.
#:
#: The upgrade runs entirely inside QBOOT, so the sizing constraint is the QBOOT
#: receive path, not the APP's shell port:
#:
#:   DMA ring    SHELLPORT_RX_RING_SZ = 1024 B, CIRCULAR mode, never re-armed.
#:               It only has to absorb the bytes that arrive while the QBOOT
#:               loop is blocked inside one synchronous flash page erase
#:               (~25-40 ms @115200 baud ~= 460 B), which it does.
#:   bridge ring QBOOT_RX_RING_SZ = 512 B, sized to hold one whole 270-byte DATA
#:               frame, so a frame enters atomically and is never split across
#:               passes. It is still a byte-stream buffer rather than a frame
#:               buffer: qboot_qiap_run() harvests the DMA ring and then drains
#:               this ring to empty every pass, so occupancy is the backlog
#:               between two passes (one host write burst), not the frame size.
#:   payload buf QUILLA_QIAP_MAX_PAYLOAD = PAGE_SIZE + 8 = 264 B.
#:
#: 256 makes one DATA frame exactly one page: 8 B of addresses + 256 B of data =
#: 264 B of payload, the buffer limit, and 270 B on the wire. That is the largest
#: value this protocol can carry - the device drops any frame whose LEN exceeds
#: MAX_PAYLOAD by returning to SOF, so 256 is a hard ceiling, not a tuning knob.
#:
#: Why bother: flash_write_range() stages into a 256-byte page buffer and only
#: erases/programs when the *next* page is entered, so page-aligned chunks mean
#: one erase per page instead of one per six frames. Fewer ACK round trips per
#: page: 3.1 KiB/s at CHUNK=48 against 7.7 KiB/s measured on a PY32F040 at
#: 115200 (the erase turned out to be faster than the 30-40 ms assumed when the
#: 4.3 KiB/s figure was estimated).
CHUNK = 256

#: QUILLA_QIAP_MAX_PAYLOAD - largest payload the device will accept.
MAX_PAYLOAD = PAGE_SIZE + 8

#: APP region start (= META_BASE + META_SIZE, identical on every current MCU).
#: The real APP_END depends on the MCU's SOC_FLASH_END and is fetched from the
#: device at run time via the QBOOT shell `pinfo` command - never hard-coded.
APP_START = 0x08007000

#: Offset of the .quilla_secver region inside the image (QUILLA_APP_SECVER_OFF).
SECVER_OFF = 0x400

#: QUILLA_APP_SECVER_MAGIC_U32 - little-endian "QAV1".
SECVER_MAGIC_U32 = 0x31564151


# ------------------------------------------------------------------------- CRC
def crc16_add(b, acc):
    """Add one byte to the running CRC, exactly mirroring the C crc16_add()."""
    acc ^= b
    acc &= 0xFFFF
    acc = (acc >> 8) | (acc << 8)
    acc &= 0xFFFF
    acc ^= (acc & 0xFF00) << 4
    acc &= 0xFFFF
    acc ^= (acc >> 8) >> 4
    acc &= 0xFFFF
    acc ^= (acc & 0xFF00) >> 5
    acc &= 0xFFFF
    return acc


def crc16(data, acc=0):
    """Mirror of the C crc16_data(data, len, acc); chainable via acc."""
    for b in data:
        acc = crc16_add(b, acc)
    return acc & 0xFFFF


# ----------------------------------------------------------------- frame codec
def build_frame(cmd, payload):
    """Encode one frame: SOF | CMD | LEN(2) | PAYLOAD | CRC16(2)."""
    body = bytes([cmd]) + struct.pack("<H", len(payload)) + payload
    return bytes([SOF]) + body + struct.pack("<H", crc16(body))


class FrameParser:
    """Byte-stream frame parser with SOF resynchronisation.

    Fed one byte at a time by the serial reader. Non-0xA5 bytes at the SOF
    position are dropped, which is what lets the host ignore the device's text
    banner (`[BOOT] Quilla V...`) and its shell echo on the same port.

    Usage::

        p = FrameParser()
        for b in chunk:
            frame = p.feed(b)
            if frame:
                cmd, payload = frame

    ``lenient=False`` also returns frames whose CRC failed, as
    ``(cmd, payload, False)``; by default corrupt frames are discarded and the
    parser resynchronises on the next SOF.
    """

    _S_SOF, _S_CMD, _S_LEN1, _S_LEN2, _S_PAYLOAD, _S_CRC1, _S_CRC2 = range(7)

    def __init__(self, max_payload=MAX_PAYLOAD):
        self.max_payload = max_payload
        self.reset()

    def reset(self):
        self._state = self._S_SOF
        self._cmd = 0
        self._len = 0
        self._payload = bytearray()
        self._calc = 0
        self._crc_lo = 0

    def feed(self, b):
        """Consume one byte. Returns (cmd, payload) on a valid frame, else None."""
        s = self._state

        if s == self._S_SOF:
            if b == SOF:
                self._state = self._S_CMD
                self._calc = 0
            return None

        if s == self._S_CMD:
            self._cmd = b
            self._calc = crc16_add(b, 0)
            self._state = self._S_LEN1
            return None

        if s == self._S_LEN1:
            self._len = b
            self._calc = crc16_add(b, self._calc)
            self._state = self._S_LEN2
            return None

        if s == self._S_LEN2:
            self._len |= (b << 8)
            self._calc = crc16_add(b, self._calc)
            self._payload = bytearray()
            if self._len == 0:
                self._state = self._S_CRC1
            elif self._len > self.max_payload:
                # Corrupt or hostile length: drop and resync.
                self._state = self._S_SOF
            else:
                self._state = self._S_PAYLOAD
            return None

        if s == self._S_PAYLOAD:
            self._payload.append(b)
            self._calc = crc16_add(b, self._calc)
            if len(self._payload) >= self._len:
                self._state = self._S_CRC1
            return None

        if s == self._S_CRC1:
            self._crc_lo = b
            self._state = self._S_CRC2
            return None

        # _S_CRC2
        self._state = self._S_SOF
        got = (b << 8) | self._crc_lo
        if got == self._calc:
            return (self._cmd, bytes(self._payload))
        return None
