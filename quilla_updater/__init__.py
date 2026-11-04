# -*- coding: utf-8 -*-
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
