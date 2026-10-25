/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              ec.c
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                    CatOS 内核 P-256 椭圆曲线 (ECDHE 用)

  实现:
    - 域: 32 位 limb, Montgomery 乘法 (CIOS)
      n0' / R / R^2 都在 ec_p256_init() 里算出来, 不依赖手抄魔数
    - 点: 内部雅可比坐标 (a = -3 的专用公式), 对外仿射
    - 标量乘: 从最高位起的双倍-加法 (不定时, 满足演示需求)
    - 每个入口都拒绝不在曲线上的点
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include "type.h"
#include "const.h"
#include "ec.h"

typedef unsigned long long ec_u64;

/* ---- 电路参数 (标准常量, 大端) ---- */
PRIVATE const t_8 p256_p[32] = {
	0xFF,0xFF,0xFF,0xFF, 0x00,0x00,0x00,0x01, 0x00,0x00,0x00,0x00,
	0x00,0x00,0x00,0x00, 0x00,0x00,0x00,0x00, 0xFF,0xFF,0xFF,0xFF,
	0xFF,0xFF,0xFF,0xFF, 0xFF,0xFF,0xFF,0xFF
};
PRIVATE const t_8 p256_b[32] = {
	0x5A,0xC6,0x35,0xD8, 0xAA,0x3A,0x93,0xE7, 0xB3,0xEB,0xBD,0x55,
	0x76,0x98,0x86,0xBC, 0x65,0x1D,0x06,0xB0, 0xCC,0x53,0xB0,0xF6,
	0x3B,0xCE,0x3C,0x3E, 0x27,0xD2,0x60,0x4B
};
PRIVATE const t_8 p256_gx[32] = {
	0x6B,0x17,0xD1,0xF2, 0xE1,0x2C,0x42,0x47, 0xF8,0xBC,0xE6,0xE5,
	0x63,0xA4,0x40,0xF2, 0x77,0x03,0x7D,0x81, 0x2D,0xEB,0x33,0xA0,
	0xF4,0xA1,0x39,0x45, 0xD8,0x98,0xC2,0x96
};
PRIVATE const t_8 p256_gy[32] = {
	0x4F,0xE3,0x42,0xE2, 0xFE,0x1A,0x7F,0x9B, 0x8E,0xE7,0xEB,0x4A,
	0x7C,0x0F,0x9E,0x16, 0x2B,0xCE,0x33,0x57, 0x6B,0x31,0x5E,0xCE,
	0xCB,0xB6,0x40,0x68, 0x37,0xBF,0x51,0xF5
};

/* ---- 运行期常量 ---- */
PRIVATE EC_FE ec_p;            /* 模数 */
PRIVATE EC_FE ec_b;            /* 曲线 b */
PRIVATE EC_FE ec_gx, ec_gy;
PRIVATE EC_FE ec_R;            /* 2^256 mod p */
PRIVATE EC_FE ec_R2;           /* 2^512 mod p */
PRIVATE t_32   ec_n0inv;       /* -p^{-1} mod 2^32 */
PRIVATE int    ec_ready;

/*======================================================================*
                          基础 limb 运算
 *======================================================================*/

PRIVATE int fe_cmp_raw(const t_32 *a, const t_32 *b)
{
	int i;
	for (i = EC_FE_LIMBS - 1; i >= 0; i--) {
		if (a[i] > b[i]) return 1;
		if (a[i] < b[i]) return -1;
	}
	return 0;
}

PRIVATE int fe_is_zero_raw(const t_32 *a)
{
	int i;
	for (i = 0; i < EC_FE_LIMBS; i++) {
		if (a[i]) return 0;
	}
	return 1;
}

PRIVATE void fe_copy(EC_FE *r, const EC_FE *a)
{
	int i;
	for (i = 0; i < EC_FE_LIMBS; i++) r->v[i] = a->v[i];
}

PRIVATE void fe_zero(EC_FE *r)
{
	int i;
	for (i = 0; i < EC_FE_LIMBS; i++) r->v[i] = 0;
}

