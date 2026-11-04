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

"""Insert the BSD-3-Clause header into every Python source file.

The block layout follows the header Quilla's C/H sources carry, but the
disclaimer names "the copyright holder" rather than "the Institute". Those C/H
files are contiki-NG derivatives and must keep the original Swedish Institute
of Computer Science wording - that is a licence obligation, not a leftover to
be tidied up. This repository contains no contiki-NG code, so its header names
the actual holder and agrees with LICENSE.

The script is idempotent: a file that already carries the marker line is left
alone, so it can be re-run after adding sources.
"""

import io
import os

MARKER = "This file is part of QuillaUpdater."

BODY = [
    "Copyright (c) 2026, JiChiRen Info. Tech.",
    "All rights reserved.",
    "",
    "Redistribution and use in source and binary forms, with or without",
    "modification, are permitted provided that the following conditions",
    "are met:",
    "1. Redistributions of source code must retain the above copyright",
    "   notice, this list of conditions and the following disclaimer.",
    "2. Redistributions in binary form must reproduce the above copyright",
    "   notice, this list of conditions and the following disclaimer in the",
    "   documentation and/or other materials provided with the distribution.",
    "3. Neither the name of the copyright holder nor the names of its",
    "   contributors may be used to endorse or promote products derived from",
    "   this software without specific prior written permission.",
    "",
    "THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS",
    "``AS IS`` AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT",
    "LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A",
    "PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT",
    "HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,",
    "SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED",
    "TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR",
    "PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF",
    "LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING",
    "NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS",
    "SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.",
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
        return any("Copyright (c) 2026" in line for line in fh.read().split("\n")[:5])


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
