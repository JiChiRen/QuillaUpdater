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

Kept out of the repository (it lives in the user's home directory), because it
holds the operator's last-used firmware / key paths and the UI language: things
that are personal to whoever runs the tool, not part of the project source.

The file is best-effort only: if the home directory is not writable the tool
still runs, it just does not remember choices across launches.
"""

import json
import os

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".quilla_updater")
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "config.json")

DEFAULTS = {
    "fw_path": "",
    "key_path": "",
    "use_key": True,
    "port": "",
    "baud": "115200",
    "lang": "auto",          # "auto" | "zh" | "en"
    "last_dir": "",          # last directory used by a file dialog
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
