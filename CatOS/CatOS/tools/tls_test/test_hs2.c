/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
     tools/tls_test/test_hs2.c — TLS 1.2 完整握手驱动测试 (C 侧客户端)

  流程:
    1. 用固定 client_random / pre-master 初始化驱动 (RNG 也固定, 便于复现)
    2. 生成 ClientHello 记录, 写到 client_hello.bin (hex), 供 Python 侧使用
    3. 逐条喂入 Python 生成的服务端首飞行 (ServerHello / 分片 Certificate /
       ServerHelloDone), 驱动应产出 ClientKeyExchange + CCS + Finished 三条记录
    4. 把客户端记录写到 client_flight.txt, 交给 gen_hs2.py verify 做独立校验
    5. 负向: 用错误信任锚时必须拒绝

  编译: gcc -I shim -I ../../include -O2 -Wall -o hs2_test.exe test_hs2.c
  运行: ./hs2_test.exe            (需要先跑 python gen_hs2.py flight1)
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include <stdio.h>

#include "type.h"
#include "const.h"
#include "crypto.h"
#include "tls.h"
#include "x509.h"

#include "../../lib/crypto.c"
#include "../../lib/rsa.c"
#include "../../lib/x509.c"
#include "../../lib/tls.c"
#include "certs.h"
#include "hs2_flight1.h"
#include "hs2_flight1_gcm.h"

static int g_err;
static TLS_CLIENT g_client;                 /* 4KB+ 的缓冲, 放静态区 */

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

static int write_hex_file(const char *path, const unsigned char *b, int n)
{
	FILE *f = fopen(path, "w");
	int i;
	if (!f) return -1;
	for (i = 0; i < n; i++) fprintf(f, "%02x", b[i]);
	fprintf(f, "\n");
	fclose(f);
	return 0;
}

