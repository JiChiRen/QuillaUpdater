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

"""Insert the Apache-2.0 header into every Python source file.

This repository contains no contiki-NG code. Quilla's C/H sources are a
different tree and keep their original Swedish Institute of Computer Science
licence - that is a licence obligation, not a leftover to be tidied up. This
tool's header names the actual copyright holder and agrees with LICENSE.

The script is idempotent: a file that already carries the Apache marker is
left alone, so it can be re-run after adding sources.
"""

import io
import os

MARKER = "This file is part of QuillaUpdater."

BODY = [
    "Copyright 2026 JiChiRen Info. Tech.",
    "",
    "Licensed under the Apache License, Version 2.0 (the \"License\");",
    "you may not use this file except in compliance with the License.",
    "You may obtain a copy of the License at",
    "",
    "    http://www.apache.org/licenses/LICENSE-2.0",
    "",
    "Unless required by applicable law or agreed to in writing, software",
    "distributed under the License is distributed on an \"AS IS\" BASIS,",
    "WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.",
    "See the License for the specific language governing permissions and",
    "limitations under the License.",
    "",
    MARKER,
]


def header_lines(prefix="#"):
    out = []
    for line in BODY:
        out.append((prefix + " " + line).rstrip() if line else prefix)
    return out


def has_header(path):
    with io.open(path, encoding="utf-8") as fh:
        return any("Licensed under the Apache License" in line for line in fh.read().split("\n")[:5])


def insert(path, prefix="#"):
    with io.open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")

    # Only the first few lines count: this script mentions MARKER in its own
    # source, and a docstring may legitimately quote it.
    if has_header(path):
        return "skip (already has header)"

    pos = 0
    if lines and lines[0].startswith("#!"):
        pos = 1
    # PEP 263: the coding line only counts within the first two lines.
    if len(lines) > pos and "coding" in lines[pos] and lines[pos].lstrip().startswith("#"):
        pos += 1

    block = header_lines(prefix) + [""]
    new = lines[:pos] + block + lines[pos:]
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(new))
    return "inserted after line %d" % pos


def collect(root):
    targets = []
    for sub in ("quilla_updater", "tools"):
        d = os.path.join(root, sub)
        for name in sorted(os.listdir(d)):
            if name.endswith(".py"):
                targets.append(os.path.join(d, name))
    return targets


def main(argv):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    check = "--check" in argv

    missing = []
    for path in collect(root):
        rel = os.path.relpath(path, root)
        if check:
            if not has_header(path):
                missing.append(rel)
            continue
        print("%-34s %s" % (rel, insert(path)))

    if check:
        if missing:
            print("license header missing in %d file(s):" % len(missing))
            for rel in missing:
                print("  %s" % rel)
            print("run: python tools/add_license_header.py")
            return 1
        print("license header: OK (%d files)" % len(collect(root)))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