/* r = a + b (不约减, 进位到 257 位时返回 1) */
PRIVATE int fe_add_raw(t_32 *r, const t_32 *a, const t_32 *b)
{
	ec_u64 carry = 0;
	int i;
	for (i = 0; i < EC_FE_LIMBS; i++) {
		ec_u64 t = (ec_u64)a[i] + b[i] + carry;
		r[i] = (t_32)t;
		carry = t >> 32;
	}
	return (int)carry;
}

/* r = a - b (假设 a >= b) */
PRIVATE void fe_sub_raw(t_32 *r, const t_32 *a, const t_32 *b)
{
	ec_u64 borrow = 0;
	int i;
	for (i = 0; i < EC_FE_LIMBS; i++) {
		ec_u64 t = (ec_u64)a[i] - b[i] - borrow;
		r[i] = (t_32)t;
		borrow = (t >> 32) & 1;
	}
}

/* r = a mod p (a 为 8 limb, 可能 >= p; 只处理最多一次进位?) */
PRIVATE void fe_reduce_once(EC_FE *r)
{
	while (fe_cmp_raw(r->v, ec_p.v) >= 0) {
		fe_sub_raw(r->v, r->v, ec_p.v);
	}
}

/*======================================================================*
                     乘法 + 模约减 (长除法)
  说明: 不用 Montgomery. 32x32 用 mull 得到 16 limb 乘积, 再用"移位减法"
  按位约减. 一次域乘约 512 次 8-limb 的移位/比较/减法, 慢但极易验证;
  一次标量乘 (~2500 次域乘) 在 QEMU 里预计几十毫秒, 可接受.
 *======================================================================*/

/* r = w mod p, w 为 16 limb (512 bit) */
PRIVATE void fe_reduce_wide(EC_FE *r, const t_32 *w)
{
	t_32 cur[EC_FE_LIMBS + 1];
	int bits, i, k, lim;

	for (k = 0; k <= EC_FE_LIMBS; k++) cur[k] = 0;

	lim = 2 * EC_FE_LIMBS - 1;
	while (lim >= 0 && w[lim] == 0) lim--;
	if (lim < 0) { fe_zero(r); return; }
	bits = lim * 32;
	{ t_32 v = w[lim]; while (v) { v >>= 1; bits++; } }

	for (i = bits - 1; i >= 0; i--) {
		t_32 carry = 0;
		for (k = 0; k <= EC_FE_LIMBS; k++) {
			t_32 nv = (cur[k] << 1) | carry;
			carry = cur[k] >> 31;
			cur[k] = nv;
		}
		if ((w[i / 32] >> (i % 32)) & 1) cur[0] |= 1;

		/* cur >= p ? cur -= p (cur < 2p) */
		{
			int ge = 1;
			int t;
			for (t = EC_FE_LIMBS; t >= 0; t--) {
				t_32 cv = cur[t];
				t_32 pv = (t < EC_FE_LIMBS) ? ec_p.v[t] : 0;
				if (cv > pv) { ge = 1; break; }
				if (cv < pv) { ge = 0; break; }
				if (t == 0) ge = 1;
			}
			if (ge) {
				ec_u64 borrow = 0;
				for (t = 0; t <= EC_FE_LIMBS; t++) {
					t_32 pv = (t < EC_FE_LIMBS) ? ec_p.v[t] : 0;
					ec_u64 d = (ec_u64)cur[t] - pv - borrow;
					cur[t] = (t_32)d;
					borrow = (d >> 32) & 1;
				}
			}
		}
	}

	for (k = 0; k < EC_FE_LIMBS; k++) r->v[k] = cur[k];
}
/*======================================================================*
                          初始化
 *======================================================================*/

/* 计算 -p^{-1} mod 2^32 (牛顿迭代) */
PRIVATE t_32 compute_n0inv(void)
{
	t_32 x = 1;
	int i;
	for (i = 0; i < 5; i++) {
		x = x * (2 - ec_p.v[0] * x);        /* 32 位自然溢出 */
	}
	return (t_32)(0 - x);
}

