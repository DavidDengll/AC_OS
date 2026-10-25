/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              crypto.c
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
       CatOS 内核密码学原语: SHA-256 / HMAC-SHA256 / TLS 1.2 PRF

  说明:
    - 纯 C, 无第三方代码, 无动态分配, 无 libc 依赖
    - 不使用 64 位整数除法 (避免链接 libgcc 的 __udivdi3)
    - 正确性由 tools/crypto_test/ 用 Python hashlib 生成的向量验证
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include "type.h"
#include "const.h"
#include "crypto.h"

/*======================================================================*
                          内部小工具
 *======================================================================*/

PRIVATE void c_memcpy(t_8 *d, const t_8 *s, int n)
{
	int i;
	for (i = 0; i < n; i++) d[i] = s[i];
}

PRIVATE void c_memzero(t_8 *d, int n)
{
	int i;
	for (i = 0; i < n; i++) d[i] = 0;
}

PUBLIC void crypto_wipe(void *p, int len)
{
	t_8 *q = (t_8 *)p;
	int i;
	if (!p || len <= 0) return;
	for (i = 0; i < len; i++) q[i] = 0;
}

/* 常量时间比较: 返回 0=相同 */
PUBLIC int crypto_memcmp_ct(const t_8 *a, const t_8 *b, int len)
{
	int i;
	t_8 diff = 0;
	if (!a || !b || len <= 0) return 1;
	for (i = 0; i < len; i++) diff |= (t_8)(a[i] ^ b[i]);
	return diff ? 1 : 0;
}

/*======================================================================*
                          SHA-256 (FIPS 180-4)
 *======================================================================*/

#define ROTR(x, n)  (((x) >> (n)) | ((x) << (32 - (n))))
#define CH(x, y, z)  (((x) & (y)) ^ (~(x) & (z)))
#define MAJ(x, y, z) (((x) & (y)) ^ ((x) & (z)) ^ ((y) & (z)))
#define EP0(x)      (ROTR(x, 2) ^ ROTR(x, 13) ^ ROTR(x, 22))
#define EP1(x)      (ROTR(x, 6) ^ ROTR(x, 11) ^ ROTR(x, 25))
#define SIG0(x)     (ROTR(x, 7) ^ ROTR(x, 18) ^ ((x) >> 3))
#define SIG1(x)     (ROTR(x, 17) ^ ROTR(x, 19) ^ ((x) >> 10))

PRIVATE const t_32 sha256_k[64] = {
	0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
	0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
	0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
	0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
	0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
	0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
	0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
	0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
	0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
	0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
	0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
	0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
	0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
	0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
	0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
	0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
};

PRIVATE void sha256_transform(SHA256_CTX *ctx, const t_8 *blk)
{
	t_32 w[64];
	t_32 a, b, c, d, e, f, g, h;
	t_32 t1, t2;
	int i;

	for (i = 0; i < 16; i++) {
		w[i] = ((t_32)blk[i * 4] << 24) | ((t_32)blk[i * 4 + 1] << 16) |
		       ((t_32)blk[i * 4 + 2] << 8) | (t_32)blk[i * 4 + 3];
	}
	for (i = 16; i < 64; i++) {
		w[i] = SIG1(w[i - 2]) + w[i - 7] + SIG0(w[i - 15]) + w[i - 16];
	}

	a = ctx->h[0]; b = ctx->h[1]; c = ctx->h[2]; d = ctx->h[3];
	e = ctx->h[4]; f = ctx->h[5]; g = ctx->h[6]; h = ctx->h[7];

	for (i = 0; i < 64; i++) {
		t1 = h + EP1(e) + CH(e, f, g) + sha256_k[i] + w[i];
		t2 = EP0(a) + MAJ(a, b, c);
		h = g;
		g = f;
		f = e;
		e = d + t1;
		d = c;
		c = b;
		b = a;
		a = t1 + t2;
	}

	ctx->h[0] += a; ctx->h[1] += b; ctx->h[2] += c; ctx->h[3] += d;
	ctx->h[4] += e; ctx->h[5] += f; ctx->h[6] += g; ctx->h[7] += h;
}

PUBLIC void sha256_init(SHA256_CTX *ctx)
{
	if (!ctx) return;
	ctx->h[0] = 0x6a09e667;
	ctx->h[1] = 0xbb67ae85;
	ctx->h[2] = 0x3c6ef372;
	ctx->h[3] = 0xa54ff53a;
	ctx->h[4] = 0x510e527f;
	ctx->h[5] = 0x9b05688c;
	ctx->h[6] = 0x1f83d9ab;
	ctx->h[7] = 0x5be0cd19;
	ctx->buf_len = 0;
	ctx->total_hi = 0;
	ctx->total_lo = 0;
}

