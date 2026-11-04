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
Quilla Updater - host-side UART upgrader for QBOOT boards.

Public surface:

    from quilla_updater import FirmwareImage, Session

    image = FirmwareImage.load("QAPP.bin")
    sess = Session("COM7", 115200, key_path="private.hex",
                   on_log=print, on_progress=lambda *a: None)
    print(sess.run(image))

The GUI (quilla_updater.gui) and the CLI (quilla_updater.cli) are both thin
shells over these two classes; the protocol itself lives in
quilla_updater.protocol and knows nothing about serial ports or windows.
"""

__version__ = "1.0.0"

from .image import FirmwareImage, ImageError          # noqa: E402,F401
from .session import (                                # noqa: E402,F401
    Session, UpgradeError, UpgradeCancelled, Progress, Result,
)

__all__ = ["FirmwareImage", "ImageError", "Session", "UpgradeError",
           "UpgradeCancelled", "Progress", "Result", "__version__"]
