# -*- coding: utf-8 -*-
"""
Ed25519 signing (RFC 8032), pure standard library.

Ported from the Quilla tree (tools/quilla_ed25519_sign.py,
Copyright (c) 2026, JiChiRen Info. Tech., BSD-3-Clause) so the updater has no
third-party crypto dependency and can be frozen into a single executable.

Signing only - the device verifies, the host never needs to.

The signed object is the firmware descriptor, not the file:

    image_len (4B LE) || SHA-256(image)

which is exactly what the firmware's quilla_qboot_secure_verify_descriptor()
recomputes. The security version is *not* part of the descriptor; QBOOT reads
it from the .quilla_secver region inside the image and compares it against its
anti-rollback floor. See docs/protocol.md.
"""

import hashlib
import os

__all__ = [
    "P", "L", "D", "B",
    "pubkey_from_seed", "sign", "verify", "sign_descriptor",
    "load_seed_hex", "keygen", "self_test",
]

# ---- curve constants (RFC 8032 section 5.1) ---------------------------------
P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P

BY = (4 * pow(5, P - 2, P)) % P


def _recover_x(y, sign=0):
    """Recover x from y on -x^2 + y^2 = 1 + d*x^2*y^2."""
    y2 = pow(y, 2, P)
    num = (y2 - 1) % P
    den = (D * y2 + 1) % P
    x2 = (num * pow(den, P - 2, P)) % P

    x = pow(x2, (P + 3) // 8, P)
    if pow(x, 2, P) != x2:
        x = (x * pow(2, (P - 1) // 4, P)) % P
    if pow(x, 2, P) != x2:
        raise ValueError("point not on curve")
    if (x & 1) != sign:
        x = (-x) % P
    return x


BX = _recover_x(BY, 0)
B = (BX, BY)


# ---- group law --------------------------------------------------------------
def point_add(p1, p2):
    x1, y1 = p1
    x2, y2 = p2
    # Complete addition law for a = -1: no exceptional cases.
    k = (D * x1 * x2 * y1 * y2) % P
    x3 = ((x1 * y2 + x2 * y1) * pow(1 + k, P - 2, P)) % P
    y3 = ((y1 * y2 + x1 * x2) * pow(1 - k, P - 2, P)) % P
    return (x3, y3)


def point_double(p):
    return point_add(p, p)


def scalarmult(k, p):
    q = (0, 1)                       # identity
    while k > 0:
        if k & 1:
            q = point_add(q, p)
        p = point_double(p)
        k >>= 1
    return q


# ---- encodings --------------------------------------------------------------
def encode_point(p):
    x, y = p
    out = bytearray(y.to_bytes(32, "little"))
    if x & 1:
        out[31] |= 0x80
    return bytes(out)


def sha512(b):
    return hashlib.sha512(b).digest()


def _decode_point(s):
    if len(s) != 32:
        raise ValueError("bad point length")
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    x = _recover_x(y, (s[31] >> 7) & 1)
    return (x, y)


# ---- key handling -----------------------------------------------------------
def pubkey_from_seed(seed):
    """Derive the 32-byte public key from a 32-byte seed."""
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    h = sha512(seed)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return encode_point(scalarmult(a, B))


def sign(seed, msg):
    """RFC 8032 section 5.1.6. Returns the 64-byte signature."""
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    h = sha512(seed)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    prefix = h[32:]

    A = encode_point(scalarmult(a, B))
    r = int.from_bytes(sha512(prefix + msg), "little") % L
    R = encode_point(scalarmult(r, B))
    k = int.from_bytes(sha512(R + A + msg), "little") % L
    S = (r + k * a) % L
    return R + S.to_bytes(32, "little")


def verify(sig, msg, pk):
    """RFC 8032 section 5.1.7 (cofactored check omitted). Host-side sanity only."""
    if len(sig) != 64 or len(pk) != 32:
        return False
    S = int.from_bytes(sig[32:], "little")
    if S >= L:
        return False
    try:
        A = _decode_point(pk)
        R = _decode_point(sig[:32])
    except ValueError:
        return False
    k = int.from_bytes(sha512(sig[:32] + pk + msg), "little") % L
    lhs = scalarmult(S, B)
    rhs = point_add(scalarmult(k, A), R)
    return lhs == rhs


# ---- the firmware descriptor ------------------------------------------------
def descriptor(image_len, image_sha256):
    """image_len(4B LE) || SHA-256(image) - the bytes QBOOT verifies."""
    if len(image_sha256) != 32:
        raise ValueError("SHA-256 digest must be 32 bytes")
    return image_len.to_bytes(4, "little") + image_sha256


def sign_descriptor(seed, image_len, image_sha256):
    """Sign the firmware descriptor and return the 64-byte signature."""
    return sign(seed, descriptor(image_len, image_sha256))


# ---- key files --------------------------------------------------------------
def load_seed_hex(path):
    """Load a 32-byte Ed25519 seed from a hex text file.

    Accepts the Quilla private.hex layout: 64 hex characters, optional
    whitespace/newline, '#' comment lines ignored.
    """
    with open(path, "r", encoding="ascii") as f:
        raw = []
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                raw.append(line)
    text = "".join(raw)
    try:
        seed = bytes.fromhex(text)
    except ValueError:
        raise ValueError("%s is not valid hex" % path)
    if len(seed) != 32:
        raise ValueError(
            "%s must hold a 32-byte seed (64 hex chars), got %d bytes"
            % (path, len(seed)))
    return seed


def keygen(directory):
    """Generate a keypair. Returns (seed, public_key)."""
    os.makedirs(directory, exist_ok=True)
    seed = os.urandom(32)
    pk = pubkey_from_seed(seed)
    with open(os.path.join(directory, "private.hex"), "w", encoding="ascii") as f:
        f.write(seed.hex() + "\n")
    with open(os.path.join(directory, "public.hex"), "w", encoding="ascii") as f:
        f.write(pk.hex() + "\n")
    return seed, pk


def pubkey_macro(pk):
    """The -DQUILLA_SECURE_BOOT_PUBKEY={...} line for the QBOOT build."""
    return "-DQUILLA_SECURE_BOOT_PUBKEY={%s}" % ",".join("0x%02x" % b for b in pk)


# ---- self test (RFC 8032 section 7.1) ---------------------------------------
_VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
     "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555"
     "fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
     "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da0"
     "85ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
     "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac1"
     "8ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]


def self_test():
    """Check against the RFC 8032 vectors. Returns a list of failures."""
    failures = []
    for i, (sk_hex, pk_hex, msg_hex, sig_hex) in enumerate(_VECTORS, 1):
        sk = bytes.fromhex(sk_hex)
        want_pk = bytes.fromhex(pk_hex)
        want_sig = bytes.fromhex(sig_hex)
        msg = bytes.fromhex(msg_hex)
        if pubkey_from_seed(sk) != want_pk:
            failures.append("RFC 8032 vector %d: public key mismatch" % i)
            continue
        if sign(sk, msg) != want_sig:
            failures.append("RFC 8032 vector %d: signature mismatch" % i)
            continue
        if not verify(want_sig, msg, want_pk):
            failures.append("RFC 8032 vector %d: verify rejected a good signature" % i)
    sk = bytes.fromhex(_VECTORS[1][0])
    pk = bytes.fromhex(_VECTORS[1][1])
    if verify(sign(sk, b"other"), b"different", pk):
        failures.append("tampered message was accepted")
    return failures