PUBLIC void sha256_update(SHA256_CTX *ctx, const void *data, int len)
{
	const t_8 *p = (const t_8 *)data;
	t_32 old;

	if (!ctx || (!p && len > 0) || len <= 0) return;

	/* 累计总长度 (字节数, hi/lo 两段 32 位) */
	old = ctx->total_lo;
	ctx->total_lo += (t_32)len;
	if (ctx->total_lo < old) ctx->total_hi++;

	while (len > 0) {
		int space = SHA256_BLOCK - (int)ctx->buf_len;
		int take = (len < space) ? len : space;

		c_memcpy(&ctx->buf[ctx->buf_len], p, take);
		ctx->buf_len += (t_32)take;
		p += take;
		len -= take;

		if (ctx->buf_len == SHA256_BLOCK) {
			sha256_transform(ctx, ctx->buf);
			ctx->buf_len = 0;
		}
	}
}

PUBLIC void sha256_final(SHA256_CTX *ctx, t_8 out[SHA256_DIGEST])
{
	t_8 pad[SHA256_BLOCK + 8];
	int pad_len;
	int i;
	t_32 bits_hi, bits_lo;

	if (!ctx || !out) return;

	/* 消息比特长度 = 字节数 * 8 (用 hi/lo 拼成 64 位) */
	bits_hi = (ctx->total_hi << 3) | (ctx->total_lo >> 29);
	bits_lo = ctx->total_lo << 3;

	/* 填充: 0x80 + 0 ... 直到长度 ≡ 56 (mod 64), 再接 8 字节长度 */
	pad_len = (int)(56 - (int)((ctx->buf_len + 1) % SHA256_BLOCK));
	if (pad_len < 0) pad_len += SHA256_BLOCK;
	pad_len += 1;                                  /* 加上 0x80 本身 */
	c_memzero(pad, (int)sizeof(pad));
	pad[0] = 0x80;

	sha256_update(ctx, pad, pad_len);

	pad[0] = (t_8)(bits_hi >> 24);
	pad[1] = (t_8)(bits_hi >> 16);
	pad[2] = (t_8)(bits_hi >> 8);
	pad[3] = (t_8)bits_hi;
	pad[4] = (t_8)(bits_lo >> 24);
	pad[5] = (t_8)(bits_lo >> 16);
	pad[6] = (t_8)(bits_lo >> 8);
	pad[7] = (t_8)bits_lo;
	sha256_update(ctx, pad, 8);

	for (i = 0; i < 8; i++) {
		out[i * 4]     = (t_8)(ctx->h[i] >> 24);
		out[i * 4 + 1] = (t_8)(ctx->h[i] >> 16);
		out[i * 4 + 2] = (t_8)(ctx->h[i] >> 8);
		out[i * 4 + 3] = (t_8)ctx->h[i];
	}
	crypto_wipe(ctx, sizeof(SHA256_CTX));
}

PUBLIC void sha256(const void *data, int len, t_8 out[SHA256_DIGEST])
{
	SHA256_CTX ctx;

	sha256_init(&ctx);
	sha256_update(&ctx, data, len);
	sha256_final(&ctx, out);
}

/*======================================================================*
                          HMAC-SHA256 (RFC 2104)
 *======================================================================*/

PUBLIC void hmac_sha256(const t_8 *key, int key_len,
                        const t_8 *data, int data_len,
                        t_8 out[HMAC_SHA256_LEN])
{
	t_8 k[SHA256_BLOCK];
	t_8 ipad[SHA256_BLOCK];
	t_8 opad[SHA256_BLOCK];
	t_8 inner[SHA256_DIGEST];
	SHA256_CTX ctx;
	int i;

	if (!out) return;
	c_memzero(k, SHA256_BLOCK);

	if (key && key_len > 0) {
		if (key_len > SHA256_BLOCK) {
			/* 长密钥先摘要 */
			sha256(key, key_len, k);
		} else {
			c_memcpy(k, key, key_len);
		}
	}

	for (i = 0; i < SHA256_BLOCK; i++) {
		ipad[i] = (t_8)(k[i] ^ 0x36);
		opad[i] = (t_8)(k[i] ^ 0x5C);
	}

	sha256_init(&ctx);
	sha256_update(&ctx, ipad, SHA256_BLOCK);
	sha256_update(&ctx, data, data_len);
	sha256_final(&ctx, inner);

	sha256_init(&ctx);
	sha256_update(&ctx, opad, SHA256_BLOCK);
	sha256_update(&ctx, inner, SHA256_DIGEST);
	sha256_final(&ctx, out);

	crypto_wipe(k, SHA256_BLOCK);
	crypto_wipe(ipad, SHA256_BLOCK);
	crypto_wipe(opad, SHA256_BLOCK);
	crypto_wipe(inner, SHA256_DIGEST);
}

