/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              x509.h
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                    CatOS 内核 X.509 证书解析与链校验

  范围:
    - 极简 DER/ASN.1 解析 (只支持定长/长形式长度, 不支持 indefinite)
    - Certificate ::= SEQUENCE { tbsCertificate, sigAlg, signature }
    - 从 tbsCertificate 取: 签发者/主体 Name(整段 DER)、有效期、
      SubjectPublicKeyInfo 里的 RSA n/e
    - 签名算法只支持 sha256WithRSAEncryption (1.2.840.113549.1.1.11)
    - 链校验: child.issuer == parent.subject (整段 DER 字节相等)
              + 用 parent 公钥验证 child 的签名 + 有效期检查
  不做:
    - 扩展项解析 (BasicConstraints / KeyUsage / SAN)、CRL/OCSP
    - 名称规范化比较 (RFC 4518) —— 真实世界需要, 这里先按 DER 字节比较

  约束: 无动态分配; 指针指向调用者的缓冲区; 所有长度做边界检查
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#ifndef _CATOS_X509_H_
#define _CATOS_X509_H_

#include "type.h"

#define X509_OK             0
#define X509_ERR_ARG       -1
#define X509_ERR_DER       -2
#define X509_ERR_FORMAT    -3
#define X509_ERR_ALG       -4
#define X509_ERR_TIME      -5
#define X509_ERR_SIG       -6
#define X509_ERR_ISSUER    -7

/* 指向完整 TLV (tag+len+value) 的片段 */
typedef struct {
	const t_8 *p;
	int        len;
} X509_DER;

typedef struct {
	X509_DER tbs;              /* 被签名的 TBS 原文 */
	X509_DER issuer;           /* Name (完整 DER) */
	X509_DER subject;          /* Name (完整 DER) */
	X509_DER not_before;       /* Time 内容 (不含 tag/len) */
	X509_DER not_after;
	X509_DER spki;             /* SubjectPublicKeyInfo 原文 */
	X509_DER rsa_n;            /* INTEGER 内容 */
	X509_DER rsa_e;
	int      sig_alg;          /* 1 = sha256WithRSA, 2 = sha1WithRSA, 0 = 其它 */
	X509_DER sig;              /* 签名值 (不含 BIT STRING 的 unused 字节) */
} X509_CERT;

/* 解析一张证书. 返回 X509_OK 或错误码 */
PUBLIC int x509_parse(const t_8 *der, int len, X509_CERT *out);

/* 有效期检查: 给定日期, 返回 X509_OK 表示在有效期内 */
PUBLIC int x509_check_time(const X509_CERT *c, int year, int month, int day);

/* child 是否由 issuer 签发 (签发者匹配 + 签名验证). 返回 X509_OK 表示通过 */
PUBLIC int x509_verify_signed_by(const X509_CERT *child, const X509_CERT *issuer);

/* 链校验: ders[i]/lens[i] 从叶子到根; 时间用 y/m/d. 返回 X509_OK 表示整链有效 */
PUBLIC int x509_verify_chain(const t_8 *const *ders, const int *lens, int count,
                             int year, int month, int day);

/* 从证书里取 RSA 公钥 (n 为定长大端, 右对齐到 n_max; e 为 <32 位整数) */
PUBLIC int x509_get_rsa(const X509_CERT *c, t_8 *n, int n_max, int *n_len,
                        t_32 *e);

#endif /* _CATOS_X509_H_ */
