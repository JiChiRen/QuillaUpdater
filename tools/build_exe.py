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

"""Freeze Quilla Updater into standalone executables.

Two programs are produced from one source tree:

    dist/QuillaUpdater.exe   GUI, windowed (no console window)
    dist/quflash.exe         CLI, console (for production lines and CI)

Usage::

    python tools/build_exe.py              # both programs
    python tools/build_exe.py --gui        # GUI only
    python tools/build_exe.py --cli        # CLI only
    python tools/build_exe.py --icon X.ico # override the embedded Quilla logo

The build is reproducible from a clean checkout: nothing outside this
repository is read, and the launchers are generated into ``build/freeze`` so
the source tree stays free of packaging glue.

Requires ``pyinstaller`` (``pip install -e .[build]``).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

WORK = os.path.join(ROOT, "build", "freeze")
DIST = os.path.join(ROOT, "dist")

#: (exe name, launcher source, windowed)
TARGETS = {
    "gui": ("QuillaUpdater", "from quilla_updater.gui import main\n"
                             "raise SystemExit(main() or 0)\n", True),
    "cli": ("quflash", "from quilla_updater.cli import main\n"
                       "raise SystemExit(main())\n", False),
}


def _launcher(path: str, source: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(source)
    return path


def build(kind: str, icon: str | None, cleanup: bool) -> str:
    name, source, windowed = TARGETS[kind]
    entry = _launcher(os.path.join(WORK, "_entry_%s.py" % kind), source)

    args = [
        sys.executable, "-m", "PyInstaller",
        entry,
        "--name", name,
        "--onefile",
        "--noconfirm",
        "--distpath", DIST,
        "--workpath", os.path.join(WORK, kind),
        "--specpath", os.path.join(WORK, kind),
        # The package lives at the repository root, not next to the launcher.
        "--paths", ROOT,
        # pyserial loads its platform backend lazily; make both explicit so a
        # frozen build cannot fall over at run time on a host it was not built on.
        "--hidden-import", "serial.tools.list_ports",
        "--hidden-import", "serial.serialwin32",
        "--hidden-import", "serial.serialposix",
        # Nothing here uses these, and dragging them in triples the size.
        "--exclude-module", "numpy",
        "--exclude-module", "PIL",
        "--exclude-module", "pytest",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc_data",
    ]
    if cleanup:
        args.append("--clean")
    if windowed:
        args.append("--windowed")
    else:
        args.append("--console")
    # Bundle the window-icon PNG next to the GUI package so the running window
    # (not just the file icon) shows the Quilla mark.
    if kind == "gui":
        res_png = os.path.join(ROOT, "quilla_updater", "resources",
                               "quilla-mark-256.png")
        if os.path.exists(res_png):
            sep = ";" if os.name == "nt" else ":"
            args += ["--add-data",
                     "%s%squilla_updater/resources" % (res_png, sep)]
    # Embed the Quilla logo by default; --icon overrides, a missing default is
    # ignored rather than failing the build.
    icon_path = icon if (icon and os.path.exists(icon)) else None
    if icon_path:
        args.extend(["--icon", icon_path])

    print("[build] %s -> %s" % (kind, os.path.join(DIST, name + (".exe" if os.name == "nt" else ""))))
    proc = subprocess.run(args, cwd=ROOT)
    if proc.returncode != 0:
        raise SystemExit("[build] PyInstaller failed for %s (rc=%d)" % (kind, proc.returncode))

    out = os.path.join(DIST, name + (".exe" if os.name == "nt" else ""))
    if not os.path.exists(out):
        raise SystemExit("[build] expected output missing: %s" % out)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Freeze Quilla Updater into executables.")
    ap.add_argument("--gui", action="store_true", help="build the GUI executable only")
    ap.add_argument("--cli", action="store_true", help="build the CLI executable only")
    ap.add_argument("--icon", default=os.path.join(ROOT, "quilla.ico"),
                    help="path to a Windows .ico to embed "
                         "(default: the Quilla logo in this repository)")
    ap.add_argument("--no-clean", action="store_true",
                    help="reuse the PyInstaller cache instead of rebuilding it")
    args = ap.parse_args(argv)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run:  %s -m pip install -e .[build]"
              % os.path.basename(sys.executable), file=sys.stderr)
        return 2

    kinds = [k for k, flag in (("gui", args.gui), ("cli", args.cli)) if flag] \
        or ["gui", "cli"]

    if not args.no_clean and os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)

    made = [build(k, args.icon, cleanup=not args.no_clean) for k in kinds]
    print()
    for path in made:
        print("[build] %-28s %7.1f KiB" % (os.path.basename(path),
                                           os.path.getsize(path) / 1024.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
