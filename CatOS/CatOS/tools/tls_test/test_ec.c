/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
     tools/tls_test/test_ec.c — P-256 域运算/点乘/ECDH 测试

  向量由 gen_ec_vectors.py 用一份独立的纯 Python P-256 实现生成
  (Python 大整数直接算, 与被测的 Montgomery/雅可比实现毫无共用).

  编译: gcc -I shim -I ../../include -O2 -Wall -o ec_check.exe test_ec.c
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include <stdio.h>

#include "type.h"
#include "const.h"
#include "ec.h"

#include "../../lib/ec.c"
#include "ec_vectors.h"

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

static int unhex(const char *hex, unsigned char *out, int max)
{
	int n = 0;
	while (hex[0] && hex[1] && n < max) {
		int hi = hexval(hex[0]);
		int lo = hexval(hex[1]);
		if (hi < 0 || lo < 0) break;
		out[n++] = (unsigned char)((hi << 4) | lo);
		hex += 2;
	}
	return n;
}

static int same(const unsigned char *a, const unsigned char *b, int n)
{
	int i;
	for (i = 0; i < n; i++) {
		if (a[i] != b[i]) return 0;
	}
	return 1;
}

static void check_fe(const char *what, const char *name,
                     const unsigned char *got, const char *want_hex)
{
	unsigned char want[32];
	unhex(want_hex, want, 32);
	if (!same(got, want, 32)) {
		int i;
		printf("  [FAIL] %s %s\n    got  ", what, name);
		for (i = 0; i < 32; i++) printf("%02x", got[i]);
		printf("\n    want %s\n", want_hex);
		g_err++;
	}
}

