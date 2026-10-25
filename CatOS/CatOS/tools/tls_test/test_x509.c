/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
     tools/tls_test/test_x509.c — X.509 解析与证书链校验测试

  证书由 gen_certs.ps1 用 .NET 的 CertificateRequest 生成 (真 DER),
  C 侧用 lib/x509.c 解析并用 lib/rsa.c 验签.

  编译: gcc -I shim -I ../../include -O2 -Wall -o x509_test.exe test_x509.c
  运行: ./x509_test.exe
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include <stdio.h>

#include "type.h"
#include "const.h"
#include "crypto.h"
#include "x509.h"

#include "../../lib/crypto.c"
#include "../../lib/rsa.c"
#include "../../lib/x509.c"
#include "certs.h"

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

int main(void)
{
	static unsigned char root[2048], leaf[2048], expired[2048], tampered[2048];
	static const t_8 *chain[2];
	static int chain_len[2];
	static const t_8 *one[1];
	static int one_len[1];
	int root_len, leaf_len, exp_len;
	X509_CERT c_leaf, c_root, c_expired;

	printf("=== X.509 parse / chain test (now = %d-%02d-%02d) ===\n",
	       CERT_NOW_YEAR, CERT_NOW_MONTH, CERT_NOW_DAY);

	root_len = hex2bin(cert_root_hex, root, (int)sizeof(root));
	leaf_len = hex2bin(cert_leaf_hex, leaf, (int)sizeof(leaf));
	exp_len = hex2bin(cert_expired_hex, expired, (int)sizeof(expired));

	CHECK(root_len == CERT_ROOT_LEN, "root DER length");
	CHECK(leaf_len == CERT_LEAF_LEN, "leaf DER length");

	/* ---------- 解析叶子 ---------- */
	CHECK(x509_parse(leaf, leaf_len, &c_leaf) == X509_OK, "leaf parses");
	CHECK(c_leaf.sig_alg == 1, "leaf signed with sha256WithRSA");
	CHECK(c_leaf.tbs.len > 0 && c_leaf.tbs.len < leaf_len, "tbs size sane");
	CHECK(c_leaf.issuer.len > 0 && c_leaf.subject.len > 0, "names present");
	CHECK(c_leaf.rsa_n.len == 256, "leaf RSA modulus is 2048 bit");
	{
		t_8 n[512];
		int n_len = 0;
		t_32 e = 0;
		CHECK(x509_get_rsa(&c_leaf, n, (int)sizeof(n), &n_len, &e) == X509_OK,
		      "leaf public key extracted");
		CHECK(n_len == 256, "leaf modulus length");
		CHECK(e == 65537, "leaf exponent is 65537");
	}

	/* ---------- 有效期 ---------- */
	CHECK(x509_check_time(&c_leaf, CERT_NOW_YEAR, CERT_NOW_MONTH, CERT_NOW_DAY) == X509_OK,
	      "leaf valid now");
	CHECK(x509_check_time(&c_leaf, CERT_NOW_YEAR + 5, CERT_NOW_MONTH, CERT_NOW_DAY)
	      == X509_ERR_TIME, "leaf expired in 5 years");

	/* ---------- 解析根 + 自签 ---------- */
	CHECK(x509_parse(root, root_len, &c_root) == X509_OK, "root parses");
	CHECK(x509_verify_signed_by(&c_root, &c_root) == X509_OK, "root is self-signed");

	/* ---------- 链校验 ---------- */
	chain[0] = leaf;
	chain[1] = root;
	chain_len[0] = leaf_len;
	chain_len[1] = root_len;
	CHECK(x509_verify_chain(chain, chain_len, 2, CERT_NOW_YEAR, CERT_NOW_MONTH,
	                        CERT_NOW_DAY) == X509_OK, "leaf -> root chain verifies");

	/* 单张自签根也是有效链 */
	one[0] = root;
	one_len[0] = root_len;
	CHECK(x509_verify_chain(one, one_len, 1, CERT_NOW_YEAR, CERT_NOW_MONTH,
	                        CERT_NOW_DAY) == X509_OK, "self-signed root chain verifies");

	/* ---------- 过期证书 ---------- */
	CHECK(x509_parse(expired, exp_len, &c_expired) == X509_OK, "expired cert parses");
	CHECK(x509_check_time(&c_expired, CERT_NOW_YEAR, CERT_NOW_MONTH, CERT_NOW_DAY)
	      == X509_ERR_TIME, "expired cert fails time check");
	chain[0] = expired;
	chain_len[0] = exp_len;
	CHECK(x509_verify_chain(chain, chain_len, 2, CERT_NOW_YEAR, CERT_NOW_MONTH,
	                        CERT_NOW_DAY) == X509_ERR_TIME,
	      "expired chain rejected");

	/* ---------- 篡改签名 ---------- */
	{
		int i;
		for (i = 0; i < leaf_len; i++) tampered[i] = leaf[i];
		tampered[leaf_len - 1] ^= 0x01;          /* 最后 1 字节在签名里 */
	}
	chain[0] = tampered;
	chain_len[0] = leaf_len;
	CHECK(x509_verify_chain(chain, chain_len, 2, CERT_NOW_YEAR, CERT_NOW_MONTH,
	                        CERT_NOW_DAY) == X509_ERR_SIG,
	      "tampered signature rejected");

	/* 篡改 tbs 里的一个字节 (改主体名) 也必须失败 */
	{
		int i;
		for (i = 0; i < leaf_len; i++) tampered[i] = leaf[i];
		tampered[c_leaf.subject.p - leaf + c_leaf.subject.len - 1] ^= 0x20;
	}
	chain[0] = tampered;
	CHECK(x509_verify_chain(chain, chain_len, 2, CERT_NOW_YEAR, CERT_NOW_MONTH,
	                        CERT_NOW_DAY) != X509_OK,
	      "tampered subject rejected");

	/* ---------- 错配链 ---------- */
	chain[0] = expired;                          /* 过期证书 + 有效根: 签发者字段本身匹配 */
	chain_len[0] = exp_len;
	CHECK(x509_verify_signed_by(&c_expired, &c_root) == X509_OK,
	      "expired leaf is genuinely issued by root");

	/* 叶子当签发者: 名字不匹配 */
	CHECK(x509_verify_signed_by(&c_leaf, &c_leaf) == X509_ERR_ISSUER,
	      "leaf cannot issue itself");

	/* ---------- 畸形输入 ---------- */
	{
		X509_CERT tmp;
		CHECK(x509_parse(leaf, 0, &tmp) == X509_ERR_ARG, "empty cert rejected");
		CHECK(x509_parse(leaf, 10, &tmp) < 0, "truncated cert rejected");
		CHECK(x509_parse(0, 100, &tmp) == X509_ERR_ARG, "NULL cert rejected");
		{
			unsigned char junk[64];
			int i;
			for (i = 0; i < 64; i++) junk[i] = (unsigned char)(0xFF - i);
			CHECK(x509_parse(junk, 64, &tmp) < 0, "garbage rejected");
		}
		/* 逐字节截断都不应越界或崩溃 */
		{
			int cut;
			for (cut = 1; cut < leaf_len; cut += 37) {
				X509_CERT t2;
				(void)x509_parse(leaf, cut, &t2);
			}
		}
	}

	printf("=== %s: %d failure(s) ===\n", g_err ? "FAILED" : "ALL PASSED", g_err);
	return g_err ? 1 : 0;
}
