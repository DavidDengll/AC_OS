/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
        tools/crypto_test/test.c — 内核密码学原语的宿主侧向量测试

  编译 (在 tools/crypto_test 目录):
    python gen_vectors.py > expected.h
    gcc -I shim -I ../../include -O2 -Wall -o crypto_test.exe test.c

  说明:
    直接 #include ../../lib/crypto.c, 所以测的就是内核里跑的那份代码.
    期望值由 gen_vectors.py 用 Python hashlib/hmac 生成 (独立实现交叉验证).
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include <stdio.h>

#include "type.h"
#include "const.h"
#include "crypto.h"

#include "../../lib/crypto.c"

/* 向量结构体 (供 expected*.h 使用) */
typedef struct { const char *name; const char *in_hex;  const char *out_hex; } SHA1_VEC;
typedef struct { const char *name; const char *key_hex; const char *in_hex;  const char *out_hex; } AES_VEC;
typedef struct { const char *name; const char *key_hex; const char *iv_hex;   const char *in_hex; const char *out_hex; } AES_CBC_VEC;
typedef struct { const char *name; const char *key_hex; const char *nonce_hex; const char *aad_hex;
                 const char *pt_hex; const char *ct_hex; const char *tag_hex; } GCM_VEC;
typedef struct { const char *name; const char *base_hex; const char *want_hex; } RSA_MODPOW_VEC;
typedef struct { const char *name; const char *digest_hex; const char *sig_hex; } RSA_SIG_VEC;
typedef struct { const char *name; const char *msg_hex; const char *ps_hex;
                 const char *em_hex; const char *ct_hex; } RSA_ENC_VEC;

#include "expected.h"        /* SHA-256 / HMAC-SHA256 / PRF  (Python hashlib) */
#include "expected_net.h"    /* SHA-1 / HMAC-SHA1 / AES-ECB/CBC/CTR  (.NET) */
#include "expected_gcm.h"    /* AES-128-GCM  (独立 Python 实现 + NIST 自检) */
#include "../../lib/rsa.c"     /* RSA / PKCS#1 v1.5 (被下面测试直接调用) */
#include "expected_rsa.h"     /* RSA 向量 (.NET BigInteger / RSA) */

static int g_err;
typedef unsigned int u32;

#define CHECK(cond, msg)                                              \
	do {                                                              \
		if (!(cond)) {                                                \
			printf("  [FAIL] %s (line %d)\n", msg, __LINE__);         \
			g_err++;                                                  \
		}                                                             \
	} while (0)

static int strcmp_local(const char *a, const char *b);

static int hexval(char c)
{
	if (c >= '0' && c <= '9') return c - '0';
	if (c >= 'a' && c <= 'f') return c - 'a' + 10;
	if (c >= 'A' && c <= 'F') return c - 'A' + 10;
	return -1;
}

/* 十六进制字符串 -> 字节数组, 返回字节数 */
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

static void to_hex(const unsigned char *b, int n, char *out)
{
	static const char *d = "0123456789abcdef";
	int i;
	for (i = 0; i < n; i++) {
		out[i * 2] = d[b[i] >> 4];
		out[i * 2 + 1] = d[b[i] & 15];
	}
	out[n * 2] = 0;
}

static void check_hex(const char *what, const char *name,
                      const unsigned char *got, int got_len,
                      const char *want_hex)
{
	char got_hex[600];

	to_hex(got, got_len, got_hex);
	if (strcmp_local(got_hex, want_hex) != 0) {
		printf("  [FAIL] %-22s %s\n         got  %s\n         want %s\n",
		       what, name, got_hex, want_hex);
		g_err++;
	}
}

static int strcmp_local(const char *a, const char *b)
{
	while (*a && *b) {
		if (*a != *b) return 1;
		a++;
		b++;
	}
	return (*a == *b) ? 0 : 1;
}

