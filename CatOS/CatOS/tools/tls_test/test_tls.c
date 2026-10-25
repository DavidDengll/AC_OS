/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
        tools/tls_test/test_tls.c — TLS 记录层/握手编解码的宿主侧测试

  编译 (在 tools/tls_test 目录):
    python gen_fixtures.py fixtures.h
    gcc -I shim -I ../../include -O2 -Wall -o tls_test.exe test_tls.c
  运行:
    ./tls_test.exe client_hello.txt
  然后:
    python verify_hello.py client_hello.txt

  说明:
    - 直接 #include ../../lib/tls.c, 测的就是内核里那份代码
    - 服务端夹具由 gen_fixtures.py 用独立实现封装, 避免"自己验自己"
    - 生成的 ClientHello 会写进 client_hello.txt, 交给 Python 反向解析
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include <stdio.h>

#include "type.h"
#include "const.h"
#include "tls.h"

#include "../../lib/tls.c"
#include "fixtures.h"

static int g_err;

#define CHECK(cond, msg)                                              \
	do {                                                              \
		if (!(cond)) {                                                \
			printf("  [FAIL] %s (line %d)\n", msg, __LINE__);         \
			g_err++;                                                  \
		}                                                             \
	} while (0)

static int hexval(char c)
{
	if (c >= '0' && c <= '9') return c - '0';
	if (c >= 'a' && c <= 'f') return c - 'a' + 10;
	if (c >= 'A' && c <= 'F') return c - 'A' + 10;
	return -1;
}

static int hex2bin(const char *hex, unsigned char *out, int out_max)
{
	int n = 0;
	while (hex[0] && hex[1] && n < out_max) {
		int hi = hexval(hex[0]);
		int lo = hexval(hex[1]);
		if (hi < 0 || lo < 0) break;
		out[n++] = (unsigned char)((hi << 4) | lo);
		hex += 2;
	}
	return n;
}

static int memcmp_local(const unsigned char *a, const unsigned char *b, int n)
{
	int i;
	for (i = 0; i < n; i++) {
		if (a[i] != b[i]) return 1;
	}
	return 0;
}

static int bin2hex_file(const char *path, const unsigned char *b, int n)
{
	FILE *f = fopen(path, "w");
	int i;
	if (!f) return -1;
	for (i = 0; i < n; i++) fprintf(f, "%02x", b[i]);
	fprintf(f, "\n");
	fclose(f);
	return 0;
}

