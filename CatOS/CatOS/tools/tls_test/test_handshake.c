/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
     tools/tls_test/test_handshake.c — TLS 1.2 握手两阶段互验 (C 侧)

  阶段 1: 生成 ClientHello / ClientKeyExchange, 用服务器公钥加密 pre-master,
          派生 master secret 与密钥块, 计算 client Finished 并加密封装,
          把所有中间结果写成 "key=hex" 文件
  阶段 2: 读取 Python 服务端产出的加密 Finished 记录, 解密 + 校验 MAC,
          并核对 server Finished 的 verify_data

  服务端侧的 PRF/HMAC/AES/RSA 解密全部由 server_emu.py 用 Python 独立实现,
  所以这是跨实现互验, 不是"自己验自己".

  编译: gcc -I shim -I ../../include -O2 -Wall -o hs_test.exe test_handshake.c
  运行: ./hs_test.exe phase1 client_out.txt server_out.txt
        ./hs_test.exe phase2 client_out.txt server_out.txt
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include <stdio.h>

#include "type.h"
#include "const.h"
#include "crypto.h"
#include "tls.h"

#include "../../lib/crypto.c"
#include "../../lib/rsa.c"
#include "../../lib/tls.c"
#include "hs_pub.h"

static int g_err;

#define CHECK(cond, msg)                                              \
	do {                                                              \
		if (!(cond)) {                                                \
			printf("  [FAIL] %s (line %d)\n", msg, __LINE__);         \
			g_err++;                                                  \
		}                                                             \
	} while (0)

/* --- 本地字符串/内存工具 (shim 目录屏蔽了系统 <string.h>) --- */
static int s_len(const char *s) { int n = 0; while (s[n]) n++; return n; }

static int s_ncmp(const char *a, const char *b, int n)
{
	int i;
	for (i = 0; i < n; i++) {
		if (a[i] != b[i]) return 1;
	}
	return 0;
}

static void b_copy(unsigned char *d, const unsigned char *s, int n)
{
	int i;
	for (i = 0; i < n; i++) d[i] = s[i];
}

static void b_zero(unsigned char *d, int n)
{
	int i;
	for (i = 0; i < n; i++) d[i] = 0;
}

static int b_cmp(const unsigned char *a, const unsigned char *b, int n)
{
	int i;
	for (i = 0; i < n; i++) {
		if (a[i] != b[i]) return 1;
	}
	return 0;
}

static void s_copy(char *d, const char *s, int max)
{
	int i;
	for (i = 0; i < max - 1 && s[i]; i++) d[i] = s[i];
	d[i] = 0;
}

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

static int read_kv(const char *path, const char *key, char *out, int out_max)
{
	FILE *f = fopen(path, "r");
	char line[8192];
	int klen = s_len(key);

	if (!f) return 0;
	out[0] = 0;
	while (fgets(line, (int)sizeof(line), f)) {
		if (s_ncmp(line, key, klen) == 0 && line[klen] == '=') {
			int i = klen + 1;
			int j = 0;
			while (line[i] && line[i] != '\r' && line[i] != '\n' && j < out_max - 1) {
				out[j++] = line[i++];
			}
			out[j] = 0;
			fclose(f);
			return j;
		}
	}
	fclose(f);
	return 0;
}

static void write_kv(FILE *f, const char *key, const unsigned char *b, int n)
{
	int i;
	fprintf(f, "%s=", key);
	for (i = 0; i < n; i++) fprintf(f, "%02x", b[i]);
	fprintf(f, "\n");
}

static int hs_msg(unsigned char *out, int cap, t_8 type,
                  const unsigned char *body, int blen)
{
	if (cap < blen + 4) return -1;
	out[0] = type;
	out[1] = (unsigned char)(blen >> 16);
	out[2] = (unsigned char)(blen >> 8);
	out[3] = (unsigned char)blen;
	b_copy(out + 4, body, blen);
	return blen + 4;
}

/* 生成会话的固定输入, 两阶段必须一致 */
static void fixed_inputs(unsigned char *client_random, unsigned char *server_random,
                         unsigned char *premaster)
{
	int i;
	for (i = 0; i < 32; i++) client_random[i] = (unsigned char)(0x10 + i);
	for (i = 0; i < 32; i++) server_random[i] = (unsigned char)(0x80 + i);
	premaster[0] = 0x03;
	premaster[1] = 0x03;
	for (i = 2; i < 48; i++) premaster[i] = (unsigned char)(0x30 + i);
}