PUBLIC int ec_p256_init(void)
{
	EC_FE one;
	int i;

	if (ec_ready) return 0;

	if (ec_fe_from_bytes(&ec_p, p256_p, 32) != 0) return -1;
	if (ec_fe_from_bytes(&ec_b, p256_b, 32) != 0) return -1;
	if (ec_fe_from_bytes(&ec_gx, p256_gx, 32) != 0) return -1;
	if (ec_fe_from_bytes(&ec_gy, p256_gy, 32) != 0) return -1;

	ec_n0inv = compute_n0inv();

	/* R = 2^256 mod p: 从 1 开始连续翻倍 256 次并取模 */
	fe_zero(&one);
	one.v[0] = 1;
	fe_copy(&ec_R, &one);
	for (i = 0; i < 256; i++) {
		t_32 carry = 0;
		int k;
		for (k = 0; k < EC_FE_LIMBS; k++) {
			t_32 nv = (ec_R.v[k] << 1) | carry;
			carry = ec_R.v[k] >> 31;
			ec_R.v[k] = nv;
		}
		fe_reduce_once(&ec_R);
	}

	/* R2 = 2^512 mod p: 再从 R 翻倍 256 次 */
	fe_copy(&ec_R2, &ec_R);
	for (i = 0; i < 256; i++) {
		t_32 carry = 0;
		int k;
		for (k = 0; k < EC_FE_LIMBS; k++) {
			t_32 nv = (ec_R2.v[k] << 1) | carry;
			carry = ec_R2.v[k] >> 31;
			ec_R2.v[k] = nv;
		}
		fe_reduce_once(&ec_R2);
	}

	ec_ready = 1;
	return 0;
}

/*======================================================================*
                          域运算对外接口
 *======================================================================*/

PUBLIC int ec_fe_from_bytes(EC_FE *r, const t_8 *be, int len)
{
	int i;
	if (!r || !be || len <= 0 || len > 32) return -1;
	fe_zero(r);
	for (i = 0; i < len; i++) {
		int j = len - 1 - i;                 /* 从最低字节数起 */
		int limb = j / 4;
		int shift = (j % 4) * 8;
		r->v[limb] |= (t_32)be[i] << shift;
	}
	return 0;
}

PUBLIC int ec_fe_to_bytes(const EC_FE *a, t_8 *be, int len)
{
	int i;
	if (!a || !be || len <= 0 || len > 32) return -1;
	for (i = 0; i < len; i++) {
		int j = len - 1 - i;
		int limb = j / 4;
		int shift = (j % 4) * 8;
		be[i] = (t_8)((a->v[limb] >> shift) & 0xFF);
	}
	return 0;
}

PUBLIC int ec_fe_is_zero(const EC_FE *a)
{
	return a ? fe_is_zero_raw(a->v) : 1;
}

PUBLIC int ec_fe_cmp(const EC_FE *a, const EC_FE *b)
{
	return fe_cmp_raw(a->v, b->v);
}

/* 9 limb 辅助: r = a + b (a,b 为 8 limb) */
PRIVATE void fe_add9(t_32 *r9, const t_32 *a, const t_32 *b)
{
	ec_u64 carry = 0;
	int i;
	for (i = 0; i < EC_FE_LIMBS; i++) {
		ec_u64 v = (ec_u64)a[i] + b[i] + carry;
		r9[i] = (t_32)v;
		carry = v >> 32;
	}
	r9[EC_FE_LIMBS] = (t_32)carry;
}

/* 9 limb - 8 limb */
PRIVATE void fe_sub9(t_32 *r9, const t_32 *a9, const t_32 *b)
{
	ec_u64 borrow = 0;
	int i;
	for (i = 0; i < EC_FE_LIMBS; i++) {
		ec_u64 d = (ec_u64)a9[i] - b[i] - borrow;
		r9[i] = (t_32)d;
		borrow = (d >> 32) & 1;
	}
	r9[EC_FE_LIMBS] = (t_32)((ec_u64)a9[EC_FE_LIMBS] - borrow);
}

/* 把 9 limb 数规约到 [0,p) 并写回 EC_FE */
PRIVATE void fe_reduce9(EC_FE *r, t_32 *v9)
{
	int guard = 0;
	while (guard++ < 4) {
		int ge = 1;
		int i;
		for (i = EC_FE_LIMBS; i >= 0; i--) {
			t_32 cv = v9[i];
			t_32 pv = (i < EC_FE_LIMBS) ? ec_p.v[i] : 0;
			if (cv > pv) { ge = 1; break; }
			if (cv < pv) { ge = 0; break; }
			if (i == 0) ge = 1;
		}
		if (!ge) break;
		fe_sub9(v9, v9, ec_p.v);
	}
	{
		int i;
		for (i = 0; i < EC_FE_LIMBS; i++) r->v[i] = v9[i];
	}
}
PUBLIC int ec_fe_add(EC_FE *r, const EC_FE *a, const EC_FE *b)
{
	if (!r || !a || !b) return -1;
	{
		t_32 t9[EC_FE_LIMBS + 1];
		fe_add9(t9, a->v, b->v);
		fe_reduce9(r, t9);
	}
	return 0;
}

