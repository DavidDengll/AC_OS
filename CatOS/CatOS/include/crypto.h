/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              crypto.h
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
            CatOS 内核密码学原语 (为 TLS / HTTPS 准备, 无第三方库)

  设计约束:
    - 无动态分配: 所有上下文是调用者提供的结构体, 工作缓冲在栈上
    - 无 64 位除法 (不依赖 libgcc 的 __udivdi3): 长度计数用 hi/lo 两个 32 位
    - 所有长度参数做边界检查, 不会越界读写
    - 每个算法都能在宿主机上用测试向量验证 (tools/crypto_test/)

  已实现:
    - SHA-256
    - HMAC-SHA256
    - TLS 1.2 PRF (P_SHA256, RFC 5246)

  后续 (按 TLS 依赖顺序):
    - SHA-1 (TLS 1.2 的 Finished/P_hash 备份算法、旧证书签名)
    - AES-128 分组加密 + CBC / GCM
    - 大整数 (bignum) + RSA-2048 (PKCS#1 v1.5 加密/验签)
    - X.509 证书解析 (后续版本)
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#ifndef _CATOS_CRYPTO_H_
#define _CATOS_CRYPTO_H_

#include "type.h"

/* ===== SHA-256 ===== */
#define SHA256_BLOCK   64
#define SHA256_DIGEST  32

typedef struct {
	t_32 h[8];           /* 中间状态 */
	t_8  buf[SHA256_BLOCK];  /* 未满一块的尾巴 */
	t_32 buf_len;        /* buf 中已有字节数 */
	t_32 total_hi;       /* 已处理字节数 (高 32 位) */
	t_32 total_lo;       /* 已处理字节数 (低 32 位) */
} SHA256_CTX;

PUBLIC void sha256_init(SHA256_CTX *ctx);
PUBLIC void sha256_update(SHA256_CTX *ctx, const void *data, int len);
/* 结束并输出 32 字节摘要. ctx 之后不可再用 (除非重新 init) */
PUBLIC void sha256_final(SHA256_CTX *ctx, t_8 out[SHA256_DIGEST]);
/* 一次性摘要 (内部使用静态上下文, 单次调用内完成) */
PUBLIC void sha256(const void *data, int len, t_8 out[SHA256_DIGEST]);

/* ===== HMAC-SHA256 ===== */
#define HMAC_SHA256_LEN  32

/* key 超过 64 字节时会先做一次 SHA-256; out 固定 32 字节 */
PUBLIC void hmac_sha256(const t_8 *key, int key_len,
                        const t_8 *data, int data_len,
                        t_8 out[HMAC_SHA256_LEN]);

/* ===== TLS 1.2 PRF (P_SHA256) =====
 * secret/seed 任意长度, label 必须以 0 结尾 (ASCII, 如 "master secret")
 * out_len <= 256 (内部按 32 字节一块生成) */
PUBLIC int tls_prf_sha256(const t_8 *secret, int secret_len,
                          const char *label,
                          const t_8 *seed, int seed_len,
                          t_8 *out, int out_len);

/* ===== 工具: 内存比较/清零 (常量时间用于将来做 MAC 比较) ===== */
PUBLIC int crypto_memcmp_ct(const t_8 *a, const t_8 *b, int len);
PUBLIC void crypto_wipe(void *p, int len);

/* ===== SHA-1 (FIPS 180-4; TLS 1.2 的 Finished 旧算法、旧证书签名) ===== */
#define SHA1_DIGEST    20

typedef struct {
	t_32 h[5];
	t_8  buf[SHA256_BLOCK];
	t_32 buf_len;
	t_32 total_hi;
	t_32 total_lo;
} SHA1_CTX;

PUBLIC void sha1_init(SHA1_CTX *ctx);
PUBLIC void sha1_update(SHA1_CTX *ctx, const void *data, int len);
PUBLIC void sha1_final(SHA1_CTX *ctx, t_8 out[SHA1_DIGEST]);
PUBLIC void sha1(const void *data, int len, t_8 out[SHA1_DIGEST]);
PUBLIC void hmac_sha1(const t_8 *key, int key_len,
                      const t_8 *data, int data_len,
                      t_8 out[SHA1_DIGEST]);

/* ===== AES-128 (FIPS 197) =====
 * 只做分组和基础模式; 填充/分块 由 TLS 记录层负责
 * 说明: S 盒在首次使用时由 GF(2^8) 运算现场生成, 不含手抄常数表 */

typedef struct {
	t_8 rk[176];          /* 11 组轮密钥 */
} AES128_KEY;

PUBLIC void aes128_setkey(AES128_KEY *ks, const t_8 key[16]);
PUBLIC void aes128_encrypt_block(const AES128_KEY *ks,
                                 const t_8 in[16], t_8 out[16]);
PUBLIC void aes128_decrypt_block(const AES128_KEY *ks,
                                 const t_8 in[16], t_8 out[16]);

/* CBC: len 必须是 16 的倍数; iv 会被就地更新 */
PUBLIC void aes128_cbc_encrypt(const AES128_KEY *ks, t_8 iv[16],
                               const t_8 *in, t_8 *out, int len);
PUBLIC void aes128_cbc_decrypt(const AES128_KEY *ks, t_8 iv[16],
                               const t_8 *in, t_8 *out, int len);

/* CTR: nonce 为 16 字节初始计数器 (就地加密/解密, in 与 out 可相同) */
PUBLIC void aes128_ctr_xcrypt(const AES128_KEY *ks, const t_8 nonce[16],
                              const t_8 *in, t_8 *out, int len);

/* ===== AES-128-GCM (NIST SP 800-38D) =====
 * nonce 12 字节, tag 16 字节; aad 可为 0
 * 返回 0=成功, -1=参数非法 (长度越界等) */
PUBLIC int aes128_gcm_encrypt(const AES128_KEY *ks, const t_8 nonce[12],
                              const t_8 *aad, int aad_len,
                              const t_8 *in, t_8 *out, int len,
                              t_8 tag[16]);
/* 校验 tag (常量时间), 返回 0=认证通过 */
PUBLIC int aes128_gcm_decrypt(const AES128_KEY *ks, const t_8 nonce[12],
                              const t_8 *aad, int aad_len,
                              const t_8 *in, t_8 *out, int len,
                              const t_8 tag[16]);
/* ===== RSA-2048 公钥运算 + PKCS#1 v1.5 (见 lib/rsa.c) =====
 * 只做公钥方向: 加密 (TLS 密钥交换) 和签名校验 (证书 / ServerKeyExchange) */

/* out = base^e mod n (n_len 字节大端). 返回 0=成功 */
PUBLIC int rsa_modexp(const t_8 *n, int n_len, t_32 e,
                      const t_8 *base, int base_len, t_8 *out);

/* 校验 PKCS#1 v1.5 + SHA-256 签名. 返回 0=通过, <0=失败原因码 */
PUBLIC int rsa_verify_pkcs1_sha256(const t_8 *n, int n_len, t_32 e,
                                   const t_8 *sig, const t_8 *hash32);

/* 用给定 PS 构造 v1.5 加密块并模幂 (确定性, 供测试用)
 * em 与 out 各 n_len 字节 */
PUBLIC int rsa_encrypt_v15_with_ps(const t_8 *n, int n_len, t_32 e,
                                   const t_8 *msg, int msg_len,
                                   const t_8 *ps, int ps_len,
                                   t_8 *em, t_8 *out);

/* 用内部随机源构造 v1.5 加密块并模幂 (TLS 用) */
PUBLIC int rsa_encrypt_v15(const t_8 *n, int n_len, t_32 e,
                           const t_8 *msg, int msg_len, t_8 *out);

/* 演示级随机源 (必须在启动时用 ticks 之类的熵播种) */
PUBLIC void rsa_random_seed(t_32 seed);
PUBLIC void rsa_random_bytes(t_8 *buf, int len);
#endif /* _CATOS_CRYPTO_H_ */