int main(void)
{
	static unsigned char cr[32], pm[48];
	static unsigned char flight1[4096];
	static unsigned char root[2048];
	static unsigned char out[4096], accumulated[8192];
	static unsigned char hello[512], rec[2048];
	int flight1_len, root_len, hello_len;
	int acc_len = 0;
	int i;

	printf("=== TLS handshake driver (C client) ===\n");

	hex2bin(HS2_CLIENT_RANDOM_HEX, cr, 32);
	hex2bin(HS2_PREMASTER_HEX, pm, 48);
	root_len = hex2bin(cert_root_hex, root, (int)sizeof(root));
	CHECK(root_len == CERT_ROOT_LEN, "trust anchor decoded");

	/* 固定随机源: RSA 填充与记录 IV 都可复现 */
	rsa_random_seed(0x12345678u);

	CHECK(tls_client_init(&g_client, "handshake.test", cr, pm, root, root_len,
	                      CERT_NOW_YEAR, CERT_NOW_MONTH, CERT_NOW_DAY) == TLS_OK,
	      "client init");

	/* ---------- ClientHello ---------- */
	hello_len = tls_client_hello(&g_client, hello, (int)sizeof(hello));
	CHECK(hello_len > 5, "ClientHello record built");
	CHECK(write_hex_file("client_hello.bin", hello, hello_len) == 0,
	      "client_hello.bin written");

	/* ---------- 服务端首飞行 ---------- */
	flight1_len = hex2bin(hs2_flight_002f_hex, flight1, (int)sizeof(flight1));
	CHECK(flight1_len > 0, "flight1 decoded");

	{
		int pos = 0;
		int records = 0;
		while (pos < flight1_len) {
			TLS_RECORD r;
			int used = tls_parse_record(flight1 + pos, flight1_len - pos, &r);
			int out_len = 0;
			int rc;

			CHECK(used > 0, "flight1 record parsed");
			if (used <= 0) break;
			pos += used;
			records++;
			rc = tls_client_feed(&g_client, flight1 + pos - used, used,
			                     out, (int)sizeof(out), &out_len);
			CHECK(rc == TLS_OK, "feed accepted record");
			if (rc != TLS_OK) {
				printf("    (error %d)\n", rc);
				break;
			}
			if (out_len > 0) {
				CHECK(acc_len + out_len <= (int)sizeof(accumulated),
				      "client output buffer");
				for (i = 0; i < out_len; i++) accumulated[acc_len + i] = out[i];
				acc_len += out_len;
			}
		}
		CHECK(records == HS2_RECORD_COUNT, "flight1 record count");
	}

	/* ---------- 驱动状态 ---------- */
	CHECK(g_client.got_hello, "ServerHello processed");
	CHECK(g_client.got_cert, "Certificate accepted (chain verified)");
	CHECK(g_client.got_done, "ServerHelloDone processed");
	CHECK(g_client.err == TLS_OK, "no driver error");
	CHECK(g_client.leaf_n_len == 256, "leaf RSA modulus captured");
	CHECK(g_client.leaf_e == 65537, "leaf RSA exponent captured");
	CHECK(!tls_client_established(&g_client), "not established before server Finished");

	/* ---------- 客户端首飞行结构 ---------- */
	{
		int pos = 0;
		int types[4];
		int lens[4];
		int nrec = 0;
		while (pos < acc_len && nrec < 4) {
			TLS_RECORD r;
			int used = tls_parse_record(accumulated + pos, acc_len - pos, &r);
			if (used <= 0) break;
			types[nrec] = r.type;
			lens[nrec] = r.length;
			nrec++;
			pos += used;
		}
		CHECK(nrec == 3, "client emitted 3 records");
		if (nrec == 3) {
			CHECK(types[0] == TLS_CT_HANDSHAKE, "client record 1 = handshake (CKE)");
			CHECK(types[1] == TLS_CT_CCS, "client record 2 = CCS");
			CHECK(types[2] == TLS_CT_HANDSHAKE, "client record 3 = handshake (Finished)");
			CHECK(lens[0] == 4 + 2 + 256, "CKE record length (4+2+256)");
			CHECK(lens[1] == 1, "CCS payload is one byte");
			CHECK(lens[2] > 16, "Finished record is encrypted (IV + ciphertext)");
		}
	}
	CHECK(write_hex_file("client_flight.txt", accumulated, acc_len) == 0,
	      "client_flight.txt written");

	/* ---------- 场景 2: 服务端选择 AES-128-GCM (AEAD) ---------- */
	{
		TLS_CLIENT g2;
		static unsigned char f1g[4096], o2[4096], a2[8192];
		int f1g_len = hex2bin(hs2_flight_009c_hex, f1g, (int)sizeof(f1g));
		int acclen = 0, p2 = 0, rc = TLS_OK;

		CHECK(tls_client_init(&g2, "handshake.test", cr, pm, root, root_len,
		                      CERT_NOW_YEAR, CERT_NOW_MONTH, CERT_NOW_DAY) == TLS_OK,
		      "gcm client init");
		CHECK(f1g_len > 0, "gcm flight decoded");
		(void)tls_client_hello(&g2, rec, (int)sizeof(rec));
		while (p2 < f1g_len) {
			TLS_RECORD r;
			int used = tls_parse_record(f1g + p2, f1g_len - p2, &r);
			int out_len = 0;
			int k;
			if (used <= 0) { rc = used; break; }
			p2 += used;
			rc = tls_client_feed(&g2, f1g + p2 - used, used, o2,
			                     (int)sizeof(o2), &out_len);
			if (rc != TLS_OK) { printf("    (gcm record %d rc=%d)\n", p2, rc); break; }
			for (k = 0; k < out_len; k++) a2[acclen + k] = o2[k];
			acclen += out_len;
		}
		if (rc != TLS_OK) printf("    (gcm feed rc=%d)\n", rc);
		CHECK(rc == TLS_OK, "gcm handshake accepted");
		CHECK(g2.sess.suite == TLS_SUITE_RSA_AES128_GCM_SHA256, "GCM suite negotiated");
		CHECK(g2.sess.mac_len == 0 && g2.sess.iv_len == 4, "GCM key layout (no MAC, 4-byte salt)");
		CHECK(g2.got_done, "GCM ServerHelloDone processed");
		{
			int pos2 = 0, nrec = 0, last_len = 0, last_type = 0;
			while (pos2 < acclen) {
				TLS_RECORD r;
				int used = tls_parse_record(a2 + pos2, acclen - pos2, &r);
				if (used <= 0) break;
				last_type = r.type;
				last_len = r.length;
				nrec++;
				pos2 += used;
			}
			CHECK(nrec == 3, "gcm client emitted 3 records");
			CHECK(last_type == TLS_CT_HANDSHAKE, "gcm finished record type");
			CHECK(last_len == 8 + 16 + 16, "gcm payload = explicit nonce + ct + tag");
		}
		CHECK(write_hex_file("client_flight_gcm.txt", a2, acclen) == 0,
		      "client_flight_gcm.txt written");
	}
	/* ---------- 负向: 错误信任锚 ---------- */
	{
		TLS_CLIENT bad;
		unsigned char expired[2048];
		int explen = hex2bin(cert_expired_hex, expired, (int)sizeof(expired));
		int pos = 0;
		int rc = TLS_OK;

		CHECK(tls_client_init(&bad, "handshake.test", cr, pm, expired, explen,
		                      CERT_NOW_YEAR, CERT_NOW_MONTH, CERT_NOW_DAY) == TLS_OK,
		      "bad-anchor client init");
		(void)tls_client_hello(&bad, rec, (int)sizeof(rec));
		while (pos < flight1_len) {
			TLS_RECORD r;
			int used = tls_parse_record(flight1 + pos, flight1_len - pos, &r);
			int out_len = 0;
			if (used <= 0) break;
			pos += used;
			rc = tls_client_feed(&bad, flight1 + pos - used, used, out,
			                     (int)sizeof(out), &out_len);
			if (rc != TLS_OK) break;
		}
		CHECK(rc != TLS_OK, "wrong trust anchor rejected");
		CHECK(!bad.got_done, "handshake aborted before ServerHelloDone");
	}

	/* ---------- 负向: 篡改服务端记录 ---------- */
	{
		TLS_CLIENT t;
		int pos = 0;
		int rc = TLS_OK;
		CHECK(tls_client_init(&t, "handshake.test", cr, pm, root, root_len,
		                      CERT_NOW_YEAR, CERT_NOW_MONTH, CERT_NOW_DAY) == TLS_OK,
		      "tamper client init");
		(void)tls_client_hello(&t, rec, (int)sizeof(rec));
		/* 只喂第一条记录, 但把长度字段改大 */
		{
			unsigned char bad_rec[4096];
			for (i = 0; i < flight1_len; i++) bad_rec[i] = flight1[i];
			bad_rec[3] = 0xFF;
			bad_rec[4] = 0xFF;
			{
				int out_len = 0;
				rc = tls_client_feed(&t, bad_rec, 40, out, (int)sizeof(out), &out_len);
			}
		}
		CHECK(rc != TLS_OK, "corrupt record rejected");
		(void)pos;
	}

	printf("=== %s: %d failure(s) ===\n", g_err ? "FAILED" : "ALL PASSED", g_err);
	return g_err ? 1 : 0;
}