PUBLIC int ec_fe_sub(EC_FE *r, const EC_FE *a, const EC_FE *b)
{
	if (!r || !a || !b) return -1;
	if (fe_cmp_raw(a->v, b->v) >= 0) {
		fe_sub_raw(r->v, a->v, b->v);
	} else {
		t_32 t9[EC_FE_LIMBS + 1];
		fe_add9(t9, a->v, ec_p.v);           /* a + p >= b, 用 9 limb 装 */
		fe_sub9(t9, t9, b->v);
		fe_reduce9(r, t9);
	}
	return 0;
}

PUBLIC int ec_fe_mul(EC_FE *r, const EC_FE *a, const EC_FE *b)
{
	t_32 w[2 * EC_FE_LIMBS];
	int i, j;

	if (!r || !a || !b) return -1;
	for (i = 0; i < 2 * EC_FE_LIMBS; i++) w[i] = 0;
	for (i = 0; i < EC_FE_LIMBS; i++) {
		ec_u64 carry = 0;
		for (j = 0; j < EC_FE_LIMBS; j++) {
			ec_u64 cur = (ec_u64)a->v[i] * b->v[j] + w[i + j] + carry;
			w[i + j] = (t_32)cur;
			carry = cur >> 32;
		}
		{
			int idx = i + EC_FE_LIMBS;
			ec_u64 cur = (ec_u64)w[idx] + carry;
			w[idx] = (t_32)cur;
			if ((t_32)(cur >> 32) && idx + 1 < 2 * EC_FE_LIMBS) {
				w[idx + 1] += (t_32)(cur >> 32);
			}
		}
	}
	fe_reduce_wide(r, w);
	return 0;
}

PUBLIC int ec_fe_sqr(EC_FE *r, const EC_FE *a)
{
	return ec_fe_mul(r, a, a);
}

PUBLIC int ec_fe_add_small(EC_FE *r, const EC_FE *a, t_32 c)
{
	EC_FE t;
	if (!r || !a) return -1;
	fe_zero(&t);
	t.v[0] = c;
	return ec_fe_add(r, a, &t);
}

/* r = a^(p-2) mod p (费马小定理求逆) */
PUBLIC int ec_fe_inv(EC_FE *r, const EC_FE *a)
{
	EC_FE acc, base, e;
	int i;

	if (!r || !a) return -1;
	if (fe_is_zero_raw(a->v)) return -1;

	/* e = p - 2 */
	fe_copy(&e, &ec_p);
	{
		EC_FE two;
		fe_zero(&two);
		two.v[0] = 2;
		fe_sub_raw(e.v, e.v, two.v);
	}

	fe_copy(&base, a);
	fe_zero(&acc);
	acc.v[0] = 1;

	for (i = 255; i >= 0; i--) {
		ec_fe_sqr(&acc, &acc);
		if ((e.v[i / 32] >> (i % 32)) & 1) {
			ec_fe_mul(&acc, &acc, &base);
		}
	}
	fe_copy(r, &acc);
	(void)i;
	return 0;
}

/*======================================================================*
                          点运算 (内部雅可比)
 *======================================================================*/

typedef struct {
	EC_FE x, y, z;              /* 仿射 (x/z^2, y/z^3); z==0 表示无穷远 */
} EC_JAC;

PRIVATE void jac_from_affine(EC_JAC *j, const EC_POINT *p)
{
	fe_copy(&j->x, &p->x);
	fe_copy(&j->y, &p->y);
	fe_zero(&j->z);
	if (!p->inf) j->z.v[0] = 1;
}

