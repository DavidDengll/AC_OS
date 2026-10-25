#!/usr/bin/env python3
"""Server side of a TLS 1.2 handshake for tools/tls_test/test_hs2.c.

Modes
  flight1  : build the server's first flight (ServerHello, Certificate split
             across TWO records, ServerHelloDone) for the fixed client_random,
             and emit it as a C header (hs2_flight1.h).
  verify   : parse the client flight the C driver produced (client_flight.txt),
             decrypt ClientKeyExchange, derive keys, unseal the Finished record
             and check verify_data against an independent computation.

The server's crypto uses Python's hashlib/hmac plus a *validated* pure-Python
AES (imported from tools/crypto_test), i.e. an independent implementation.
"""

import hashlib
import hmac
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "crypto_test"))
import gen_gcm_vectors as aesref

HANDSHAKE = 22
CCS = 20
VERSION = b"\x03\x03"
SUITE = 0x002F

# 与 test_hs2.c 里保持一致
CLIENT_RANDOM = bytes((0x10 + i) & 0xFF for i in range(32))
PREMASTER = bytes([3, 3]) + bytes((0x30 + i) & 0xFF for i in range(2, 48))
SERVER_RANDOM = bytes((0x80 + i) & 0xFF for i in range(32))
SNI = "handshake.test"

errors = []


def check(cond, msg):
    if not cond:
        errors.append(msg)
        print("  [FAIL] %s" % msg)
    return cond


def read_kv(path):
    out = {}
    with open(path, "r", encoding="ascii") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                out[k] = v
    return out


