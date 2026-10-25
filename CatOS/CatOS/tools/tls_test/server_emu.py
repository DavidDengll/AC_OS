#!/usr/bin/env python3
"""Emulate the TLS 1.2 server side of a handshake, independently of the C code.

Inputs (written by tools/tls_test/test_handshake.c phase1):
    client_out.txt : key=hex lines (client_random, server_random, premaster,
                     rsa_ct, client_hello, client_key_exchange, master_secret,
                     client_finished, sealed_client_finished,
                     expected_server_finished, client_mac, client_key,
                     server_mac, server_key)
    hs_key.txt     : n / e / d of the RSA key pair (hex)

What this checks (all with Python's own hashlib/hmac + a validated AES):
    1. RSA: decrypt rsa_ct with d, validate PKCS#1 v1.5 padding, recover premaster
    2. master secret  = PRF(premaster, "master secret", client_random||server_random)
    3. key block      = PRF(master, "key expansion", server_random||client_random)
    4. client Finished verify_data over SHA256(ClientHello||ClientKeyExchange)
    5. decrypt the client's encrypted Finished record: padding, HMAC-SHA1 MAC, value
    6. server Finished = PRF(master, "server finished", transcript incl. client Finished)
    7. seal a server Finished record for the C side to decrypt (phase 2)

Output: server_out.txt (key=hex), exit code 0 only if every check passed.
"""

import hashlib
import hmac
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "crypto_test"))
import gen_gcm_vectors as aesref          # validated AES-128 (FIPS-197 self-checked)

HANDSHAKE = 22
FINISHED = 20
CCS = 20
VERSION = b"\x03\x03"

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
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k] = v
    return out


def kv_bytes(d, k):
    return bytes.fromhex(d[k])


# ------------------------------------------------------------------ TLS bits
def prf(secret, label, seed, length):
    """P_SHA256 (RFC 5246). Independent of the C implementation."""
    full = label.encode() + seed
    a = hmac.new(secret, full, hashlib.sha256).digest()
    out = b""
    while len(out) < length:
        out += hmac.new(secret, a + full, hashlib.sha256).digest()
        a = hmac.new(secret, a, hashlib.sha256).digest()
    return out[:length]


def cbc_encrypt(key, iv, data):
    assert len(data) % 16 == 0
    out = b""
    prev = iv
    for off in range(0, len(data), 16):
        blk = bytes(x ^ y for x, y in zip(data[off:off + 16], prev))
        prev = aesref.aes_encrypt_block(key, blk)
        out += prev
    return out


def cbc_decrypt(key, iv, data):
    assert len(data) % 16 == 0
    out = b""
    prev = iv
    for off in range(0, len(data), 16):
        blk = data[off:off + 16]
        dec = aesref.aes_decrypt_block(key, blk)
        out += bytes(x ^ y for x, y in zip(dec, prev))
        prev = blk
    return out


def record_mac(mac_key, seq, ctype, fragment):
    hdr = seq.to_bytes(8, "big") + bytes([ctype]) + VERSION + \
          len(fragment).to_bytes(2, "big")
    return hmac.new(mac_key, hdr + fragment, hashlib.sha1).digest()


def unseal(mac_key, enc_key, payload, ctype, seq):
    """payload = explicit_iv(16) || ciphertext; returns fragment or None."""
    if len(payload) < 16 + 16:
        return None
    iv, ct = payload[:16], payload[16:]
    if len(ct) % 16 != 0:
        return None
    plain = cbc_decrypt(enc_key, iv, ct)
    pad_len = plain[-1] + 1
    if pad_len > 16 or pad_len > len(plain):
        return None
    if any(b != pad_len - 1 for b in plain[-pad_len:]):
        return None
    body = plain[:-pad_len]
    mac, frag = body[-20:], body[:-20]
    if not hmac.compare_digest(record_mac(mac_key, seq, ctype, frag), mac):
        return None
    return frag


