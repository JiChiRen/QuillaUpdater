#!/usr/bin/env python3
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
Key management for Quilla secure boot.

    python tools/keygen.py keygen --dir keys        generate a keypair
    python tools/keygen.py pubkey --key keys/private.hex
                                                    show the public key + build macro

The private key is a 32-byte Ed25519 seed in hex. The matching public key is
compiled into QBOOT with -DQUILLA_SECURE_BOOT_PUBKEY={...}; once that is done
QBOOT refuses any image without a valid SIGN frame.

Keep the private key on the signing station only. It never belongs in the app
repository, and never in a firmware image.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quilla_updater import ed25519            # noqa: E402


def cmd_keygen(args):
    seed, pk = ed25519.keygen(args.dir)
    sk_path = os.path.join(args.dir, "private.hex")
    print("wrote %s   KEEP SECRET (32-byte seed)" % sk_path)
    print("wrote %s" % os.path.join(args.dir, "public.hex"))
    print("")
    print("Bake the public key into the QBOOT build:")
    print("  " + ed25519.pubkey_macro(pk))
    print("")
    print("Never commit %s. Make sure it is in .gitignore." % sk_path)
    return 0


def cmd_pubkey(args):
    seed = ed25519.load_seed_hex(args.key)
    pk = ed25519.pubkey_from_seed(seed)
    print(pk.hex())
    print("")
    print("  " + ed25519.pubkey_macro(pk))
    return 0


def cmd_selftest(_args):
    failures = ed25519.self_test()
    for f in failures:
        print("FAIL: " + f)
    print("Ed25519 self-test: %s" % ("PASS" if not failures else "FAILED"))
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="Quilla Ed25519 key tool")
    sub = ap.add_subparsers(dest="cmd")

    g = sub.add_parser("keygen", help="generate a keypair")
    g.add_argument("--dir", default="keys", help="output directory (default: keys)")
    g.set_defaults(func=cmd_keygen)

    p = sub.add_parser("pubkey", help="print the public key for a private key")
    p.add_argument("--key", required=True, help="path to private.hex")
    p.set_defaults(func=cmd_pubkey)

    t = sub.add_parser("self-test", help="check against the RFC 8032 vectors")
    t.set_defaults(func=cmd_selftest)

    args = ap.parse_args()
    if hasattr(args, "func"):
        return args.func(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