/*======================================================================*
                    TLS 1.2 PRF (P_SHA256, RFC 5246)
 *======================================================================*/

#define PRF_LABEL_MAX  32
#define PRF_SEED_MAX   96

PUBLIC int tls_prf_sha256(const t_8 *secret, int secret_len,
                          const char *label,
                          const t_8 *seed, int seed_len,
                          t_8 *out, int out_len)
{
	t_8 ls[PRF_LABEL_MAX + PRF_SEED_MAX];   /* label || seed */
	t_8 ap[SHA256_DIGEST + PRF_LABEL_MAX + PRF_SEED_MAX];
	t_8 A[SHA256_DIGEST];
	t_8 blk[SHA256_DIGEST];
	t_8 tmp[SHA256_DIGEST];
	int llen = 0;
	int ls_len;
	int produced = 0;
	int i;

	if (!out || out_len < 0 || out_len > 256) return -1;
	if (seed_len < 0 || seed_len > PRF_SEED_MAX) return -1;
	if (secret_len < 0) return -1;

	while (label && label[llen] && llen < PRF_LABEL_MAX) llen++;

	for (i = 0; i < llen; i++) ls[i] = (t_8)label[i];
	if (seed_len > 0 && seed) {
		for (i = 0; i < seed_len; i++) ls[llen + i] = seed[i];
	}
	ls_len = llen + seed_len;

	/* A(1) = HMAC(secret, label || seed) */
	hmac_sha256(secret, secret_len, ls, ls_len, A);

	while (produced < out_len) {
		int n;

		/* block = HMAC(secret, A(i) || label || seed) */
		for (i = 0; i < SHA256_DIGEST; i++) ap[i] = A[i];
		for (i = 0; i < ls_len; i++) ap[SHA256_DIGEST + i] = ls[i];
		hmac_sha256(secret, secret_len, ap, SHA256_DIGEST + ls_len, blk);

		n = out_len - produced;
		if (n > SHA256_DIGEST) n = SHA256_DIGEST;
		for (i = 0; i < n; i++) out[produced + i] = blk[i];
		produced += n;

		/* A(i+1) = HMAC(secret, A(i)) */
		hmac_sha256(secret, secret_len, A, SHA256_DIGEST, tmp);
		for (i = 0; i < SHA256_DIGEST; i++) A[i] = tmp[i];
	}

	crypto_wipe(ls, (int)sizeof(ls));
	crypto_wipe(ap, (int)sizeof(ap));
	crypto_wipe(A, SHA256_DIGEST);
	crypto_wipe(blk, SHA256_DIGEST);
	crypto_wipe(tmp, SHA256_DIGEST);
	return 0;
}

/*======================================================================*
                          SHA-1 (FIPS 180-4)
 *======================================================================*/

#define ROTL32(x, n) (((x) << (n)) | ((x) >> (32 - (n))))