def seal(mac_key, enc_key, fragment, ctype, seq):
    mac = record_mac(mac_key, seq, ctype, fragment)
    body = fragment + mac
    pad_len = 16 - (len(body) % 16)
    body += bytes([pad_len - 1]) * pad_len
    iv = bytes((0xA0 + i) & 0xFF for i in range(16))
    return iv + cbc_encrypt(enc_key, iv, body)


def main():
    cfile = sys.argv[1] if len(sys.argv) > 1 else "client_out.txt"
    kfile = sys.argv[2] if len(sys.argv) > 2 else "hs_key.txt"
    sfile = sys.argv[3] if len(sys.argv) > 3 else "server_out.txt"

    c = read_kv(cfile)
    k = read_kv(kfile)
    n = int(k["n"], 16)
    d = int(k["d"], 16)

    client_random = kv_bytes(c, "client_random")
    server_random = kv_bytes(c, "server_random")
    premaster_c = kv_bytes(c, "premaster")
    rsa_ct = kv_bytes(c, "rsa_ct")
    client_hello = kv_bytes(c, "client_hello")
    cke = kv_bytes(c, "client_key_exchange")

    # ---- 1. RSA decrypt + PKCS#1 v1.5 padding ----
    em = pow(int.from_bytes(rsa_ct, "big"), d, n).to_bytes(len(rsa_ct), "big")
    check(em[0] == 0 and em[1] == 2, "RSA block header 00 02")
    sep = em.find(b"\x00", 2)
    check(sep >= 10, "PKCS#1 v1.5 PS separator found")
    premaster_s = em[sep + 1:]
    check(premaster_s == premaster_c, "decrypted pre-master matches client's")
    check(len(premaster_s) == 48, "pre-master is 48 bytes")

    # ---- 2. master secret ----
    master_s = prf(premaster_s, "master secret", client_random + server_random, 48)
    check(master_s == kv_bytes(c, "master_secret"), "master secret matches")

    # ---- 3. key block ----
    kb = prf(master_s, "key expansion", server_random + client_random, 104)
    cli_mac, srv_mac = kb[0:20], kb[20:40]
    cli_key, srv_key = kb[40:56], kb[56:72]
    check(cli_mac == kv_bytes(c, "client_mac"), "client_write_MAC matches")
    check(cli_key == kv_bytes(c, "client_key"), "client_write_key matches")
    check(srv_mac == kv_bytes(c, "server_mac"), "server_write_MAC matches")
    check(srv_key == kv_bytes(c, "server_key"), "server_write_key matches")

    # ---- 4. client Finished ----
    transcript1 = hashlib.sha256(client_hello + cke).digest()
    cli_fin = prf(master_s, "client finished", transcript1, 12)
    fin_msg = bytes([FINISHED, 0, 0, 12]) + cli_fin
    check(fin_msg == kv_bytes(c, "client_finished"), "client Finished message matches")

    # ---- 5. decrypt the client's encrypted Finished record ----
    sealed = kv_bytes(c, "sealed_client_finished")
    frag = unseal(cli_mac, cli_key, sealed, HANDSHAKE, 0)
    check(frag is not None, "client record decrypted and MAC verified")
    if frag is not None:
        check(frag == fin_msg, "decrypted fragment equals client Finished")

    # ---- 6. server Finished ----
    transcript2 = hashlib.sha256(client_hello + cke + fin_msg).digest()
    srv_fin = prf(master_s, "server finished", transcript2, 12)
    check(srv_fin == kv_bytes(c, "expected_server_finished"),
          "server Finished matches client's expectation")
    srv_msg = bytes([FINISHED, 0, 0, 12]) + srv_fin

    # ---- 7. seal a server Finished record for phase 2 ----
    sealed_srv = seal(srv_mac, srv_key, srv_msg, HANDSHAKE, 0)

    with open(sfile, "w", encoding="ascii", newline="\n") as f:
        f.write("server_finished=%s\n" % srv_msg.hex())
        f.write("sealed_server_finished=%s\n" % sealed_srv.hex())
        f.write("ok=%d\n" % (1 if not errors else 0))

    print("  server emulation: %d check(s) failed" % len(errors))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