def record(ctype, payload):
    return bytes([ctype, 3, 3, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload


def hs(mtype, body):
    return bytes([mtype]) + len(body).to_bytes(3, "big") + body


def prf(secret, label, seed, length):
    full = label.encode() + seed
    a = hmac.new(secret, full, hashlib.sha256).digest()
    out = b""
    while len(out) < length:
        out += hmac.new(secret, a + full, hashlib.sha256).digest()
        a = hmac.new(secret, a, hashlib.sha256).digest()
    return out[:length]


def cbc_decrypt(key, iv, data):
    out = b""
    prev = iv
    for off in range(0, len(data), 16):
        blk = data[off:off + 16]
        dec = aesref.aes_decrypt_block(key, blk)
        out += bytes(x ^ y for x, y in zip(dec, prev))
        prev = blk
    return out


def record_mac(mac_key, seq, ctype, fragment):
    hdr = seq.to_bytes(8, "big") + bytes([ctype]) + VERSION + len(fragment).to_bytes(2, "big")
    return hmac.new(mac_key, hdr + fragment, hashlib.sha1).digest()


def unseal(mac_key, enc_key, payload, ctype, seq):
    if len(payload) < 32:
        return None
    iv, ct = payload[:16], payload[16:]
    if len(ct) % 16:
        return None
    plain = cbc_decrypt(enc_key, iv, ct)
    pad = plain[-1] + 1
    if pad > 16 or pad > len(plain) or any(b != pad - 1 for b in plain[-pad:]):
        return None
    body = plain[:-pad]
    mac, frag = body[-20:], body[:-20]
    if not hmac.compare_digest(record_mac(mac_key, seq, ctype, frag), mac):
        return None
    return frag


def gcm_encrypt(key, nonce, aad, plain):
    h = int.from_bytes(aesref.aes_encrypt_block(key, bytes(16)), "big")
    j0 = nonce + b"\x00\x00\x00\x01"
    ctr = aesref.inc32(j0)
    ct = bytearray()
    for off in range(0, len(plain), 16):
        ks = aesref.aes_encrypt_block(key, ctr)
        chunk = plain[off:off + 16]
        ct.extend(bytes(c ^ k for c, k in zip(chunk, ks)))
        ctr = aesref.inc32(ctr)
    ct = bytes(ct)
    s = aesref.ghash(h, aad, ct)
    tag = (s ^ int.from_bytes(aesref.aes_encrypt_block(key, j0), "big")).to_bytes(16, "big")
    return ct, tag


def gcm_decrypt(key, nonce, aad, ct, tag):
    h = int.from_bytes(aesref.aes_encrypt_block(key, bytes(16)), "big")
    j0 = nonce + b"\x00\x00\x00\x01"
    s = aesref.ghash(h, aad, ct)
    want = (s ^ int.from_bytes(aesref.aes_encrypt_block(key, j0), "big")).to_bytes(16, "big")
    if not hmac.compare_digest(want, tag):
        return None
    ctr = aesref.inc32(j0)
    out = bytearray()
    for off in range(0, len(ct), 16):
        ks = aesref.aes_encrypt_block(key, ctr)
        chunk = ct[off:off + 16]
        out.extend(bytes(c ^ k for c, k in zip(chunk, ks)))
        ctr = aesref.inc32(ctr)
    return bytes(out)


def suite_keyblock(master, is_gcm):
    if is_gcm:
        kb = prf(master, "key expansion", SERVER_RANDOM + CLIENT_RANDOM, 40)
        return None, None, kb[0:16], kb[16:32], kb[32:36], kb[36:40]
    kb = prf(master, "key expansion", SERVER_RANDOM + CLIENT_RANDOM, 104)
    return kb[0:20], kb[20:40], kb[40:56], kb[56:72], None, None


def unseal_any(mac_key, enc_key, fixed_iv, payload, ctype, seq, is_gcm):
    if is_gcm:
        if len(payload) < 24:
            return None
        explicit, ct, tag = payload[:8], payload[8:-16], payload[-16:]
        nonce = fixed_iv + explicit
        aad = seq.to_bytes(8, "big") + bytes([ctype]) + VERSION + len(ct).to_bytes(2, "big")
        return gcm_decrypt(enc_key, nonce, aad, ct, tag)
    return unseal(mac_key, enc_key, payload, ctype, seq)

def mode_flight1(out_path, suite=SUITE):
    certs = read_kv(os.path.join(HERE, "certs_py.txt"))
    leaf = bytes.fromhex(certs["leaf"])
    root = bytes.fromhex(certs["root"])

    sh_body = bytes([3, 3]) + SERVER_RANDOM + bytes([0]) + suite.to_bytes(2, "big") + bytes([0]) + bytes([0, 0])
    sh = hs(2, sh_body)

    entry = lambda der: len(der).to_bytes(3, "big") + der
    cert_body = len(entry(leaf) + entry(root)).to_bytes(3, "big") + entry(leaf) + entry(root)
    cert = hs(11, cert_body)
    done = hs(14, b"")

    # Certificate 拆到两条记录里, 用来测试客户端的跨记录重组
    half = len(cert) // 2
    rec1 = record(HANDSHAKE, sh)
    rec2 = record(HANDSHAKE, cert[:half])
    rec3 = record(HANDSHAKE, cert[half:] + done)

    stream = rec1 + rec2 + rec3

    tag = "%04x" % suite
    lines = [
        "/* generated by gen_hs2.py flight1 - do not edit */",
        "#ifndef _HS2_FLIGHT1_%s_H_" % tag,
        "#define _HS2_FLIGHT1_%s_H_" % tag,
        'static const char *hs2_flight_%s_hex = "%s";' % (tag, stream.hex()),
        "#define HS2_RECORD_COUNT 3",
        "#define HS2_CLIENT_RANDOM_HEX \"%s\"" % CLIENT_RANDOM.hex(),
        "#define HS2_SERVER_RANDOM_HEX \"%s\"" % SERVER_RANDOM.hex(),
        "#define HS2_PREMASTER_HEX \"%s\"" % PREMASTER.hex(),
        "#define HS2_SUITE_%s 0x%04X" % (tag, suite),

        "#endif",
    ]
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("  flight1: %d records, %d bytes, suite 0x%04X -> %s" % (3, len(stream), suite, out_path))
    return 0


def mode_verify(client_path, suite=SUITE):
    certs = read_kv(os.path.join(HERE, "certs_py.txt"))
    n = int(certs["leaf_n"], 16)
    d = int(certs["leaf_d"], 16)
    leaf = bytes.fromhex(certs["leaf"])
    root = bytes.fromhex(certs["root"])

    data = bytes.fromhex(open(client_path, "r", encoding="ascii").read().strip())

    # ---- 解析客户端记录: CKE (明文) / CCS / Finished (加密) ----
    pos = 0
    recs = []
    while pos < len(data):
        if pos + 5 > len(data):
            check(False, "client record header truncated")
            break
        ctype = data[pos]
        rlen = (data[pos + 3] << 8) | data[pos + 4]
        payload = data[pos + 5:pos + 5 + rlen]
        if len(payload) != rlen:
            check(False, "client record payload truncated")
            break
        recs.append((ctype, payload))
        pos += 5 + rlen

    check(len(recs) == 3, "client sent exactly 3 records (got %d)" % len(recs))
    check(recs[0][0] == HANDSHAKE, "record 1 is handshake (ClientKeyExchange)")
    check(recs[1][0] == CCS and recs[1][1] == b"\x01", "record 2 is ChangeCipherSpec")
    check(recs[2][0] == HANDSHAKE, "record 3 is handshake (Finished)")

    # ---- ClientKeyExchange ----
    cke = recs[0][1]
    check(len(cke) > 4 and cke[0] == 16, "CKE message type 16")
    ckelen = (cke[1] << 16) | (cke[2] << 8) | cke[3]
    check(4 + ckelen == len(cke), "CKE length matches")
    body = cke[4:]
    enc_len = (body[0] << 8) | body[1]
    ct = body[2:2 + enc_len]
    check(enc_len == 256, "CKE ciphertext is 256 bytes")

    # ---- 解密 premaster (PKCS#1 v1.5) ----
    em = pow(int.from_bytes(ct, "big"), d, n).to_bytes(enc_len, "big")
    check(em[0] == 0 and em[1] == 2, "CKE padded block header 00 02")
    sep = em.find(b"\x00", 2)
    check(sep >= 10, "CKE padding separator")
    pm = em[sep + 1:]
    check(pm == PREMASTER, "recovered pre-master matches the fixed test value")

    # ---- 密钥派生 ----
    master = prf(pm, "master secret", CLIENT_RANDOM + SERVER_RANDOM, 48)
    is_gcm = (suite == 0x009C)
    cli_mac, srv_mac, cli_key, srv_key, cli_iv, srv_iv = suite_keyblock(master, is_gcm)

    # ---- transcript 与 client Finished ----
    sh = hs(2, bytes([3, 3]) + SERVER_RANDOM + bytes([0]) + suite.to_bytes(2, "big") + bytes([0]) + bytes([0, 0]))
    entry = lambda der: len(der).to_bytes(3, "big") + der
    cert_body = len(entry(leaf) + entry(root)).to_bytes(3, "big") + entry(leaf) + entry(root)
    cert = hs(11, cert_body)
    done = hs(14, b"")

    # 客户端的 ClientHello 由 transcript 顺序推断: 这里用其 ClientHello 记录内容
    # (test_hs2.c 会把 ClientHello 记录也写进文件, 见下)
    ch_record_len = None
    ch = None
    hellos = open(os.path.join(HERE, "client_hello.bin"), "r", encoding="ascii").read().strip()
    ch_data = bytes.fromhex(hellos)
    ch = ch_data[5:]                      # 去掉记录头, 取握手消息
    transcript = hashlib.sha256(ch + sh + cert + done + cke).digest()
    expected_fin = prf(master, "client finished", transcript, 12)

    frag = unseal_any(cli_mac, cli_key, cli_iv, recs[2][1], HANDSHAKE, 0, is_gcm)
    check(frag is not None, "client Finished record decrypted and MAC verified")
    if frag is not None:
        check(len(frag) == 16 and frag[0] == 20, "client Finished message shape")
        check(frag[4:] == expected_fin, "client verify_data matches independent computation")

    print("  verify: %d check(s) failed" % len(errors))
    return 0 if not errors else 1


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    if sys.argv[1] == "flight1":
        out = sys.argv[2] if len(sys.argv) > 2 else "hs2_flight1.h"
        suite = int(sys.argv[3], 16) if len(sys.argv) > 3 else SUITE
        return mode_flight1(out, suite)
    if sys.argv[1] == "verify":
        path = sys.argv[2] if len(sys.argv) > 2 else "client_flight.txt"
        suite = int(sys.argv[3], 16) if len(sys.argv) > 3 else SUITE
        return mode_verify(path, suite)
    print("unknown mode")
    return 1


if __name__ == "__main__":
    sys.exit(main())