/* 建立会话并完成 ClientHello + ClientKeyExchange (phase1/2 共用) */
static int setup_session(TLS_SESSION *sess, const char *cfile,
                         unsigned char *hello, int *hello_len,
                         unsigned char *cke, int *cke_len)
{
	static unsigned char client_random[32], server_random[32], premaster[48];
	int i;

	fixed_inputs(client_random, server_random, premaster);
	if (tls_session_init(sess, TLS_SUITE_RSA_AES128_CBC_SHA) != TLS_OK) return -1;
	b_copy(sess->client_random, client_random, 32);
	b_copy(sess->server_random, server_random, 32);

	/* ClientHello */
	{
		TLS_CLIENT_HELLO ch;
		int n;
		b_zero((unsigned char *)&ch, (int)sizeof(ch));
		ch.version_major = 3;
		ch.version_minor = 3;
		b_copy(ch.random, client_random, 32);
		ch.suites[0] = TLS_SUITE_RSA_AES128_CBC_SHA;
		ch.suite_count = 1;
		s_copy(ch.server_name, "handshake.test", (int)sizeof(ch.server_name));
		n = tls_build_client_hello(&ch, hello, 512);
		if (n <= 0) return -1;
		*hello_len = n;
		tls_transcript_add(sess, hello, n);
	}

	/* ClientKeyExchange */
	{
		unsigned char n_be[256], ct[256], body[260];
		int n_len = hex2bin(hs_n_hex, n_be, (int)sizeof(n_be));
		int blen = 2 + n_len;

		if (n_len != HS_N_LEN) return -1;
		if (rsa_encrypt_v15(n_be, n_len, 65537u, premaster, 48, ct) != 0) return -1;
		body[0] = (unsigned char)(n_len >> 8);
		body[1] = (unsigned char)n_len;
		b_copy(body + 2, ct, n_len);
		*cke_len = hs_msg(cke, 512, TLS_HS_CLIENT_KEY_EXCH, body, blen);
		if (*cke_len <= 0) return -1;
		tls_transcript_add(sess, cke, *cke_len);

		/* 记录阶段 1 产物 */
		{
			FILE *f = fopen(cfile, "w");
			if (!f) return -1;
			write_kv(f, "client_random", client_random, 32);
			write_kv(f, "server_random", server_random, 32);
			write_kv(f, "premaster", premaster, 48);
			write_kv(f, "rsa_ct", ct, n_len);
			write_kv(f, "client_hello", hello, *hello_len);
			write_kv(f, "client_key_exchange", cke, *cke_len);
			fclose(f);
		}
	}

	if (tls_derive_keys(sess, premaster) != TLS_OK) return -1;
	(void)i;
	return 0;
}

