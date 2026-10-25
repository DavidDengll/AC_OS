#!/usr/bin/env python3
"""Generate the baked-in data for kernel/netmock.c (browser https:// mock).

Produces netmock_data.h containing:
  - server first flight (ServerHello + Certificate split across 2 records
    + ServerHelloDone), suite TLS_RSA_WITH_AES_128_CBC_SHA
  - two encrypted application-data records carrying an HTTP/1.1 response
    whose body showcases the new renderer features
  - the trust anchor (root certificate DER) and the fixed client random /
    pre-master used by the driver

All crypto is done with Python's hashlib/hmac + a pure-Python AES that has
been validated against FIPS-197 and NIST GCM test vectors.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "crypto_test"))
import gen_gcm_vectors as aesref

import hashlib
import hmac

HANDSHAKE = 22
CCS = 20
APPDATA = 23
VERSION = b"\x03\x03"
SUITE = 0x002F

CLIENT_RANDOM = bytes((0x41 + i) & 0xFF for i in range(32))
SERVER_RANDOM = bytes((0x5A + i) & 0xFF for i in range(32))
PREMASTER = bytes([3, 3]) + bytes((0x70 + i) & 0xFF for i in range(2, 48))


def prf(secret, label, seed, length):
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


def record_mac(mac_key, seq, ctype, fragment):
    hdr = seq.to_bytes(8, "big") + bytes([ctype]) + VERSION + \
          len(fragment).to_bytes(2, "big")
    return hmac.new(mac_key, hdr + fragment, hashlib.sha1).digest()


def seal(mac_key, enc_key, fragment, ctype, seq):
    mac = record_mac(mac_key, seq, ctype, fragment)
    body = fragment + mac
    pad = 16 - (len(body) % 16)
    body += bytes([pad - 1]) * pad
    iv = bytes((0xC0 + i) & 0xFF for i in range(16))
    return iv + cbc_encrypt(enc_key, iv, body)


def record(ctype, payload):
    return bytes([ctype, 3, 3, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload


def hs(mtype, body):
    return bytes([mtype]) + len(body).to_bytes(3, "big") + body


def read_kv(path):
    out = {}
    with open(path, "r", encoding="ascii") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                out[k] = v
    return out


HTML_BODY = (
    "<html><head><title>NetMock Page</title></head><body>"
    "<h1>HTTPS Pipeline Works</h1>"
    "<p>This page travelled through the real TLS record layer: "
    "AES-128-CBC encrypted, HMAC-SHA1 authenticated, then decrypted "
    "by the CatOS kernel.</p>"
    "<hr>"
    "<h1>Colour test</h1>"
    "<p><font color=\"red\">red text, </font>"
    "<font color=\"green\">green text, </font>"
    "<font color=\"blue\">blue text, </font>"
    "<font color=\"orange\">orange text.</font></p>"
    "<h1>List test</h1>"
    "<ul>"
    "<li>first list item</li>"
    "<li>second list item with <b>bold</b> inside</li>"
    "<li>third item mentions the <a href=\"INDEX.HTM\">local index</a></li>"
    "</ul>"
    "<h1>Image test</h1>"
    "<p><img src=\"LOGO.BMP\"></p>"
    "<p>End of mock page.</p>"
    "</body></html>"
)


def main():
    certs = read_kv(os.path.join(HERE, "certs_py.txt"))
    root = bytes.fromhex(certs["root"])
    leaf = bytes.fromhex(certs["leaf"])

    # ---- server flight ----
    sh_body = bytes([3, 3]) + SERVER_RANDOM + bytes([0]) + \
        SUITE.to_bytes(2, "big") + bytes([0]) + bytes([0, 0])
    entry = lambda der: len(der).to_bytes(3, "big") + der
    cert_body = len(entry(leaf) + entry(root)).to_bytes(3, "big") + \
        entry(leaf) + entry(root)

    recs = []
    recs.append(record(HANDSHAKE, hs(2, sh_body)))
    cert = hs(11, cert_body)
    half = len(cert) // 2
    recs.append(record(HANDSHAKE, cert[:half]))
    recs.append(record(HANDSHAKE, cert[half:] + hs(14, b"")))
    flight1 = recs[0] + recs[1] + recs[2]

    # ---- keys (same derivation as the driver) ----
    master = prf(PREMASTER, "master secret", CLIENT_RANDOM + SERVER_RANDOM, 48)
    kb = prf(master, "key expansion", SERVER_RANDOM + CLIENT_RANDOM, 104)
    srv_mac, srv_key = kb[20:40], kb[56:72]

    http_resp = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n"
        "\r\n" % len(HTML_BODY)
    ).encode() + HTML_BODY.encode()

    # 两个应用数据记录 (模拟分片到达)    cut = http_resp.find(b"<hr>") + 4
    if cut < 40:
        cut = len(http_resp) // 2
    frag1, frag2 = http_resp[:cut], http_resp[cut:]

    rec_app1 = record(APPDATA, seal(srv_mac, srv_key, frag1, APPDATA, 0))
    rec_app2 = record(APPDATA, seal(srv_mac, srv_key, frag2, APPDATA, 1))

    out = []
    out.append("/* generated by gen_netmock_data.py - do not edit */")
    out.append("#ifndef _NETMOCK_DATA_H_")
    out.append("#define _NETMOCK_DATA_H_")
    out.append('static const char *nm_client_random_hex = "%s";' % CLIENT_RANDOM.hex())
    out.append('static const char *nm_premaster_hex = "%s";' % PREMASTER.hex())
    out.append('static const char *nm_trust_hex = "%s";' % root.hex())
    out.append("#define NM_TRUST_LEN %d" % len(root))
    out.append('static const char *nm_flight1_hex = "%s";' % flight1.hex())
    out.append('static const char *nm_app1_hex = "%s";' % rec_app1.hex())
    out.append('static const char *nm_app2_hex = "%s";' % rec_app2.hex())
    out.append("#define NM_SNI \"mock.catos.test\"")
    out.append("#endif")

    text = "\n".join(out) + "\n"
    dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "..", "include", "netmock_data.h")
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("written: %s (%d bytes)" % (dest, len(text)))
    print("  flight1 %d B, app1 %d B (frag %d B), app2 %d B (frag %d B)"
          % (len(flight1), len(rec_app1), len(frag1), len(rec_app2), len(frag2)))


if __name__ == "__main__":
    main()
