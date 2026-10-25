/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              rsa.c
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
        CatOS 内核 RSA-2048 / PKCS#1 v1.5 (仅公钥运算 + 签名校验)

  为什么只需要公钥运算:
    - TLS 1.2 RSA 密钥交换: 客户端用服务器公钥加密 pre-master secret
      → 只需要 m^e mod n
    - 证书 / ServerKeyExchange 签名校验: 只需要 s^e mod n 再比对 DigestInfo
    所以完全不需要私钥运算 (d / CRT), 代码量和出错面都小很多.

  实现要点:
    - 多精度整数: 32 位 limb, 小端; 最长 2048 位 (64 limb)
    - 32x32 乘法用 unsigned long long 的 mull (无除法, 不需要 libgcc)
    - 取模用位串长除法: 慢但极简; 一次 2048 位模幂约十几毫秒量级
    - PKCS#1 v1.5:
        加密块 EM = 00 || 02 || PS(>=8 字节非零) || 00 || M
        签名块 EM = 00 || 01 || FF..FF || 00 || DigestInfo(SHA-256) || H
    - 无动态分配; 工作区在栈上 (约 1.5KB)

  验证: tools/crypto_test/ 用 .NET 的 BigInteger / RSA 生成向量
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include "type.h"
#include "const.h"
#include "crypto.h"

typedef unsigned long long t_64;

#define BN_LIMBS  64                    /* 64 * 32 = 2048 bit */
#define BN_TMP    (2 * BN_LIMBS)        /* 乘法结果 */

typedef struct {
	t_32 d[BN_LIMBS];
	int  n;                             /* 有效 limb 数 */
} BN;

/*======================================================================*
                          基础操作
 *======================================================================*/

PRIVATE void bn_zero(BN *a)
{
	int i;
	for (i = 0; i < BN_LIMBS; i++) a->d[i] = 0;
	a->n = 0;
}

PRIVATE void bn_trim(BN *a)
{
	while (a->n > 0 && a->d[a->n - 1] == 0) a->n--;
}

/* 大端字节 -> BN (超长输入只保留低 2048 位) */
PRIVATE void bn_from_be(BN *a, const t_8 *p, int len)
{
	int limbs, i, k;

	bn_zero(a);
	if (!p || len <= 0) return;

	limbs = (len + 3) / 4;
	if (limbs > BN_LIMBS) {
		int drop = (limbs - BN_LIMBS) * 4;
		p += drop;
		len -= drop;
		limbs = BN_LIMBS;
	}
	for (i = 0; i < limbs; i++) {
		int off = len - 4 * (i + 1);
		t_32 v = 0;
		for (k = 0; k < 4; k++) {
			int idx = off + k;
			v <<= 8;
			if (idx >= 0 && idx < len) v |= (t_32)p[idx];
		}
		a->d[i] = v;
	}
	a->n = limbs;
	bn_trim(a);
}

/* BN -> 定长大端字节 */
PRIVATE void bn_to_be(const BN *a, t_8 *out, int len)
{
	int i;

	for (i = 0; i < len; i++) {
		int j = len - 1 - i;            /* 从最低字节数起 */
		int limb = j / 4;
		int shift = (j % 4) * 8;
		t_32 v = (limb < a->n) ? a->d[limb] : 0;
		out[i] = (t_8)((v >> shift) & 0xFF);
	}
}

PRIVATE int bn_cmp(const BN *a, const BN *b)
{
	int i;
	int n = (a->n > b->n) ? a->n : b->n;

	for (i = n - 1; i >= 0; i--) {
		t_32 av = (i < a->n) ? a->d[i] : 0;
		t_32 bv = (i < b->n) ? b->d[i] : 0;
		if (av > bv) return 1;
		if (av < bv) return -1;
	}
	return 0;
}

/* 定长数组比较: 返回 1/0/-1 */
PRIVATE int arr_cmp(const t_32 *x, const t_32 *y, int n)
{
	int i;
	for (i = n - 1; i >= 0; i--) {
		if (x[i] > y[i]) return 1;
		if (x[i] < y[i]) return -1;
	}
	return 0;
}

/* 定长数组减法: x -= y (要求 x >= y) */
PRIVATE void arr_sub(t_32 *x, const t_32 *y, int n)
{
	int i;
	t_32 borrow = 0;

	for (i = 0; i < n; i++) {
		t_32 xv = x[i];
		t_32 yv = y[i];
		t_32 diff = xv - yv;
		t_32 b1 = (xv < yv) ? 1 : 0;
		t_32 res = diff - borrow;
		if (diff < borrow) b1 = 1;
		x[i] = res;
		borrow = b1;
	}
}