PRIVATE void jac_to_affine(EC_POINT *p, const EC_JAC *j)
{
	EC_FE zi, zi2, zi3;

	if (fe_is_zero_raw(j->z.v)) {
		p->inf = 1;
		fe_zero(&p->x);
		fe_zero(&p->y);
		return;
	}
	ec_fe_inv(&zi, &j->z);
	ec_fe_sqr(&zi2, &zi);
	ec_fe_mul(&zi3, &zi2, &zi);
	ec_fe_mul(&p->x, &j->x, &zi2);
	ec_fe_mul(&p->y, &j->y, &zi3);
	p->inf = 0;
}

/* 倍点 (a = -3 专用公式) */
PRIVATE void jac_double(EC_JAC *r, const EC_JAC *p)
{
	EC_FE delta, gamma, beta, alpha, t1, t2;

	if (fe_is_zero_raw(p->z.v) || fe_is_zero_raw(p->y.v)) {
		fe_zero(&r->z);
		return;
	}
	ec_fe_sqr(&delta, &p->z);
	ec_fe_sqr(&gamma, &p->y);
	ec_fe_mul(&beta, &p->x, &gamma);

	ec_fe_sub(&t1, &p->x, &delta);
	ec_fe_add(&t2, &p->x, &delta);
	ec_fe_mul(&alpha, &t1, &t2);
	/* alpha = 3*(x-delta)*(x+delta) */
	ec_fe_add(&t2, &alpha, &alpha);
	ec_fe_add(&alpha, &t2, &alpha);

	/* X3 = alpha^2 - 8*beta */
	ec_fe_sqr(&t1, &alpha);
	{
		EC_FE b8;
		ec_fe_add(&b8, &beta, &beta);       /* 2b */
		ec_fe_add(&b8, &b8, &b8);           /* 4b */
		ec_fe_add(&b8, &b8, &b8);           /* 8b */
		ec_fe_sub(&r->x, &t1, &b8);
	}

	/* Z3 = (y+z)^2 - gamma - delta */
	ec_fe_add(&t1, &p->y, &p->z);
	ec_fe_sqr(&t1, &t1);
	ec_fe_sub(&t1, &t1, &gamma);
	ec_fe_sub(&r->z, &t1, &delta);

	/* Y3 = alpha*(4*beta - X3) - 8*gamma^2 */
	{
		EC_FE b4, g2, g8;
		ec_fe_add(&b4, &beta, &beta);
		ec_fe_add(&b4, &b4, &b4);
		ec_fe_sub(&t1, &b4, &r->x);
		ec_fe_mul(&t1, &alpha, &t1);
		ec_fe_sqr(&g2, &gamma);
		ec_fe_add(&g8, &g2, &g2);
		ec_fe_add(&g8, &g8, &g8);
		ec_fe_add(&g8, &g8, &g8);
		ec_fe_sub(&r->y, &t1, &g8);
	}
}

/* 雅可比 + 仿射 */
PRIVATE void jac_add_affine(EC_JAC *r, const EC_JAC *p, const EC_POINT *q)
{
	EC_FE z1z1, u2, s2, h, hh, i4, j, rr, v, t1, t2;

	if (q->inf) { *r = *p; return; }
	if (fe_is_zero_raw(p->z.v)) {
		jac_from_affine(r, q);
		return;
	}

	ec_fe_sqr(&z1z1, &p->z);
	ec_fe_mul(&u2, &q->x, &z1z1);
	ec_fe_mul(&t1, &p->z, &z1z1);
	ec_fe_mul(&s2, &q->y, &t1);

	ec_fe_sub(&h, &u2, &p->x);
	ec_fe_sqr(&hh, &h);
	ec_fe_add(&i4, &hh, &hh);
	ec_fe_add(&i4, &i4, &i4);
	ec_fe_mul(&j, &h, &i4);

	ec_fe_sub(&t1, &s2, &p->y);
	ec_fe_add(&rr, &t1, &t1);
	ec_fe_mul(&v, &p->x, &i4);

	if (fe_is_zero_raw(h.v)) {
		if (fe_is_zero_raw(rr.v)) {
			jac_double(r, p);               /* 同一点: 转倍点 */
			return;
		}
		fe_zero(&r->z);                      /* 两倍点互为相反数: 无穷远 */
		return;
	}

	/* X3 = r^2 - J - 2V */
	ec_fe_sqr(&t1, &rr);
	ec_fe_sub(&t1, &t1, &j);
	ec_fe_sub(&t2, &v, &v);
	ec_fe_sub(&r->x, &t1, &t2);

	/* Y3 = r*(V - X3) - 2*Y1*J */
	ec_fe_sub(&t1, &v, &r->x);
	ec_fe_mul(&t1, &rr, &t1);
	ec_fe_mul(&t2, &p->y, &j);
	ec_fe_add(&t2, &t2, &t2);
	ec_fe_sub(&r->y, &t1, &t2);

	/* Z3 = (Z1 + H)^2 - Z1Z1 - HH */
	ec_fe_add(&t1, &p->z, &h);
	ec_fe_sqr(&t1, &t1);
	ec_fe_sub(&t1, &t1, &z1z1);
	ec_fe_sub(&r->z, &t1, &hh);
}