int main(void)
{
	static unsigned char a[32], b[32], r[32];
	EC_FE fa, fb, fr;
	int i;

	printf("=== P-256 field / point / ECDH test ===\n");
	CHECK(ec_p256_init() == 0, "init");

	/* ---------- 域运算 ---------- */
	for (i = 0; i < (int)(sizeof(ec_fe_vecs) / sizeof(ec_fe_vecs[0])); i++) {
		unhex(ec_fe_vecs[i].a, a, 32);
		unhex(ec_fe_vecs[i].b, b, 32);
		ec_fe_from_bytes(&fa, a, 32);
		ec_fe_from_bytes(&fb, b, 32);

		ec_fe_add(&fr, &fa, &fb);
		ec_fe_to_bytes(&fr, r, 32);
		check_fe("add", ec_fe_vecs[i].a, r, ec_fe_vecs[i].add);

		ec_fe_sub(&fr, &fa, &fb);
		ec_fe_to_bytes(&fr, r, 32);
		check_fe("sub", ec_fe_vecs[i].a, r, ec_fe_vecs[i].sub);

		ec_fe_mul(&fr, &fa, &fb);
		ec_fe_to_bytes(&fr, r, 32);
		check_fe("mul", ec_fe_vecs[i].a, r, ec_fe_vecs[i].mul);
	}
	printf("  field add/sub/mul: %d vectors\n",
	       (int)(sizeof(ec_fe_vecs) / sizeof(ec_fe_vecs[0])));

	for (i = 0; i < (int)(sizeof(ec_inv_vecs) / sizeof(ec_inv_vecs[0])); i++) {
		unhex(ec_inv_vecs[i].a, a, 32);
		ec_fe_from_bytes(&fa, a, 32);
		CHECK(ec_fe_inv(&fr, &fa) == 0, "inverse computed");
		ec_fe_to_bytes(&fr, r, 32);
		check_fe("inv", ec_inv_vecs[i].a, r, ec_inv_vecs[i].inv);
		/* a * a^-1 == 1 */
		{
			EC_FE t, one;
			ec_fe_mul(&t, &fa, &fr);
			ec_fe_to_bytes(&t, r, 32);
			one.v[0] = 11;  /* 占位, 避免未初始化告警 */
			(void)one;
			{
				unsigned char oneb[32];
				int k;
				for (k = 0; k < 32; k++) oneb[k] = 0;
				oneb[31] = 1;
				CHECK(same(r, oneb, 32), "a * a^-1 == 1");
			}
		}
	}
	printf("  field inverse: %d vectors\n",
	       (int)(sizeof(ec_inv_vecs) / sizeof(ec_inv_vecs[0])));

	/* ---------- 生成元在曲线上 ---------- */
	{
		EC_POINT g;
		ec_p256_generator(&g);
		CHECK(ec_point_on_curve(&g) == 1, "generator is on P-256");

		/* ---------- 标量乘 ---------- */
		for (i = 0; i < (int)(sizeof(ec_mul_vecs) / sizeof(ec_mul_vecs[0])); i++) {
			EC_FE k;
			EC_POINT q;
			unsigned char kb[32], want[32];
			unhex(ec_mul_vecs[i].k, kb, 32);
			ec_fe_from_bytes(&k, kb, 32);
			CHECK(ec_point_mul(&q, &k, &g) == 0, "point mul");
			CHECK(ec_point_on_curve(&q) == 1, "result on curve");
			ec_fe_to_bytes(&q.x, r, 32);
			unhex(ec_mul_vecs[i].qx, want, 32);
			CHECK(same(r, want, 32), "k*G x");
			ec_fe_to_bytes(&q.y, r, 32);
			unhex(ec_mul_vecs[i].qy, want, 32);
			CHECK(same(r, want, 32), "k*G y");
		}
		printf("  scalar mult: %d vectors\n",
		       (int)(sizeof(ec_mul_vecs) / sizeof(ec_mul_vecs[0])));

		/* ---------- 点加: 2G + G == 3G ---------- */
		{
			EC_FE two, three;
			EC_POINT g2, g3, sum;
			unsigned char kb[32];
			kb[31] = 2;
			ec_fe_from_bytes(&two, kb, 32);
			kb[31] = 3;
			ec_fe_from_bytes(&three, kb, 32);
			ec_point_mul(&g2, &two, &g);
			ec_point_mul(&g3, &three, &g);
			ec_point_add(&sum, &g2, &g);
			CHECK(!sum.inf, "2G+G is not infinity");
			CHECK(ec_fe_cmp(&sum.x, &g3.x) == 0 && ec_fe_cmp(&sum.y, &g3.y) == 0,
			      "2G + G == 3G");
			/* G + (-G) == 无穷远 */
			{
				EC_POINT neg, z;
				neg = g;
				ec_fe_sub(&neg.y, &fr, &fr);        /* 0 */
				ec_fe_sub(&neg.y, &neg.y, &g.y);    /* -Gy */
				{
					EC_FE zero;
					ec_fe_from_bytes(&zero, (const t_8 *)"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00", 32);
					ec_fe_sub(&neg.y, &zero, &g.y);
				}
				ec_point_add(&z, &g, &neg);
				CHECK(z.inf, "G + (-G) == infinity");
			}
		}

		/* ---------- ECDH ---------- */
		for (i = 0; i < (int)(sizeof(ec_ecdh_vecs) / sizeof(ec_ecdh_vecs[0])); i++) {
			unsigned char d1[32], d2[32], qx[32], qy[32], want[32];
			EC_POINT q1, q2;
			EC_FE t;

			unhex(ec_ecdh_vecs[i].d1, d1, 32);
			unhex(ec_ecdh_vecs[i].d2, d2, 32);
			unhex(ec_ecdh_vecs[i].q1x, qx, 32);
			unhex(ec_ecdh_vecs[i].q1y, qy, 32);
			ec_fe_from_bytes(&q1.x, qx, 32);
			ec_fe_from_bytes(&q1.y, qy, 32);
			q1.inf = 0;
			unhex(ec_ecdh_vecs[i].q2x, qx, 32);
			unhex(ec_ecdh_vecs[i].q2y, qy, 32);
			ec_fe_from_bytes(&q2.x, qx, 32);
			ec_fe_from_bytes(&q2.y, qy, 32);
			q2.inf = 0;

			CHECK(ec_point_on_curve(&q1) && ec_point_on_curve(&q2),
			      "peer public keys are valid");

			unhex(ec_ecdh_vecs[i].shared, want, 32);
			CHECK(ec_ecdh(d1, &q2, r) == 0, "ecdh d1*Q2");
			CHECK(same(r, want, 32), "shared secret d1*Q2");
			CHECK(ec_ecdh(d2, &q1, r) == 0, "ecdh d2*Q1");
			CHECK(same(r, want, 32), "shared secret d2*Q1");

			/* 无效点必须被拒绝 */
			{
				EC_POINT bad = q2;
				ec_fe_add_small(&bad.y, &bad.y, 1);
				CHECK(ec_ecdh(d1, &bad, r) != 0, "off-curve peer rejected");
			}
			(void)t;
		}
		printf("  ecdh: %d vectors\n",
		       (int)(sizeof(ec_ecdh_vecs) / sizeof(ec_ecdh_vecs[0])));
	}

	printf("=== %s: %d failure(s) ===\n", g_err ? "FAILED" : "ALL PASSED", g_err);
	return g_err ? 1 : 0;
}