/* 乘法: prod = a * b (prod 长度 2*BN_LIMBS) */
PRIVATE void bn_mul(t_32 *prod, const BN *a, const BN *b)
{
	int i, j;

	for (i = 0; i < BN_TMP; i++) prod[i] = 0;
	if (a->n == 0 || b->n == 0) return;

	for (i = 0; i < a->n; i++) {
		t_64 carry = 0;
		for (j = 0; j < b->n; j++) {
			t_64 cur = (t_64)a->d[i] * (t_64)b->d[j] + (t_64)prod[i + j] + carry;
			prod[i + j] = (t_32)cur;
			carry = cur >> 32;
		}
		{
			int idx = i + b->n;
			t_64 cur = (t_64)prod[idx] + carry;
			prod[idx] = (t_32)cur;
			if ((t_32)(cur >> 32) && idx + 1 < BN_TMP) {
				prod[idx + 1] += (t_32)(cur >> 32);
			}
		}
	}
}

/* r = a mod m, a 为 2*BN_LIMBS 的 limb 数组 */
PRIVATE void bn_mod(t_32 *out_limbs, const t_32 *a, const BN *m)
{
	t_32 cur[BN_LIMBS + 1];
	int i, k, bits, lim;

	for (k = 0; k <= BN_LIMBS; k++) cur[k] = 0;   /* 消除未初始化告警 */

	if (m->n == 0) {
		for (k = 0; k < BN_LIMBS; k++) out_limbs[k] = 0;
		return;
	}

	/* a 的位长 */
	lim = BN_TMP - 1;
	while (lim >= 0 && a[lim] == 0) lim--;
	if (lim < 0) {
		for (k = 0; k < BN_LIMBS; k++) out_limbs[k] = 0;
		return;
	}
	bits = lim * 32;
	{
		t_32 v = a[lim];
		while (v) { v >>= 1; bits++; }
	}

	for (k = 0; k <= m->n; k++) cur[k] = 0;

	for (i = bits - 1; i >= 0; i--) {
		t_32 carry = 0;

		/* cur <<= 1 */
		for (k = 0; k <= m->n; k++) {
			t_32 nv = (cur[k] << 1) | carry;
			carry = cur[k] >> 31;
			cur[k] = nv;
		}
		/* 补入 a 的第 i 位 */
		if ((a[i / 32] >> (i % 32)) & 1) cur[0] |= 1;

		/* cur >= m ? cur -= m (cur < 2m 恒成立, 减一次即可) */
		{
			t_32 mtmp[BN_LIMBS + 1];
			for (k = 0; k <= m->n; k++) mtmp[k] = (k < m->n) ? m->d[k] : 0;
			if (arr_cmp(cur, mtmp, m->n + 1) >= 0) {
				arr_sub(cur, mtmp, m->n + 1);
			}
		}
	}

	for (k = 0; k < BN_LIMBS; k++) out_limbs[k] = cur[k];
}

/* r = a*b mod m */
PRIVATE void bn_modmul(BN *r, const BN *a, const BN *b, const BN *m)
{
	t_32 prod[BN_TMP];

	bn_mul(prod, a, b);
	bn_mod(r->d, prod, m);
	r->n = m->n;
	bn_trim(r);
}

/* r = base^e mod m (e 为 32 位) */
PRIVATE void bn_modexp(BN *r, const BN *base, t_32 e, const BN *m)
{
	BN acc;
	BN b;
	int i;
	int started = 0;

	bn_zero(&acc);
	acc.d[0] = 1;
	acc.n = 1;
	b = *base;

	for (i = 31; i >= 0; i--) {
		int bit = (int)((e >> i) & 1);
		if (!started) {
			if (!bit) continue;
			started = 1;
		}
		bn_modmul(&acc, &acc, &acc, m);
		if (bit) bn_modmul(&acc, &acc, &b, m);
	}
	if (!started) {
		bn_zero(&acc);
		acc.d[0] = 1;
		acc.n = 1;
	}
	*r = acc;
}

/*======================================================================*
                          RSA 公钥运算
 *======================================================================*/

/* out = base^e mod n, out 为 n_len 字节大端. 返回 0=成功 */
PUBLIC int rsa_modexp(const t_8 *n, int n_len, t_32 e,
                      const t_8 *base, int base_len,
                      t_8 *out)
{
	BN m, b, r;
	t_32 prod[BN_TMP];
	int i;

	if (!n || !out || n_len <= 0 || n_len > 256) return -1;
	if (!base || base_len < 0) return -1;

	bn_from_be(&m, n, n_len);
	if (m.n == 0) return -1;

	bn_from_be(&b, base, base_len);
	if (bn_cmp(&b, &m) >= 0) {
		for (i = 0; i < BN_TMP; i++) prod[i] = (i < b.n) ? b.d[i] : 0;
		bn_mod(b.d, prod, &m);
		b.n = m.n;
		bn_trim(&b);
	}

	bn_modexp(&r, &b, e, &m);
	bn_to_be(&r, out, n_len);
	return 0;
}

