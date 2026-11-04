# -*- coding: utf-8 -*-
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
