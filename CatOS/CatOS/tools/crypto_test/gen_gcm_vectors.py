#!/usr/bin/env python3
"""Independent pure-Python AES-128 + GHASH + GCM, used to generate test vectors.

Why pure Python: .NET Framework 4.x has no AesGcm, and Python's stdlib has no AES,
so this file is a *second, independent implementation* of AES and GCM.  It is
self-checked against:

  * FIPS-197 Appendix C.1 (AES-128 single block)
  * NIST GCM test case 1 and 2 (published constants)

Only if those pass does it emit vectors, so a bug here fails loudly instead of
silently blessing a matching bug in the C code.

Usage: python gen_gcm_vectors.py > expected_gcm.h
"""

import sys

# ---------------------------------------------------------------- AES-128 ---


def xtime(a):
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def gmul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        a = xtime(a)
        b >>= 1
    return p


def gpow(a, n):
    r = 1
    while n:
        if n & 1:
            r = gmul(r, a)
        a = gmul(a, a)
        n >>= 1
    return r


def rotl8(x, n):
    x &= 0xFF
    return ((x << n) | (x >> (8 - n))) & 0xFF


def build_sbox():
    sb = [0] * 256
    ib = [0] * 256
    for i in range(256):
        x = 0 if i == 0 else gpow(i, 254)
        s = x ^ rotl8(x, 1) ^ rotl8(x, 2) ^ rotl8(x, 3) ^ rotl8(x, 4) ^ 0x63
        sb[i] = s & 0xFF
        ib[s & 0xFF] = i
    return sb, ib


SBOX, ISBOX = build_sbox()


def expand_key(key):
    assert len(key) == 16
    w = list(key)
    rcon = 1
    for i in range(16, 176, 4):
        t = w[i - 4:i]
        if i % 16 == 0:
            t = [SBOX[t[1]] ^ rcon, SBOX[t[2]], SBOX[t[3]], SBOX[t[0]]]
            rcon = xtime(rcon)
        for k in range(4):
            w.append(w[i - 16 + k] ^ t[k])
    return w


def shift_rows(s, inv=False):
    out = [0] * 16
    for r in range(4):
        for c in range(4):
            src = (c + (4 - r)) % 4 if inv else (c + r) % 4
            out[r + 4 * c] = s[r + 4 * src]
    return out


def mix_columns(s, inv=False):
    out = [0] * 16
    for c in range(4):
        a = s[4 * c:4 * c + 4]
        if not inv:
            t = a[0] ^ a[1] ^ a[2] ^ a[3]
            out[4 * c + 0] = a[0] ^ t ^ gmul(a[0] ^ a[1], 2)
            out[4 * c + 1] = a[1] ^ t ^ gmul(a[1] ^ a[2], 2)
            out[4 * c + 2] = a[2] ^ t ^ gmul(a[2] ^ a[3], 2)
            out[4 * c + 3] = a[3] ^ t ^ gmul(a[3] ^ a[0], 2)
        else:
            out[4 * c + 0] = gmul(a[0], 14) ^ gmul(a[1], 11) ^ gmul(a[2], 13) ^ gmul(a[3], 9)
            out[4 * c + 1] = gmul(a[0], 9) ^ gmul(a[1], 14) ^ gmul(a[2], 11) ^ gmul(a[3], 13)
            out[4 * c + 2] = gmul(a[0], 13) ^ gmul(a[1], 9) ^ gmul(a[2], 14) ^ gmul(a[3], 11)
            out[4 * c + 3] = gmul(a[0], 11) ^ gmul(a[1], 13) ^ gmul(a[2], 9) ^ gmul(a[3], 14)
    return [x & 0xFF for x in out]


def add_round_key(s, w, rnd):
    return [s[i] ^ w[rnd * 16 + i] for i in range(16)]


def aes_encrypt_block(key, block):
    w = expand_key(key)
    s = add_round_key(list(block), w, 0)
    for rnd in range(1, 10):
        s = [SBOX[x] for x in s]
        s = shift_rows(s)
        s = mix_columns(s)
        s = add_round_key(s, w, rnd)
    s = [SBOX[x] for x in s]
    s = shift_rows(s)
    return bytes(add_round_key(s, w, 10))


def aes_decrypt_block(key, block):
    w = expand_key(key)
    s = add_round_key(list(block), w, 10)
    for rnd in range(9, 0, -1):
        s = shift_rows(s, inv=True)
        s = [ISBOX[x] for x in s]
        s = add_round_key(s, w, rnd)
        s = mix_columns(s, inv=True)
    s = shift_rows(s, inv=True)
    s = [ISBOX[x] for x in s]
    return bytes(add_round_key(s, w, 0))