/* PKCS#1 v1.5 + SHA-256 的 DigestInfo 前缀 (19 字节) */
PRIVATE const t_8 rsa_sha256_di[19] = {
	0x30, 0x31, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01,
	0x65, 0x03, 0x04, 0x02, 0x01, 0x05, 0x00, 0x04, 0x20
};

/* 校验 RSA PKCS#1 v1.5 (SHA-256) 签名. 返回 0=通过, <0=不通过 */
PUBLIC int rsa_verify_pkcs1_sha256(const t_8 *n, int n_len, t_32 e,
                                   const t_8 *sig,
                                   const t_8 *hash32)
{
	t_8 em[256];
	int k;
	int tlen = (int)sizeof(rsa_sha256_di) + 32;

	if (!n || !sig || !hash32) return -1;
	if (n_len < tlen + 11 || n_len > 256) return -1;
	if (rsa_modexp(n, n_len, e, sig, n_len, em) != 0) return -2;

	if (em[0] != 0x00 || em[1] != 0x01) return -3;
	k = 2;
	while (k < n_len - tlen && em[k] == 0xFF) k++;
	if (k < 10) return -4;                       /* PS 至少 8 字节 FF */
	if (em[k] != 0x00) return -5;
	k++;
	if (k != n_len - tlen) return -6;
	if (crypto_memcmp_ct(&em[k], rsa_sha256_di, (int)sizeof(rsa_sha256_di)) != 0) {
		return -7;
	}
	if (crypto_memcmp_ct(&em[k + (int)sizeof(rsa_sha256_di)], hash32, 32) != 0) {
		return -8;
	}
	return 0;
}

/* 用给定 PS 字节构造 v1.5 加密块并模幂 (测试/确定性用)
 * 要求 ps 全非零, 2 + ps_len + 1 + msg_len == n_len, ps_len >= 8 */
PUBLIC int rsa_encrypt_v15_with_ps(const t_8 *n, int n_len, t_32 e,
                                   const t_8 *msg, int msg_len,
                                   const t_8 *ps, int ps_len,
                                   t_8 *em, t_8 *out)
{
	int i;

	if (!n || !msg || !ps || !em || !out) return -1;
	if (n_len <= 0 || n_len > 256) return -1;
	if (msg_len < 0 || ps_len < 8) return -1;
	if (2 + ps_len + 1 + msg_len != n_len) return -1;

	em[0] = 0x00;
	em[1] = 0x02;
	for (i = 0; i < ps_len; i++) {
		if (ps[i] == 0) return -1;
		em[2 + i] = ps[i];
	}
	em[2 + ps_len] = 0x00;
	for (i = 0; i < msg_len; i++) em[3 + ps_len + i] = msg[i];

	return rsa_modexp(n, n_len, e, em, n_len, out);
}

/* 演示级随机源 (正式版应改用 RDRAND/RTC/中断计时混合, 见 README) */
PRIVATE t_32 rsa_rng_state;

PUBLIC void rsa_random_seed(t_32 seed)
{
	rsa_rng_state = seed ? seed : 0x9E3779B9u;
}

PUBLIC void rsa_random_bytes(t_8 *buf, int len)
{
	int i;

	if (!buf || len <= 0) return;
	if (!rsa_rng_state) rsa_rng_state = 0x9E3779B9u;
	for (i = 0; i < len; i++) {
		rsa_rng_state = rsa_rng_state * 1103515245u + 12345u;
		buf[i] = (t_8)(rsa_rng_state >> 16);
	}
}

/* 生成 v1.5 加密块并模幂 (PS 来自随机源) */
PUBLIC int rsa_encrypt_v15(const t_8 *n, int n_len, t_32 e,
                           const t_8 *msg, int msg_len,
                           t_8 *out)
{
	t_8 em[256];
	t_8 ps[256];
	int ps_len = n_len - 3 - msg_len;
	int i;

	if (!out || n_len <= 0 || n_len > 256) return -1;
	if (ps_len < 8) return -1;

	rsa_random_bytes(ps, ps_len);
	for (i = 0; i < ps_len; i++) {
		if (ps[i] == 0) ps[i] = 0x42;
	}
	return rsa_encrypt_v15_with_ps(n, n_len, e, msg, msg_len, ps, ps_len,
	                               em, out);
}
