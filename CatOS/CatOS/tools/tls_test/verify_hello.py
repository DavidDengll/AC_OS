#!/usr/bin/env python3
"""Check the ClientHello that the C code produced (tools/tls_test/test_tls.c).

Parses client_hello.txt (hex) with an independent implementation and asserts:
  * record header: type 22, version 3.3, length matches payload
  * handshake header: type 1 (ClientHello), length == remaining bytes
  * body: version 3.3, 32-byte random, empty session id
  * cipher suites: even length, non-empty, contains the two suites we offer
  * compression: exactly [0]
  * extensions: SNI extension #0 present with host_name == expected

Exit code 0 = all good.
"""

import sys

expected_sni = "example.com"
expected_suites = (0x002F, 0x009C)


def fail(msg):
    print("  [FAIL] %s" % msg)
    sys.exit(1)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "client_hello.txt"
    hexstr = open(path, "r", encoding="ascii").read().strip()
    data = bytes.fromhex(hexstr)

    if len(data) < 5:
        fail("record too short")
    if data[0] != 22:
        fail("record type %d, expected 22 (handshake)" % data[0])
    if data[1] != 3 or data[2] != 3:
        fail("record version %d.%d, expected 3.3" % (data[1], data[2]))
    rlen = (data[3] << 8) | data[4]
    if rlen != len(data) - 5:
        fail("record length %d != payload %d" % (rlen, len(data) - 5))

    body = data[5:]
    if not body:
        fail("empty handshake payload")
    if body[0] != 1:
        fail("handshake type %d, expected 1 (ClientHello)" % body[0])
    hlen = (body[1] << 16) | (body[2] << 8) | body[3]
    if hlen != len(body) - 4:
        fail("handshake length %d != body %d" % (hlen, len(body) - 4))

    ch = body[4:]
    pos = 0
    if ch[pos] != 3 or ch[pos + 1] != 3:
        fail("ClientHello version %d.%d, expected 3.3" % (ch[pos], ch[pos + 1]))
    pos += 2
    pos += 32                                   # random
    sid_len = ch[pos]
    pos += 1
    if sid_len != 0:
        fail("session id length %d, expected 0" % sid_len)
    pos += sid_len
    suites_len = (ch[pos] << 8) | ch[pos + 1]
    pos += 2
    if suites_len == 0 or suites_len % 2 != 0:
        fail("cipher suites length %d" % suites_len)
    if pos + suites_len > len(ch):
        fail("cipher suites truncated")
    suites = [(ch[pos + i] << 8) | ch[pos + i + 1] for i in range(0, suites_len, 2)]
    for s in expected_suites:
        if s not in suites:
            fail("suite 0x%04X missing from %s" % (s, ["0x%04X" % x for x in suites]))
    pos += suites_len
    comp_len = ch[pos]
    pos += 1
    if comp_len != 1 or ch[pos] != 0:
        fail("compression methods %s, expected [0]" % list(ch[pos:pos + comp_len]))
    pos += comp_len

    if pos + 2 > len(ch):
        fail("extensions length missing")
    ext_total = (ch[pos] << 8) | ch[pos + 1]
    pos += 2
    if pos + ext_total != len(ch):
        fail("extensions length %d != remaining %d" % (ext_total, len(ch) - pos))

    end = pos + ext_total
    sni_ok = False
    while pos + 4 <= end:
        etype = (ch[pos] << 8) | ch[pos + 1]
        elen = (ch[pos + 2] << 8) | ch[pos + 3]
        pos += 4
        if pos + elen > end:
            fail("extension 0x%04X truncated" % etype)
        if etype == 0:
            list_len = (ch[pos] << 8) | ch[pos + 1]
            if list_len != elen - 2:
                fail("SNI list length %d != %d" % (list_len, elen - 2))
            ntype = ch[pos + 2]
            nlen = (ch[pos + 3] << 8) | ch[pos + 4]
            name = ch[pos + 5:pos + 5 + nlen].decode("ascii", "replace")
            if ntype != 0:
                fail("SNI name type %d, expected 0" % ntype)
            if name != expected_sni:
                fail("SNI name %r, expected %r" % (name, expected_sni))
            sni_ok = True
        pos += elen

    if not sni_ok:
        fail("SNI extension missing")

    print("  client_hello: record+handshake framing, suites %s, SNI %r OK"
          % (["0x%04X" % x for x in suites], expected_sni))
    return 0


if __name__ == "__main__":
    sys.exit(main())