# ------------------------------------------------------------------ GCM -----

R128 = 0xE1000000000000000000000000000000


def gf128_mul(x, y):
    z = 0
    v = y
    for i in range(128):
        if (x >> (127 - i)) & 1:
            z ^= v
        if v & 1:
            v = (v >> 1) ^ R128
        else:
            v >>= 1
    return z


def ghash(h, aad, ct):
    y = 0
    for data in (aad, ct):
        for off in range(0, len(data), 16):
            blk = data[off:off + 16]
            blk = blk + b"\x00" * (16 - len(blk))
            y = gf128_mul(y ^ int.from_bytes(blk, "big"), h)
    lb = (len(aad) * 8).to_bytes(8, "big") + (len(ct) * 8).to_bytes(8, "big")
    return gf128_mul(y ^ int.from_bytes(lb, "big"), h)


def inc32(counter):
    v = (int.from_bytes(counter[-4:], "big") + 1) & 0xFFFFFFFF
    return counter[:-4] + v.to_bytes(4, "big")


def gcm_encrypt(key, nonce, aad, pt):
    assert len(nonce) == 12
    h = int.from_bytes(aes_encrypt_block(key, bytes(16)), "big")
    j0 = nonce + b"\x00\x00\x00\x01"
    ctr = inc32(j0)
    ct = bytearray()
    for off in range(0, len(pt), 16):
        ks = aes_encrypt_block(key, ctr)
        chunk = pt[off:off + 16]
        ct.extend(bytes(c ^ k for c, k in zip(chunk, ks)))
        ctr = inc32(ctr)
    ct = bytes(ct)
    s = ghash(h, aad, ct)
    tag = (s ^ int.from_bytes(aes_encrypt_block(key, j0), "big")).to_bytes(16, "big")
    return ct, tag


# ------------------------------------------------------------- self-check ---

def hexs(b):
    return b.hex()


def selfcheck():
    # FIPS-197 C.1
    key = bytes(range(16))
    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    ct = aes_encrypt_block(key, pt)
    assert hexs(ct) == "69c4e0d86a7b0430d8cdb78070b4c55a", hexs(ct)
    assert aes_decrypt_block(key, ct) == pt

    # NIST GCM test case 1
    z16 = bytes(16)
    z12 = bytes(12)
    c1, t1 = gcm_encrypt(z16, z12, b"", b"")
    assert hexs(c1) == "" and hexs(t1) == "58e2fccefa7e3061367f1d57a4e7455a", hexs(t1)

    # NIST GCM test case 2
    c2, t2 = gcm_encrypt(z16, z12, b"", z16)
    assert hexs(c2) == "0388dace60b6a392f328c2b971b2fe78", hexs(c2)
    assert hexs(t2) == "ab6e47d42cec13bdf53a67b21257bddf", hexs(t2)


def bytes_of(n, start=0):
    return bytes(((start + i) % 251) for i in range(n))


def c_str(s):
    return '"' + s + '"'


def main():
    selfcheck()

    cases = [
        ("gcm_empty", 0, 0),
        ("gcm_16", 16, 0),
        ("gcm_17_aad20", 17, 20),
        ("gcm_100_aad32", 100, 32),
        ("gcm_0_aad16", 0, 16),
        ("gcm_255_aad1", 255, 1),
    ]

    out = []
    out.append("/* generated by gen_gcm_vectors.py (independent Python AES/GCM, FIPS-197 + NIST self-checked) */")
    out.append("static const GCM_VEC gcm_vecs[] = {")
    n = 0
    for name, pt_len, aad_len in cases:
        key = bytes_of(16, 100 + n)
        nonce = bytes_of(12, 200 + n)
        pt = bytes_of(pt_len, 10 + n)
        aad = bytes_of(aad_len, 50 + n)
        ct, tag = gcm_encrypt(key, nonce, aad, pt)
        out.append('  { %s, %s, %s, %s, %s, %s, %s },' % (
            c_str(name), c_str(hexs(key)), c_str(hexs(nonce)), c_str(hexs(aad)),
            c_str(hexs(pt)), c_str(hexs(ct)), c_str(hexs(tag))))
        n += 1
    out.append("};")
    text = "\n".join(out) + "\n"
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("written: %s (%d bytes)" % (sys.argv[1], len(text)))
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