int main(int argc, char **argv)
{
	const char *phase = (argc > 1) ? argv[1] : "phase1";
	const char *cfile = (argc > 2) ? argv[2] : "client_out.txt";
	const char *sfile = (argc > 3) ? argv[3] : "server_out.txt";
	static unsigned char hello[512], cke[512];
	static unsigned char fin[16], sealed[512];
	static TLS_SESSION sess;
	int hello_len = 0, cke_len = 0;

	printf("=== TLS handshake %s ===\n", phase);

	if (setup_session(&sess, cfile, hello, &hello_len, cke, &cke_len) != 0) {
		printf("  [FAIL] session setup\n");
		return 1;
	}
	CHECK(sess.mac_len == 20 && sess.enc_len == 16, "suite key sizes");
	CHECK(hs_e_hex[0] != '%', "public exponent present");

	if (phase[0] == 'p' && phase[5] == '1') {
		/* ---------- client Finished ---------- */
		unsigned char vd[TLS_FINISHED_LEN];
		int flen, slen;

		CHECK(tls_finished_verify(&sess, 1, vd) == TLS_OK, "client finished");
		flen = hs_msg(fin, (int)sizeof(fin), TLS_HS_FINISHED, vd, TLS_FINISHED_LEN);
		CHECK(flen == 16, "finished message");
		CHECK(hs_msg(fin, 8, TLS_HS_FINISHED, vd, TLS_FINISHED_LEN) == -1,
		      "tiny buffer rejected");

		sess.encrypted = 1;
		slen = tls_seal(&sess, TLS_CT_HANDSHAKE, fin, flen, sealed, (int)sizeof(sealed));
		CHECK(slen > 0, "client Finished sealed");

		tls_transcript_add(&sess, fin, flen);
		{
			unsigned char svd[TLS_FINISHED_LEN];
			FILE *f;

			CHECK(tls_finished_verify(&sess, 0, svd) == TLS_OK, "server finished expected");
			f = fopen(cfile, "a");
			CHECK(f != 0, "append artifacts");
			if (f) {
				write_kv(f, "master_secret", sess.master_secret, TLS_MASTER_LEN);
				write_kv(f, "client_finished", fin, flen);
				write_kv(f, "sealed_client_finished", sealed, slen);
				write_kv(f, "expected_server_finished", svd, TLS_FINISHED_LEN);
				write_kv(f, "client_mac", sess.client_mac, sess.mac_len);
				write_kv(f, "client_key", sess.client_key, sess.enc_len);
				write_kv(f, "server_mac", sess.server_mac, sess.mac_len);
				write_kv(f, "server_key", sess.server_key, sess.enc_len);
				fclose(f);
			}
		}
		printf("  artifacts: %s\n", cfile);
	} else {
		/* ---------- phase2: 服务端加密 Finished ---------- */
		static char hexbuf[8192];
		static unsigned char sealed_s[4096], frag[2048], want[64];
		int n, blen, flen;
		unsigned char mine[TLS_FINISHED_LEN];

		n = read_kv(sfile, "sealed_server_finished", hexbuf, (int)sizeof(hexbuf));
		CHECK(n > 0, "server finished present");
		if (n > 0) {
			blen = hex2bin(hexbuf, sealed_s, (int)sizeof(sealed_s));
			sess.encrypted = 1;
			sess.seq_in = 0;
			flen = tls_unseal(&sess, TLS_CT_HANDSHAKE, sealed_s, blen, frag,
			                  (int)sizeof(frag));
			CHECK(flen == 16, "server Finished decrypted + MAC verified");
			if (flen == 16) {
				CHECK(frag[0] == TLS_HS_FINISHED, "decrypted type is Finished");
				/* 真实协议里: 客户端发完自己的 Finished 后要把它加进 transcript,
				 * 再校验服务端的 Finished */
				{
					unsigned char cli_vd[TLS_FINISHED_LEN];
					unsigned char cli_msg[16];
					CHECK(tls_finished_verify(&sess, 1, cli_vd) == TLS_OK,
					      "recompute client finished");
					CHECK(hs_msg(cli_msg, (int)sizeof(cli_msg), TLS_HS_FINISHED,
					             cli_vd, TLS_FINISHED_LEN) == 16,
					      "rebuild client finished message");
					CHECK(b_cmp(cli_msg + 4, frag + 4, TLS_FINISHED_LEN) != 0,
					      "sanity: client/server verify_data differ");
					tls_transcript_add(&sess, cli_msg, 16);
				}
				CHECK(tls_finished_verify(&sess, 0, mine) == TLS_OK, "local server finished");
				CHECK(b_cmp(frag + 4, mine, TLS_FINISHED_LEN) == 0,
				      "server verify_data matches local computation");
				read_kv(sfile, "server_finished", hexbuf, (int)sizeof(hexbuf));
				hex2bin(hexbuf, want, (int)sizeof(want));
				CHECK(b_cmp(frag + 4, want + 4, TLS_FINISHED_LEN) == 0,
				      "server verify_data matches python side");
			}
			/* 篡改密文: MAC 必须失败 */
			sealed_s[blen - 1] ^= 0x01;
			sess.seq_in = 0;
			CHECK(tls_unseal(&sess, TLS_CT_HANDSHAKE, sealed_s, blen, frag,
			                 (int)sizeof(frag)) < 0,
			      "tampered server record rejected");
			/* 截断记录 */
			sess.seq_in = 0;
			CHECK(tls_unseal(&sess, TLS_CT_HANDSHAKE, sealed_s, 20, frag,
			                 (int)sizeof(frag)) < 0,
			      "truncated server record rejected");
		}
	}

	printf("=== %s: %d failure(s) ===\n", g_err ? "FAILED" : "ALL PASSED", g_err);
	return g_err ? 1 : 0;
}