int main(void)
{
	int i, j;
	unsigned char buf[1024];
	unsigned char out[64];
	unsigned char key[128];
	unsigned char secret[128];
	unsigned char seed[128];
	char hex[700];

	printf("=== crypto self test (vectors from Python hashlib) ===\n");

	/* ---------- SHA-256 ---------- */
	for (i = 0; i < (int)(sizeof(sha_vecs) / sizeof(sha_vecs[0])); i++) {
		int len = hex2bin(sha_vecs[i].in_hex, buf, (int)sizeof(buf));
		sha256(buf, len, out);
		check_hex("sha256", sha_vecs[i].name, out, 32, sha_vecs[i].out_hex);
	}
	printf("  sha256: %d vectors\n", (int)(sizeof(sha_vecs) / sizeof(sha_vecs[0])));

	/* 分段 update 必须与一次性 update 结果相同 */
	{
		int len = hex2bin(sha_vecs[2].in_hex, buf, (int)sizeof(buf));
		SHA256_CTX ctx;
		t_8 d1[32], d2[32];

		sha256_init(&ctx);
		sha256_update(&ctx, buf, 1);
		sha256_update(&ctx, buf + 1, 7);
		sha256_update(&ctx, buf + 8, len - 8);
		sha256_final(&ctx, d1);
		sha256(buf, len, d2);
		check_hex("sha256(chunked)", sha_vecs[2].name, d1, 32, sha_vecs[2].out_hex);
		if (crypto_memcmp_ct(d1, d2, 32) != 0) {
			printf("  [FAIL] chunked update differs from one-shot\n");
			g_err++;
		}
	}

	/* ---------- HMAC-SHA256 ---------- */
	for (i = 0; i < (int)(sizeof(hmac_vecs) / sizeof(hmac_vecs[0])); i++) {
		int klen = hex2bin(hmac_vecs[i].key_hex, key, (int)sizeof(key));
		int dlen = hex2bin(hmac_vecs[i].in_hex, buf, (int)sizeof(buf));
		hmac_sha256(key, klen, buf, dlen, out);
		check_hex("hmac_sha256", hmac_vecs[i].name, out, 32, hmac_vecs[i].out_hex);
	}
	printf("  hmac_sha256: %d vectors\n",
	       (int)(sizeof(hmac_vecs) / sizeof(hmac_vecs[0])));

	/* ---------- TLS PRF ---------- */
	for (i = 0; i < (int)(sizeof(prf_vecs) / sizeof(prf_vecs[0])); i++) {
		int slen = hex2bin(prf_vecs[i].secret_hex, secret, (int)sizeof(secret));
		int seedlen = hex2bin(prf_vecs[i].seed_hex, seed, (int)sizeof(seed));
		unsigned char prf_out[256];
		int rc = tls_prf_sha256(secret, slen, prf_vecs[i].label,
		                        seed, seedlen, prf_out, prf_vecs[i].out_len);
		if (rc != 0) {
			printf("  [FAIL] tls_prf returned %d for %s\n", rc, prf_vecs[i].name);
			g_err++;
			continue;
		}
		check_hex("tls_prf_sha256", prf_vecs[i].name, prf_out,
		          prf_vecs[i].out_len, prf_vecs[i].out_hex);
	}
	printf("  tls_prf_sha256: %d vectors\n",
	       (int)(sizeof(prf_vecs) / sizeof(prf_vecs[0])));

	/* ---------- 边界与拒绝路径 ---------- */
	{
		int rc;
		/* 超长 seed 必须被拒绝, 而不是越界 */
		rc = tls_prf_sha256(secret, 48, "x", seed, 97, out, 32);
		if (rc == 0) {
			printf("  [FAIL] prf accepted oversized seed\n");
			g_err++;
		}
		/* out_len 上限 */
		rc = tls_prf_sha256(secret, 48, "x", seed, 32, out, 257);
		if (rc == 0) {
			printf("  [FAIL] prf accepted oversized output\n");
			g_err++;
		}
		/* 空输入摘要 */
		sha256(0, 0, out);
		to_hex(out, 32, hex);
		if (strcmp_local(hex, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855") != 0) {
			printf("  [FAIL] sha256(NULL,0) wrong: %s\n", hex);
			g_err++;
		}
	}

	/* ---------- SHA-1 ---------- */
	for (i = 0; i < (int)(sizeof(sha1_vecs) / sizeof(sha1_vecs[0])); i++) {
		int len = hex2bin(sha1_vecs[i].in_hex, buf, (int)sizeof(buf));
		sha1(buf, len, out);
		check_hex("sha1", sha1_vecs[i].name, out, 20, sha1_vecs[i].out_hex);
	}
	printf("  sha1: %d vectors\n", (int)(sizeof(sha1_vecs) / sizeof(sha1_vecs[0])));

	/* ---------- HMAC-SHA1 ---------- */
	for (i = 0; i < (int)(sizeof(hmac1_vecs) / sizeof(hmac1_vecs[0])); i++) {
		int klen = hex2bin(hmac1_vecs[i].key_hex, key, (int)sizeof(key));
		int dlen = hex2bin(hmac1_vecs[i].in_hex, buf, (int)sizeof(buf));
		hmac_sha1(key, klen, buf, dlen, out);
		check_hex("hmac_sha1", hmac1_vecs[i].name, out, 20, hmac1_vecs[i].out_hex);
	}
	printf("  hmac_sha1: %d vectors\n",
	       (int)(sizeof(hmac1_vecs) / sizeof(hmac1_vecs[0])));

	/* ---------- AES-128 单分组 (FIPS-197) ---------- */
	for (i = 0; i < (int)(sizeof(aes_ecb_vecs) / sizeof(aes_ecb_vecs[0])); i++) {
		int klen = hex2bin(aes_ecb_vecs[i].key_hex, key, (int)sizeof(key));
		int dlen = hex2bin(aes_ecb_vecs[i].in_hex, buf, (int)sizeof(buf));
		unsigned char dec[16];
		AES128_KEY ks;
		if (klen != 16 || dlen != 16) {
			printf("  [FAIL] bad ecb vector sizes\n");
			g_err++;
			continue;
		}
		aes128_setkey(&ks, key);
		aes128_encrypt_block(&ks, buf, out);
		check_hex("aes128_ecb_enc", aes_ecb_vecs[i].name, out, 16, aes_ecb_vecs[i].out_hex);
		aes128_decrypt_block(&ks, out, dec);
		check_hex("aes128_ecb_dec", aes_ecb_vecs[i].name, dec, 16, aes_ecb_vecs[i].in_hex);
	}
	printf("  aes128_ecb: %d vectors\n",
	       (int)(sizeof(aes_ecb_vecs) / sizeof(aes_ecb_vecs[0])));

	/* ---------- AES-128-CBC ---------- */
	for (i = 0; i < (int)(sizeof(aes_cbc_vecs) / sizeof(aes_cbc_vecs[0])); i++) {
		unsigned char pt[300], iv[16], got[300], back[300];
		int klen = hex2bin(aes_cbc_vecs[i].key_hex, key, (int)sizeof(key));
		int ivlen = hex2bin(aes_cbc_vecs[i].iv_hex, iv, 16);
		int dlen = hex2bin(aes_cbc_vecs[i].in_hex, pt, (int)sizeof(pt));
		int j;
		AES128_KEY ks;
		if (klen != 16 || ivlen != 16 || dlen <= 0 || dlen > (int)sizeof(got)) {
			printf("  [FAIL] bad cbc vector sizes\n");
			g_err++;
			continue;
		}
		aes128_setkey(&ks, key);
		aes128_cbc_encrypt(&ks, iv, pt, got, dlen);
		check_hex("aes128_cbc_enc", aes_cbc_vecs[i].name, got, dlen, aes_cbc_vecs[i].out_hex);
		/* 用原始 IV 解回来 */
		hex2bin(aes_cbc_vecs[i].iv_hex, iv, 16);
		aes128_cbc_decrypt(&ks, iv, got, back, dlen);
		for (j = 0; j < dlen; j++) {
			if (back[j] != pt[j]) break;
		}
		if (j != dlen) {
			printf("  [FAIL] aes128_cbc dec round-trip (%s)\n", aes_cbc_vecs[i].name);
			g_err++;
		}
	}
	printf("  aes128_cbc: %d vectors\n",
	       (int)(sizeof(aes_cbc_vecs) / sizeof(aes_cbc_vecs[0])));

	/* ---------- AES-128-CTR ---------- */
	for (i = 0; i < (int)(sizeof(aes_ctr_vecs) / sizeof(aes_ctr_vecs[0])); i++) {
		unsigned char pt[300], nonce[16], got[300], back[300];
		int klen = hex2bin(aes_ctr_vecs[i].key_hex, key, (int)sizeof(key));
		int nlen = hex2bin(aes_ctr_vecs[i].iv_hex, nonce, 16);
		int dlen = hex2bin(aes_ctr_vecs[i].in_hex, pt, (int)sizeof(pt));
		int j;
		AES128_KEY ks;
		if (klen != 16 || nlen != 16 || dlen <= 0 || dlen > (int)sizeof(got)) {
			printf("  [FAIL] bad ctr vector sizes\n");
			g_err++;
			continue;
		}
		aes128_setkey(&ks, key);
		aes128_ctr_xcrypt(&ks, nonce, pt, got, dlen);
		check_hex("aes128_ctr", aes_ctr_vecs[i].name, got, dlen, aes_ctr_vecs[i].out_hex);
		aes128_ctr_xcrypt(&ks, nonce, got, back, dlen);
		for (j = 0; j < dlen; j++) {
			if (back[j] != pt[j]) break;
		}
		if (j != dlen) {
			printf("  [FAIL] aes128_ctr round-trip (%s)\n", aes_ctr_vecs[i].name);
			g_err++;
		}
	}
	printf("  aes128_ctr: %d vectors\n",
	       (int)(sizeof(aes_ctr_vecs) / sizeof(aes_ctr_vecs[0])));

	/* ---------- AES-128-GCM ---------- */
	for (i = 0; i < (int)(sizeof(gcm_vecs) / sizeof(gcm_vecs[0])); i++) {
		unsigned char k2[16], nonce[12], aad[64], pt[320], ct[320], got[320], back[320], got_tag[16];
		int klen = hex2bin(gcm_vecs[i].key_hex, k2, (int)sizeof(k2));
		int nlen = hex2bin(gcm_vecs[i].nonce_hex, nonce, (int)sizeof(nonce));
		int alen = hex2bin(gcm_vecs[i].aad_hex, aad, (int)sizeof(aad));
		int plen = hex2bin(gcm_vecs[i].pt_hex, pt, (int)sizeof(pt));
		int clen = hex2bin(gcm_vecs[i].ct_hex, ct, (int)sizeof(ct));
		int j;
		AES128_KEY ks;

		if (klen != 16 || nlen != 12 || plen != clen) {
			printf("  [FAIL] bad gcm vector sizes (%s)\n", gcm_vecs[i].name);
			g_err++;
			continue;
		}
		aes128_setkey(&ks, k2);

		if (aes128_gcm_encrypt(&ks, nonce, alen ? aad : 0, alen, plen ? pt : 0,
		                       got, plen, got_tag) != 0) {
			printf("  [FAIL] gcm_encrypt returned error (%s)\n", gcm_vecs[i].name);
			g_err++;
			continue;
		}
		check_hex("gcm_ct", gcm_vecs[i].name, got, plen, gcm_vecs[i].ct_hex);
		check_hex("gcm_tag", gcm_vecs[i].name, got_tag, 16, gcm_vecs[i].tag_hex);

		/* 解密 (就地) 应还原明文 */
		for (j = 0; j < plen; j++) back[j] = ct[j];
		if (aes128_gcm_decrypt(&ks, nonce, alen ? aad : 0, alen,
		                       back, back, plen, got_tag) != 0) {
			printf("  [FAIL] gcm_decrypt rejected valid tag (%s)\n", gcm_vecs[i].name);
			g_err++;
		} else {
			for (j = 0; j < plen; j++) {
				if (back[j] != pt[j]) break;
			}
			if (j != plen) {
				printf("  [FAIL] gcm_decrypt plaintext mismatch (%s)\n", gcm_vecs[i].name);
				g_err++;
			}
		}

		/* 篡改 tag 必须被拒绝 */
		got_tag[0] ^= 0x01;
		for (j = 0; j < plen; j++) back[j] = ct[j];
		if (aes128_gcm_decrypt(&ks, nonce, alen ? aad : 0, alen,
		                       back, back, plen, got_tag) == 0) {
			printf("  [FAIL] gcm_decrypt accepted tampered tag (%s)\n", gcm_vecs[i].name);
			g_err++;
		}
	}
	printf("  aes128_gcm: %d vectors\n",
	       (int)(sizeof(gcm_vecs) / sizeof(gcm_vecs[0])));
	/* ---------- RSA: modpow / 签名校验 / v1.5 加密 ---------- */
	{
		t_8 n_be[256], out_be[256];
		int n_len = hex2bin(rsa_n_hex, n_be, (int)sizeof(n_be));
		u32 e = 65537;

		CHECK(n_len == rsa_n_len, "n length");
		CHECK(rsa_e_hex[0] == '0' && rsa_e_hex[1] == '1', "exponent is 65537");

		for (i = 0; i < (int)(sizeof(rsa_modpow_vecs) / sizeof(rsa_modpow_vecs[0])); i++) {
			unsigned char base[256];
			int blen = hex2bin(rsa_modpow_vecs[i].base_hex, base, (int)sizeof(base));
			if (rsa_modexp(n_be, n_len, e, base, blen, out_be) != 0) {
				printf("  [FAIL] rsa_modexp error (%s)\n", rsa_modpow_vecs[i].name);
				g_err++;
				continue;
			}
			check_hex("rsa_modexp", rsa_modpow_vecs[i].name, out_be, n_len,
			          rsa_modpow_vecs[i].want_hex);
		}
		printf("  rsa_modexp: %d vectors\n",
		       (int)(sizeof(rsa_modpow_vecs) / sizeof(rsa_modpow_vecs[0])));

		for (i = 0; i < (int)(sizeof(rsa_sig_vecs) / sizeof(rsa_sig_vecs[0])); i++) {
			unsigned char sig[256], digest[32], bad[256];
			int slen = hex2bin(rsa_sig_vecs[i].sig_hex, sig, (int)sizeof(sig));
			hex2bin(rsa_sig_vecs[i].digest_hex, digest, 32);
			if (slen != n_len) {
				printf("  [FAIL] sig length (%s)\n", rsa_sig_vecs[i].name);
				g_err++;
				continue;
			}
			if (rsa_verify_pkcs1_sha256(n_be, n_len, e, sig, digest) != 0) {
				printf("  [FAIL] valid signature rejected (%s)\n", rsa_sig_vecs[i].name);
				g_err++;
			}
			/* 篡改签名必须被拒 */
			for (j = 0; j < n_len; j++) bad[j] = sig[j];
			bad[n_len - 1] ^= 0x01;
			if (rsa_verify_pkcs1_sha256(n_be, n_len, e, bad, digest) == 0) {
				printf("  [FAIL] tampered signature accepted (%s)\n", rsa_sig_vecs[i].name);
				g_err++;
			}
			/* 篡改摘要必须被拒 */
			digest[0] ^= 0x01;
			if (rsa_verify_pkcs1_sha256(n_be, n_len, e, sig, digest) == 0) {
				printf("  [FAIL] tampered digest accepted (%s)\n", rsa_sig_vecs[i].name);
				g_err++;
			}
		}
		printf("  rsa_signature: %d vectors (+ 篡改拒绝)\n",
		       (int)(sizeof(rsa_sig_vecs) / sizeof(rsa_sig_vecs[0])));

		for (i = 0; i < (int)(sizeof(rsa_enc_vecs) / sizeof(rsa_enc_vecs[0])); i++) {
			unsigned char msg[128], ps[256], got_em[256], got_ct[256];
			int mlen = hex2bin(rsa_enc_vecs[i].msg_hex, msg, (int)sizeof(msg));
			int plen = hex2bin(rsa_enc_vecs[i].ps_hex, ps, (int)sizeof(ps));
			if (rsa_encrypt_v15_with_ps(n_be, n_len, e, msg, mlen, ps, plen,
			                            got_em, got_ct) != 0) {
				printf("  [FAIL] rsa v1.5 encrypt error (%s)\n", rsa_enc_vecs[i].name);
				g_err++;
				continue;
			}
			check_hex("rsa_em", rsa_enc_vecs[i].name, got_em, n_len, rsa_enc_vecs[i].em_hex);
			check_hex("rsa_ct", rsa_enc_vecs[i].name, got_ct, n_len, rsa_enc_vecs[i].ct_hex);
		}
		printf("  rsa_v15_encrypt: %d vectors\n",
		       (int)(sizeof(rsa_enc_vecs) / sizeof(rsa_enc_vecs[0])));
	}
	printf("=== %s: %d failure(s) ===\n", g_err ? "FAILED" : "ALL PASSED", g_err);
	return g_err ? 1 : 0;
}
