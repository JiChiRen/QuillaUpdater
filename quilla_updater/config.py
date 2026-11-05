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
