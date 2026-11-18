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
Persistent settings.

The file lives next to the application (the executable's own directory when
frozen, the source tree directory when run from Python), so a portable copy
of the tool carries its settings with it. It holds the operator's last-used
firmware / key paths and UI language; keep it out of version control.

For a one-file PyInstaller build ``__file__`` points into a temporary
extraction directory, so the application directory must come from
``sys.executable``. The file is best-effort: if the directory is not writable
the tool still runs, it just does not remember choices across launches.
"""

import json
import os
import sys


def app_dir():
    """Directory that holds the application (exe when frozen, source otherwise)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


_CONFIG_DIR = app_dir()
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "config.json")

DEFAULTS = {
    "fw_path": "",
    "key_path": "",
    "use_key": True,
    "port": "",
    "baud": "115200",
    "lang": "auto",          # "auto" | "zh" | "en"
    "fw_dir": "",            # last directory used by the firmware dialog
    "keyfile_dir": "",       # last directory used by a private-key dialog
    "last_dir": "",          # legacy shared dialog directory (pre-split);
                             # kept only as a first-run fallback
    "key_dir": "keys",       # last output directory on the key tool page
    "app_reset": "swqboot",  # text command that makes the APP jump to QBOOT
    "app_reset_hex": "",     # raw hex reset command (takes precedence); "" = off
    "use_hex_reset": False,  # UI toggle: send the hex command instead of text
}


def load_config():
    """Return the merged config (defaults + anything valid we found on disk)."""
    cfg = dict(DEFAULTS)
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            for key in DEFAULTS:
                if key in data and isinstance(data[key], type(DEFAULTS[key])):
                    cfg[key] = data[key]
    except Exception:
        pass
    return cfg


def save_config(cfg):
    """Persist `cfg`. Silently no-op if the location is not writable."""
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        pass


def update(**fields):
    """Load, patch a few fields, and write back in one call."""
    cfg = load_config()
    cfg.update(fields)
    save_config(cfg)
    return cfg