int main(int argc, char **argv)
{
	static unsigned char stream[8192];
	static unsigned char hello[512];
	static unsigned char cert[600], cert_want[600];
	static unsigned char want_random[32];
	int stream_len;
	int pos;
	int rec_count = 0;
	int hs_count = 0;
	int saw_sh = 0, saw_cert = 0, saw_done = 0;
	const char *hello_out = (argc > 1) ? argv[1] : "client_hello.txt";

	printf("=== TLS record/handshake codec test ===\n");

	/* ---------- 1. 生成 ClientHello ---------- */
	{
		TLS_CLIENT_HELLO ch;
		int n;
		int i;

		for (i = 0; i < 32; i++) ch.random[i] = (t_8)((i * 5 + 1) & 0xFF);
		ch.version_major = 3;
		ch.version_minor = 3;
		ch.suites[0] = TLS_SUITE_RSA_AES128_CBC_SHA;
		ch.suites[1] = TLS_SUITE_RSA_AES128_GCM_SHA256;
		ch.suite_count = 2;
		ch.server_name[0] = 0;
		{
			const char *sni = "example.com";
			for (i = 0; sni[i] && i < (int)sizeof(ch.server_name) - 1; i++) {
				ch.server_name[i] = sni[i];
			}
			ch.server_name[i] = 0;
		}

		n = tls_build_client_hello(&ch, hello, (int)sizeof(hello));
		CHECK(n > 0, "client hello built");
		if (n > 0) {
			/* 记录层封装后写出, 交给 Python 反向解析 */
			unsigned char rec[600];
			int rn = tls_build_record(TLS_CT_HANDSHAKE, hello, n, rec, (int)sizeof(rec));
			CHECK(rn == n + 5, "record wrapping length");
			if (bin2hex_file(hello_out, rec, rn) == 0) {
				printf("  client_hello written: %s (%d bytes)\n", hello_out, rn);
			} else {
				printf("  [FAIL] cannot write %s\n", hello_out);
				g_err++;
			}
		}
		CHECK(tls_build_client_hello(0, hello, (int)sizeof(hello)) == TLS_ERR_ARG,
		      "NULL hello rejected");
		ch.suite_count = 0;
		CHECK(tls_build_client_hello(&ch, hello, (int)sizeof(hello)) == TLS_ERR_ARG,
		      "empty suite list rejected");
	}

	/* ---------- 2. 解析服务端夹具 ---------- */
	stream_len = hex2bin(fixture_records_hex, stream, (int)sizeof(stream));
	CHECK(stream_len > 0, "fixture decoded");

	pos = 0;
	while (pos < stream_len) {
		TLS_RECORD rec;
		int used = tls_parse_record(stream + pos, stream_len - pos, &rec);

		CHECK(used > 0, "record parsed");
		if (used <= 0) break;
		CHECK(rec.type == TLS_CT_HANDSHAKE, "record is handshake");
		CHECK(rec.major == 3 && rec.minor == 3, "record version 3.3");
		rec_count++;
		pos += used;

		{
			int hp = 0;
			while (hp < (int)rec.length) {
				t_8 type = 0;
				const t_8 *body = 0;
				int blen = 0;
				int hused = tls_hs_header(rec.payload + hp, (int)rec.length - hp,
				                          &type, &body, &blen);
				CHECK(hused > 0, "handshake message parsed");
				if (hused <= 0) break;
				hs_count++;

				if (type == TLS_HS_SERVER_HELLO) {
					TLS_SERVER_HELLO sh;
					int i;
					CHECK(tls_parse_server_hello(body, blen, &sh) == TLS_OK,
					      "ServerHello parsed");
					CHECK(sh.version_major == FIX_VERSION_MAJOR &&
					      sh.version_minor == FIX_VERSION_MINOR,
					      "ServerHello version");
					CHECK(sh.suite == FIX_SUITE, "ServerHello cipher suite");
					CHECK(sh.compression == 0, "ServerHello compression null");
					CHECK(sh.session_id_len == 0, "ServerHello empty session id");
					hex2bin(FIX_SERVER_RANDOM_HEX, want_random, 32);
					for (i = 0; i < 32; i++) {
						if (sh.random[i] != want_random[i]) break;
					}
					CHECK(i == 32, "ServerHello random bytes");
					saw_sh = 1;
				} else if (type == TLS_HS_CERTIFICATE) {
					TLS_CERT_LIST list;
					list.data = 0;
					list.length = 0;
					const t_8 *c = 0;
					int clen = 0;
					CHECK(tls_parse_certificate(body, blen, &list) == TLS_OK,
					      "Certificate parsed");
					CHECK(tls_cert_at(&list, 0, &c, &clen) == TLS_OK,
					      "first certificate present");
					CHECK(clen == FIX_CERT_LEN, "certificate length");
					if (clen == FIX_CERT_LEN) {
						hex2bin(FIX_CERT_HEX, cert_want, (int)sizeof(cert_want));
						if (clen < (int)sizeof(cert)) {
							int k;
							for (k = 0; k < clen; k++) cert[k] = c[k];
						}
						CHECK(memcmp_local(cert, cert_want, clen) == 0,
						      "certificate bytes");
					}
					CHECK(tls_cert_at(&list, 1, &c, &clen) == TLS_ERR_SHORT,
					      "certificate index 1 out of range");
					saw_cert = 1;
				} else if (type == TLS_HS_SERVER_HELLO_DONE) {
					CHECK(tls_parse_server_hello_done(body, blen) == TLS_OK,
					      "ServerHelloDone parsed");
					saw_done = 1;
				}
				hp += hused;
			}
		}
	}

	CHECK(rec_count == FIX_RECORD_COUNT, "record count");
	CHECK(hs_count == FIX_HANDSHAKE_COUNT, "handshake message count");
	CHECK(saw_sh && saw_cert && saw_done, "saw ServerHello + Certificate + Done");

	/* ---------- 3. 截断/畸形输入必须被拒 ---------- */
	{
		TLS_RECORD rec;
		CHECK(tls_parse_record(stream, 4, &rec) == TLS_ERR_SHORT, "short record header");
		{
			/* 只截断第一条记录的最后一个字节 */
			int first = tls_parse_record(stream, stream_len, &rec);
			CHECK(first > 0, "first record measured");
			if (first > 0) {
				CHECK(tls_parse_record(stream, first - 1, &rec) == TLS_ERR_SHORT,
				      "truncated record payload");
			}
		}
		{
			unsigned char bad[16];
			int i;
			for (i = 0; i < 16; i++) bad[i] = stream[i];
			bad[3] = 0xFF;                     /* 长度超协议上限 */
			bad[4] = 0xFF;
			CHECK(tls_parse_record(bad, 16, &rec) == TLS_ERR_TOO_BIG,
			      "oversized record length rejected");
		}
		{
			unsigned char hs[8];
			t_8 type;
			const t_8 *body;
			int blen;
			hs[0] = TLS_HS_SERVER_HELLO;
			hs[1] = 0x00; hs[2] = 0x10; hs[3] = 0x00;   /* 声明 4096 字节 */
			CHECK(tls_hs_header(hs, 8, &type, &body, &blen) == TLS_ERR_SHORT,
			      "truncated handshake body rejected");
			hs[1] = 0xFF; hs[2] = 0xFF; hs[3] = 0xFF;
			CHECK(tls_hs_header(hs, 8, &type, &body, &blen) == TLS_ERR_TOO_BIG,
			      "oversized handshake length rejected");
		}
		{
			TLS_SERVER_HELLO sh;
			CHECK(tls_parse_server_hello(stream, 3, &sh) == TLS_ERR_SHORT,
			      "short ServerHello rejected");
		}
	}

	printf("=== %s: %d failure(s) ===\n", g_err ? "FAILED" : "ALL PASSED", g_err);
	return g_err ? 1 : 0;
}