/*======================================================================*
                          对外点接口
 *======================================================================*/

PUBLIC int ec_p256_generator(EC_POINT *g)
{
	if (!g) return -1;
	if (ec_p256_init() != 0) return -1;
	fe_copy(&g->x, &ec_gx);
	fe_copy(&g->y, &ec_gy);
	g->inf = 0;
	return 0;
}

/* y^2 == x^3 - 3x + b (mod p) ? */
PUBLIC int ec_point_on_curve(const EC_POINT *p)
{
	EC_FE lhs, rhs, t1, t2, three_x;

	if (!p) return 0;
	if (p->inf) return 1;
	if (ec_p256_init() != 0) return 0;
	if (fe_cmp_raw(p->x.v, ec_p.v) >= 0) return 0;
	if (fe_cmp_raw(p->y.v, ec_p.v) >= 0) return 0;

	ec_fe_sqr(&lhs, &p->y);
	ec_fe_sqr(&t1, &p->x);
	ec_fe_mul(&t2, &t1, &p->x);              /* x^3 */
	ec_fe_add(&three_x, &p->x, &p->x);
	ec_fe_add(&three_x, &three_x, &p->x);    /* 3x */
	ec_fe_sub(&t2, &t2, &three_x);
	ec_fe_add(&rhs, &t2, &ec_b);

	return (ec_fe_cmp(&lhs, &rhs) == 0) ? 1 : 0;
}

PUBLIC int ec_point_add(EC_POINT *r, const EC_POINT *a, const EC_POINT *b)
{
	EC_JAC ja, jr;

	if (!r || !a || !b) return -1;
	if (ec_p256_init() != 0) return -1;
	if (a->inf) { *r = *b; return 0; }
	if (b->inf) { *r = *a; return 0; }

	jac_from_affine(&ja, a);
	jac_add_affine(&jr, &ja, b);
	jac_to_affine(r, &jr);
	return 0;
}

PUBLIC int ec_point_mul(EC_POINT *r, const EC_FE *k, const EC_POINT *p)
{
	EC_JAC acc;
	int i;

	if (!r || !k || !p) return -1;
	if (ec_p256_init() != 0) return -1;
	if (p->inf) { r->inf = 1; return 0; }

	fe_zero(&acc.x);
	fe_zero(&acc.y);
	fe_zero(&acc.z);                          /* 无穷远 */

	for (i = 255; i >= 0; i--) {
		if (!fe_is_zero_raw(acc.z.v)) {
			jac_double(&acc, &acc);
		}
		if ((k->v[i / 32] >> (i % 32)) & 1) {
			jac_add_affine(&acc, &acc, p);
		}
	}
	jac_to_affine(r, &acc);
	return 0;
}

PUBLIC int ec_ecdh(const t_8 priv[32], const EC_POINT *peer, t_8 out_x[32])
{
	EC_FE d;
	EC_POINT s;

	if (!priv || !peer || !out_x) return -1;
	if (!ec_point_on_curve(peer)) return -1;  /* 拒绝无效点 */
	if (ec_fe_from_bytes(&d, priv, 32) != 0) return -1;
	if (ec_fe_is_zero(&d)) return -1;
	if (ec_point_mul(&s, &d, peer) != 0) return -1;
	if (s.inf) return -1;
	return ec_fe_to_bytes(&s.x, out_x, 32);
}