PRIVATE void sha1_transform(SHA1_CTX *ctx, const t_8 *blk)
{
	t_32 w[80];
	t_32 a, b, c, d, e, f, k, tmp;
	int i;

	for (i = 0; i < 16; i++) {
		w[i] = ((t_32)blk[i * 4] << 24) | ((t_32)blk[i * 4 + 1] << 16) |
		       ((t_32)blk[i * 4 + 2] << 8) | (t_32)blk[i * 4 + 3];
	}
	for (i = 16; i < 80; i++) {
		w[i] = ROTL32(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
	}

	a = ctx->h[0]; b = ctx->h[1]; c = ctx->h[2]; d = ctx->h[3]; e = ctx->h[4];

	for (i = 0; i < 80; i++) {
		if (i < 20) {
			f = (b & c) | ((~b) & d);
			k = 0x5A827999;
		} else if (i < 40) {
			f = b ^ c ^ d;
			k = 0x6ED9EBA1;
		} else if (i < 60) {
			f = (b & c) | (b & d) | (c & d);
			k = 0x8F1BBCDC;
		} else {
			f = b ^ c ^ d;
			k = 0xCA62C1D6;
		}
		tmp = ROTL32(a, 5) + f + e + k + w[i];
		e = d;
		d = c;
		c = ROTL32(b, 30);
		b = a;
		a = tmp;
	}

	ctx->h[0] += a; ctx->h[1] += b; ctx->h[2] += c;
	ctx->h[3] += d; ctx->h[4] += e;
}

PUBLIC void sha1_init(SHA1_CTX *ctx)
{
	if (!ctx) return;
	ctx->h[0] = 0x67452301;
	ctx->h[1] = 0xEFCDAB89;
	ctx->h[2] = 0x98BADCFE;
	ctx->h[3] = 0x10325476;
	ctx->h[4] = 0xC3D2E1F0;
	ctx->buf_len = 0;
	ctx->total_hi = 0;
	ctx->total_lo = 0;
}

PUBLIC void sha1_update(SHA1_CTX *ctx, const void *data, int len)
{
	const t_8 *p = (const t_8 *)data;
	t_32 old;

	if (!ctx || (!p && len > 0) || len <= 0) return;

	old = ctx->total_lo;
	ctx->total_lo += (t_32)len;
	if (ctx->total_lo < old) ctx->total_hi++;

	while (len > 0) {
		int space = SHA256_BLOCK - (int)ctx->buf_len;
		int take = (len < space) ? len : space;

		c_memcpy(&ctx->buf[ctx->buf_len], p, take);
		ctx->buf_len += (t_32)take;
		p += take;
		len -= take;

		if (ctx->buf_len == SHA256_BLOCK) {
			sha1_transform(ctx, ctx->buf);
			ctx->buf_len = 0;
		}
	}
}

PUBLIC void sha1_final(SHA1_CTX *ctx, t_8 out[SHA1_DIGEST])
{
	t_8 pad[SHA256_BLOCK + 8];
	int pad_len;
	int i;
	t_32 bits_hi, bits_lo;

	if (!ctx || !out) return;

	bits_hi = (ctx->total_hi << 3) | (ctx->total_lo >> 29);
	bits_lo = ctx->total_lo << 3;

	pad_len = (int)(56 - (int)((ctx->buf_len + 1) % SHA256_BLOCK));
	if (pad_len < 0) pad_len += SHA256_BLOCK;
	pad_len += 1;
	c_memzero(pad, (int)sizeof(pad));
	pad[0] = 0x80;
	sha1_update(ctx, pad, pad_len);

	pad[0] = (t_8)(bits_hi >> 24);
	pad[1] = (t_8)(bits_hi >> 16);
	pad[2] = (t_8)(bits_hi >> 8);
	pad[3] = (t_8)bits_hi;
	pad[4] = (t_8)(bits_lo >> 24);
	pad[5] = (t_8)(bits_lo >> 16);
	pad[6] = (t_8)(bits_lo >> 8);
	pad[7] = (t_8)bits_lo;
	sha1_update(ctx, pad, 8);

	for (i = 0; i < 5; i++) {
		out[i * 4]     = (t_8)(ctx->h[i] >> 24);
		out[i * 4 + 1] = (t_8)(ctx->h[i] >> 16);
		out[i * 4 + 2] = (t_8)(ctx->h[i] >> 8);
		out[i * 4 + 3] = (t_8)ctx->h[i];
	}
	crypto_wipe(ctx, sizeof(SHA1_CTX));
}

PUBLIC void sha1(const void *data, int len, t_8 out[SHA1_DIGEST])
{
	SHA1_CTX ctx;
	sha1_init(&ctx);
	sha1_update(&ctx, data, len);
	sha1_final(&ctx, out);
}

PUBLIC void hmac_sha1(const t_8 *key, int key_len,
                      const t_8 *data, int data_len,
                      t_8 out[SHA1_DIGEST])
{
	t_8 k[SHA256_BLOCK];
	t_8 ipad[SHA256_BLOCK];
	t_8 opad[SHA256_BLOCK];
	t_8 inner[SHA1_DIGEST];
	SHA1_CTX ctx;
	int i;

	if (!out) return;
	c_memzero(k, SHA256_BLOCK);
	if (key && key_len > 0) {
		if (key_len > SHA256_BLOCK) sha1(key, key_len, k);
		else c_memcpy(k, key, key_len);
	}
	for (i = 0; i < SHA256_BLOCK; i++) {
		ipad[i] = (t_8)(k[i] ^ 0x36);
		opad[i] = (t_8)(k[i] ^ 0x5C);
	}
	sha1_init(&ctx);
	sha1_update(&ctx, ipad, SHA256_BLOCK);
	sha1_update(&ctx, data, data_len);
	sha1_final(&ctx, inner);

	sha1_init(&ctx);
	sha1_update(&ctx, opad, SHA256_BLOCK);
	sha1_update(&ctx, inner, SHA1_DIGEST);
	sha1_final(&ctx, out);

	crypto_wipe(k, SHA256_BLOCK);
	crypto_wipe(ipad, SHA256_BLOCK);
	crypto_wipe(opad, SHA256_BLOCK);
	crypto_wipe(inner, SHA1_DIGEST);
}

/*======================================================================*
                          AES-128 (FIPS 197)
 *======================================================================*/

/* GF(2^8) 乘法 (AES 多项式 x^8+x^4+x^3+x+1) */
PRIVATE t_8 aes_gmul(t_8 a, t_8 b)
{
	t_8 p = 0;
	int i;

	for (i = 0; i < 8; i++) {
		if (b & 1) p ^= a;
		{
			t_8 hi = (t_8)(a & 0x80);
			a = (t_8)(a << 1);
			if (hi) a ^= 0x1B;
		}
		b = (t_8)(b >> 1);
	}
	return p;
}

/* GF(2^8) 求逆 (a^254) */
PRIVATE t_8 aes_ginv(t_8 a)
{
	t_8 r = 1;
	t_8 b = a;
	int e = 254;

	while (e) {
		if (e & 1) r = aes_gmul(r, b);
		b = aes_gmul(b, b);
		e >>= 1;
	}
	return r;
}

/* S 盒: 现场生成 (避免手抄 256 个常数) */
PRIVATE t_8 aes_sbox[256];
PRIVATE t_8 aes_isbox[256];
PRIVATE int aes_tables_ready;

PRIVATE t_8 aes_rotl8(t_8 x, int n)
{
	return (t_8)((x << n) | (x >> (8 - n)));
}

PRIVATE void aes_build_tables(void)
{
	int i;

	if (aes_tables_ready) return;
	for (i = 0; i < 256; i++) {
		t_8 x = aes_ginv((t_8)i);
		t_8 s = (t_8)(x ^ aes_rotl8(x, 1) ^ aes_rotl8(x, 2) ^
		              aes_rotl8(x, 3) ^ aes_rotl8(x, 4) ^ 0x63);
		aes_sbox[i] = s;
		aes_isbox[s] = (t_8)i;
	}
	aes_tables_ready = 1;
}

PUBLIC void aes128_setkey(AES128_KEY *ks, const t_8 key[16])
{
	int i;
	t_8 rcon = 1;

	if (!ks || !key) return;
	aes_build_tables();
	c_memcpy(ks->rk, key, 16);

	for (i = 16; i < 176; i += 4) {
		t_8 t0 = ks->rk[i - 4];
		t_8 t1 = ks->rk[i - 3];
		t_8 t2 = ks->rk[i - 2];
		t_8 t3 = ks->rk[i - 1];

		if (i % 16 == 0) {
			t_8 tmp = t0;
			t0 = (t_8)(aes_sbox[t1] ^ rcon);
			t1 = aes_sbox[t2];
			t2 = aes_sbox[t3];
			t3 = aes_sbox[tmp];
			rcon = aes_gmul(rcon, 2);
		}
		ks->rk[i]     = (t_8)(ks->rk[i - 16] ^ t0);
		ks->rk[i + 1] = (t_8)(ks->rk[i - 15] ^ t1);
		ks->rk[i + 2] = (t_8)(ks->rk[i - 14] ^ t2);
		ks->rk[i + 3] = (t_8)(ks->rk[i - 13] ^ t3);
	}
}

PRIVATE void aes_add_round_key(t_8 *s, const t_8 *rk)
{
	int i;
	for (i = 0; i < 16; i++) s[i] ^= rk[i];
}

PRIVATE void aes_sub_bytes(t_8 *s, const t_8 *box)
{
	int i;
	for (i = 0; i < 16; i++) s[i] = box[s[i]];
}

/* 状态按列优先: s[r + 4c] */
PRIVATE void aes_shift_rows(t_8 *s, int inv)
{
	int r, c;
	t_8 t[4];

	for (r = 1; r < 4; r++) {
		for (c = 0; c < 4; c++) {
			int src = inv ? (c + 4 - r) % 4 : (c + r) % 4;
			t[c] = s[r + 4 * src];
		}
		for (c = 0; c < 4; c++) s[r + 4 * c] = t[c];
	}
}

PRIVATE void aes_mix_columns(t_8 *s, int inv)
{
	int c;

	for (c = 0; c < 4; c++) {
		t_8 *a = &s[4 * c];
		if (!inv) {
			t_8 t = (t_8)(a[0] ^ a[1] ^ a[2] ^ a[3]);
			t_8 a0 = a[0];
			a[0] = (t_8)(a[0] ^ t ^ aes_gmul(a[0] ^ a[1], 2));
			a[1] = (t_8)(a[1] ^ t ^ aes_gmul(a[1] ^ a[2], 2));
			a[2] = (t_8)(a[2] ^ t ^ aes_gmul(a[2] ^ a[3], 2));
			a[3] = (t_8)(a[3] ^ t ^ aes_gmul(a[3] ^ a0, 2));
		} else {
			t_8 a0 = a[0], a1 = a[1], a2 = a[2], a3 = a[3];
			a[0] = (t_8)(aes_gmul(a0, 14) ^ aes_gmul(a1, 11) ^
			             aes_gmul(a2, 13) ^ aes_gmul(a3, 9));
			a[1] = (t_8)(aes_gmul(a0, 9) ^ aes_gmul(a1, 14) ^
			             aes_gmul(a2, 11) ^ aes_gmul(a3, 13));
			a[2] = (t_8)(aes_gmul(a0, 13) ^ aes_gmul(a1, 9) ^
			             aes_gmul(a2, 14) ^ aes_gmul(a3, 11));
			a[3] = (t_8)(aes_gmul(a0, 11) ^ aes_gmul(a1, 13) ^
			             aes_gmul(a2, 9) ^ aes_gmul(a3, 14));
		}
	}
}

PUBLIC void aes128_encrypt_block(const AES128_KEY *ks,
                                 const t_8 in[16], t_8 out[16])
{
	t_8 s[16];
	int round;

	if (!ks || !in || !out) return;
	c_memcpy(s, in, 16);
	aes_add_round_key(s, &ks->rk[0]);
	for (round = 1; round < 10; round++) {
		aes_sub_bytes(s, aes_sbox);
		aes_shift_rows(s, 0);
		aes_mix_columns(s, 0);
		aes_add_round_key(s, &ks->rk[round * 16]);
	}
	aes_sub_bytes(s, aes_sbox);
	aes_shift_rows(s, 0);
	aes_add_round_key(s, &ks->rk[160]);
	c_memcpy(out, s, 16);
	crypto_wipe(s, 16);
}

PUBLIC void aes128_decrypt_block(const AES128_KEY *ks,
                                 const t_8 in[16], t_8 out[16])
{
	t_8 s[16];
	int round;

	if (!ks || !in || !out) return;
	c_memcpy(s, in, 16);
	aes_add_round_key(s, &ks->rk[160]);
	for (round = 9; round >= 1; round--) {
		aes_shift_rows(s, 1);
		aes_sub_bytes(s, aes_isbox);
		aes_add_round_key(s, &ks->rk[round * 16]);
		aes_mix_columns(s, 1);
	}
	aes_shift_rows(s, 1);
	aes_sub_bytes(s, aes_isbox);
	aes_add_round_key(s, &ks->rk[0]);
	c_memcpy(out, s, 16);
	crypto_wipe(s, 16);
}

PUBLIC void aes128_cbc_encrypt(const AES128_KEY *ks, t_8 iv[16],
                               const t_8 *in, t_8 *out, int len)
{
	t_8 chain[16];
	int off;

	if (!ks || !iv || !in || !out || len <= 0 || (len % 16) != 0) return;
	c_memcpy(chain, iv, 16);
	for (off = 0; off < len; off += 16) {
		t_8 blk[16];
		int i;
		for (i = 0; i < 16; i++) blk[i] = (t_8)(in[off + i] ^ chain[i]);
		aes128_encrypt_block(ks, blk, chain);
		c_memcpy(&out[off], chain, 16);
	}
	c_memcpy(iv, chain, 16);
	crypto_wipe(chain, 16);
}

PUBLIC void aes128_cbc_decrypt(const AES128_KEY *ks, t_8 iv[16],
                               const t_8 *in, t_8 *out, int len)
{
	t_8 chain[16];
	t_8 blk[16];
	int off;

	if (!ks || !iv || !in || !out || len <= 0 || (len % 16) != 0) return;
	c_memcpy(chain, iv, 16);
	for (off = 0; off < len; off += 16) {
		int i;
		c_memcpy(blk, &in[off], 16);
		aes128_decrypt_block(ks, blk, &out[off]);
		for (i = 0; i < 16; i++) out[off + i] = (t_8)(out[off + i] ^ chain[i]);
		c_memcpy(chain, blk, 16);
	}
	c_memcpy(iv, chain, 16);
	crypto_wipe(chain, 16);
}

PUBLIC void aes128_ctr_xcrypt(const AES128_KEY *ks, const t_8 nonce[16],
                              const t_8 *in, t_8 *out, int len)
{
	t_8 ctr[16];
	t_8 ksblk[16];
	int off = 0;

	if (!ks || !nonce || !in || !out || len < 0) return;
	c_memcpy(ctr, nonce, 16);

	while (off < len) {
		int i;
		int n = len - off;
		if (n > 16) n = 16;

		aes128_encrypt_block(ks, ctr, ksblk);
		for (i = 0; i < n; i++) out[off + i] = (t_8)(in[off + i] ^ ksblk[i]);

		/* 128 位计数器自增 (低 32 位足够, 但按 4 字节大端进位更稳) */
		for (i = 15; i >= 0; i--) {
			ctr[i] = (t_8)(ctr[i] + 1);
			if (ctr[i] != 0) break;
		}
		off += n;
	}
	crypto_wipe(ctr, 16);
	crypto_wipe(ksblk, 16);
}

/*----------------------------------------------------------------------
  GF(2^128) 乘法 (GCM 用), x = x * h, 位反射表示
----------------------------------------------------------------------*/
PRIVATE void aes_gf128_mul(t_8 *x, const t_8 *h)
{
	t_8 z[16];
	t_8 v[16];
	int i, j;

	c_memzero(z, 16);
	c_memcpy(v, h, 16);

	for (i = 0; i < 128; i++) {
		if (x[i >> 3] & (0x80 >> (i & 7))) {
			for (j = 0; j < 16; j++) z[j] ^= v[j];
		}
		{
			int lsb = v[15] & 1;
			for (j = 15; j > 0; j--) {
				v[j] = (t_8)((v[j] >> 1) | ((v[j - 1] & 1) << 7));
			}
			v[0] = (t_8)(v[0] >> 1);
			if (lsb) v[0] ^= 0xE1;
		}
	}
	c_memcpy(x, z, 16);
	crypto_wipe(z, 16);
	crypto_wipe(v, 16);
}

/* GHASH: 处理数据 (len 任意), 不处理 "长度块" (由调用者控制) */
PRIVATE void aes_ghash_update(t_8 *y, const t_8 *h, const t_8 *data, int len)
{
	int off = 0;

	while (off < len) {
		t_8 blk[16];
		int i;
		int n = len - off;

		c_memzero(blk, 16);
		if (n > 16) n = 16;
		for (i = 0; i < n; i++) blk[i] = data[off + i];
		for (i = 0; i < 16; i++) y[i] ^= blk[i];
		aes_gf128_mul(y, h);
		off += n;
	}
}

/* 64 位大端写入 */
PRIVATE void aes_put_be64(t_8 *p, t_32 hi, t_32 lo)
{
	p[0] = (t_8)(hi >> 24); p[1] = (t_8)(hi >> 16);
	p[2] = (t_8)(hi >> 8);  p[3] = (t_8)hi;
	p[4] = (t_8)(lo >> 24); p[5] = (t_8)(lo >> 16);
	p[6] = (t_8)(lo >> 8);  p[7] = (t_8)lo;
}

/* 32 位计数器自增 (GCM 的 J0 计数器) */
PRIVATE void aes_inc32(t_8 *ctr)
{
	int i;
	for (i = 15; i >= 12; i--) {
		ctr[i] = (t_8)(ctr[i] + 1);
		if (ctr[i] != 0) break;
	}
}

/* GHASH: AAD || 密文 || 长度块 */
PRIVATE void aes_ghash(t_8 *y, const t_8 *h,
                       const t_8 *aad, int aad_len,
                       const t_8 *ct, int ct_len)
{
	t_8 lenblk[16];
	int i;

	c_memzero(y, 16);
	if (aad_len > 0) aes_ghash_update(y, h, aad, aad_len);
	if (ct_len > 0) aes_ghash_update(y, h, ct, ct_len);

	/* 比特长度 = 字节数 * 8, 用 hi/lo 拼 64 位, 避免 64 位除法 */
	aes_put_be64(&lenblk[0], (t_32)(aad_len >> 29), (t_32)aad_len << 3);
	aes_put_be64(&lenblk[8], (t_32)(ct_len >> 29), (t_32)ct_len << 3);

	for (i = 0; i < 16; i++) y[i] ^= lenblk[i];
	aes_gf128_mul(y, h);
}

PUBLIC int aes128_gcm_encrypt(const AES128_KEY *ks, const t_8 nonce[12],
                              const t_8 *aad, int aad_len,
                              const t_8 *in, t_8 *out, int len,
                              t_8 tag[16])
{
	t_8 h[16];
	t_8 j0[16];
	t_8 ctr[16];
	t_8 ek[16];
	t_8 s[16];
	t_8 zero[16];
	int off;
	int i;

	if (!ks || !nonce || !tag) return -1;
	if (aad_len < 0 || len < 0) return -1;
	if (len > 0 && (!in || !out)) return -1;
	if (aad_len > 0 && !aad) return -1;

	c_memzero(zero, 16);
	aes128_encrypt_block(ks, zero, h);          /* H = E_K(0) */

	c_memcpy(j0, nonce, 12);
	j0[12] = 0; j0[13] = 0; j0[14] = 0; j0[15] = 1;
	c_memcpy(ctr, j0, 16);
	aes_inc32(ctr);

	off = 0;
	while (off < len) {
		int n = len - off;
		if (n > 16) n = 16;
		aes128_encrypt_block(ks, ctr, ek);
		for (i = 0; i < n; i++) out[off + i] = (t_8)(in[off + i] ^ ek[i]);
		aes_inc32(ctr);
		off += n;
	}

	aes_ghash(s, h, aad, aad_len, out, len);
	aes128_encrypt_block(ks, j0, ek);
	for (i = 0; i < 16; i++) tag[i] = (t_8)(s[i] ^ ek[i]);

	crypto_wipe(h, 16);
	crypto_wipe(j0, 16);
	crypto_wipe(ctr, 16);
	crypto_wipe(ek, 16);
	crypto_wipe(s, 16);
	return 0;
}

PUBLIC int aes128_gcm_decrypt(const AES128_KEY *ks, const t_8 nonce[12],
                              const t_8 *aad, int aad_len,
                              const t_8 *in, t_8 *out, int len,
                              const t_8 tag[16])
{
	t_8 h[16];
	t_8 j0[16];
	t_8 ctr[16];
	t_8 ek[16];
	t_8 s[16];
	t_8 calc[16];
	int off;
	int i;

	if (!ks || !nonce || !tag) return -1;
	if (aad_len < 0 || len < 0) return -1;
	if (len > 0 && (!in || !out)) return -1;
	if (aad_len > 0 && !aad) return -1;

	/* 先用密文算 tag 并校验, 通过后才解密 (避免对伪造数据做无谓解密) */
	aes128_encrypt_block(ks, (const t_8[16]){0}, h);
	c_memcpy(j0, nonce, 12);
	j0[12] = 0; j0[13] = 0; j0[14] = 0; j0[15] = 1;

	aes_ghash(s, h, aad, aad_len, in, len);
	aes128_encrypt_block(ks, j0, ek);
	for (i = 0; i < 16; i++) calc[i] = (t_8)(s[i] ^ ek[i]);

	if (crypto_memcmp_ct(calc, tag, 16) != 0) {
		crypto_wipe(h, 16);
		crypto_wipe(j0, 16);
		crypto_wipe(ek, 16);
		crypto_wipe(s, 16);
		crypto_wipe(calc, 16);
		return -1;                       /* 认证失败: 不输出明文 */
	}

	c_memcpy(ctr, j0, 16);
	aes_inc32(ctr);
	off = 0;
	while (off < len) {
		int n = len - off;
		if (n > 16) n = 16;
		aes128_encrypt_block(ks, ctr, ek);
		for (i = 0; i < n; i++) out[off + i] = (t_8)(in[off + i] ^ ek[i]);
		aes_inc32(ctr);
		off += n;
	}

	crypto_wipe(h, 16);
	crypto_wipe(j0, 16);
	crypto_wipe(ctr, 16);
	crypto_wipe(ek, 16);
	crypto_wipe(s, 16);
	crypto_wipe(calc, 16);
	return 0;
}