/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              x509.c
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                    CatOS 内核 X.509 证书解析与链校验

  设计:
    - 手写极简 DER 解析, 只处理定长与长形式长度 (真实证书都这样)
    - 证书里的位串/整数按 TLV 切开, 记录指针与长度, 不复制不分配
    - 链校验: 名字整段 DER 字节相等 + 父证书公钥验子证书签名 + 有效期
  安全注意:
    - 每步都检查剩余长度, 恶意长度一律返回错误
    - 只接受 sha256WithRSA (sha1WithRSA 能识别但拒绝使用)
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include "type.h"
#include "const.h"
#include "crypto.h"

#include "x509.h"

/*======================================================================*
                          极简 DER 读取
 *======================================================================*/

/* 读一个 TLV; 成功时 *val 指向内容, *vlen 为内容长度, pp 前进到下一个 TLV */
PRIVATE int der_read(const t_8 **pp, const t_8 *end,
                     t_8 *tag, const t_8 **val, int *vlen)
{
	const t_8 *p = *pp;
	int l;

	if (!p || p + 2 > end) return X509_ERR_DER;
	*tag = *p++;
	l = *p++;
	if (l & 0x80) {
		int n = l & 0x7F;
		if (n <= 0 || n > 3) return X509_ERR_DER;
		if (p + n > end) return X509_ERR_DER;
		l = 0;
		while (n-- > 0) l = (l << 8) | *p++;
	}
	if (l < 0 || p + l > end) return X509_ERR_DER;
	*val = p;
	*vlen = l;
	*pp = p + l;
	return X509_OK;
}

/* 读一个 TLV 并把它作为完整的 DER 片段 (含 tag/len) 返回 */
PRIVATE int der_read_tlv(const t_8 **pp, const t_8 *end,
                         t_8 want_tag, X509_DER *out)
{
	const t_8 *start = *pp;
	const t_8 *val;
	int vlen;
	t_8 tag;

	if (der_read(pp, end, &tag, &val, &vlen) != X509_OK) return X509_ERR_DER;
	if (tag != want_tag) return X509_ERR_FORMAT;
	out->p = start;
	out->len = (int)(*pp - start);
	return X509_OK;
}

/* 内容片段 (只要 value) */
PRIVATE int der_read_content(const t_8 **pp, const t_8 *end,
                             t_8 want_tag, X509_DER *out)
{
	const t_8 *val;
	int vlen;
	t_8 tag;

	if (der_read(pp, end, &tag, &val, &vlen) != X509_OK) return X509_ERR_DER;
	if (tag != want_tag) return X509_ERR_FORMAT;
	out->p = val;
	out->len = vlen;
	return X509_OK;
}

/*======================================================================*
                          OID 识别
 *======================================================================*/

/* sha256WithRSAEncryption: 1.2.840.113549.1.1.11 -> 2a 86 48 86 f7 0d 01 01 0b */
PRIVATE const t_8 oid_sha256_rsa[] = {
	0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x0b
};
/* sha1WithRSAEncryption: ... 01 01 05 */
PRIVATE const t_8 oid_sha1_rsa[] = {
	0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x05
};

PRIVATE int der_eq(const X509_DER *a, const X509_DER *b)
{
	int i;
	if (!a || !b) return 0;
	if (a->len != b->len || a->len <= 0) return 0;
	for (i = 0; i < a->len; i++) {
		if (a->p[i] != b->p[i]) return 0;
	}
	return 1;
}

/*======================================================================*
                          时间解析
 *======================================================================*/

PRIVATE int two_digits(const t_8 *p)
{
	if (p[0] < '0' || p[0] > '9' || p[1] < '0' || p[1] > '9') return -1;
	return (p[0] - '0') * 10 + (p[1] - '0');
}

/* 解析 UTCTime "YYMMDDHHMMSSZ" 或 GeneralizedTime "YYYYMMDDHHMMSSZ" */
PRIVATE int parse_time(const X509_DER *t, int *y, int *m, int *d)
{
	int yy, mm, dd;

	if (!t || t->len < 10) return X509_ERR_FORMAT;

	if (t->len >= 15) {                       /* GeneralizedTime (4 位年) */
		int yyyy = two_digits(t->p) * 100 + two_digits(t->p + 2);
		yy = yyyy;
		mm = two_digits(t->p + 4);
		dd = two_digits(t->p + 6);
	} else {                                  /* UTCTime (2 位年) */
		yy = two_digits(t->p);
		mm = two_digits(t->p + 2);
		dd = two_digits(t->p + 4);
		if (yy < 0) return X509_ERR_FORMAT;
		yy += (yy < 50) ? 2000 : 1900;
	}
	if (yy < 0 || mm < 0 || dd < 0) return X509_ERR_FORMAT;
	*y = yy; *m = mm; *d = dd;
	return X509_OK;
}

PRIVATE int date_cmp(int y1, int m1, int d1, int y2, int m2, int d2)
{
	if (y1 != y2) return (y1 < y2) ? -1 : 1;
	if (m1 != m2) return (m1 < m2) ? -1 : 1;
	if (d1 != d2) return (d1 < d2) ? -1 : 1;
	return 0;
}

/*======================================================================*
                          证书解析
 *======================================================================*/

PRIVATE int parse_sig_alg(const t_8 *p, int len, int *out_alg)
{
	const t_8 *end = p + len;
	const t_8 *seq_val;
	int seq_len;
	t_8 tag;
	X509_DER oid;

	/* AlgorithmIdentifier ::= SEQUENCE { algorithm OID, parameters ANY } */
	if (der_read(&p, end, &tag, &seq_val, &seq_len) != X509_OK) return X509_ERR_DER;
	if (tag != 0x30) return X509_ERR_FORMAT;
	{
		const t_8 *q = seq_val;
		const t_8 *qend = seq_val + seq_len;
		if (der_read_content(&q, qend, 0x06, &oid) != X509_OK) return X509_ERR_FORMAT;
	}

	*out_alg = 0;
	if (oid.len == (int)sizeof(oid_sha256_rsa)) {
		int i, same = 1;
		for (i = 0; i < oid.len; i++) {
			if (oid.p[i] != oid_sha256_rsa[i]) { same = 0; break; }
		}
		if (same) *out_alg = 1;
	}
	if (*out_alg == 0 && oid.len == (int)sizeof(oid_sha1_rsa)) {
		int i, same = 1;
		for (i = 0; i < oid.len; i++) {
			if (oid.p[i] != oid_sha1_rsa[i]) { same = 0; break; }
		}
		if (same) *out_alg = 2;
	}
	return X509_OK;
}

/* 解析 SubjectPublicKeyInfo 里的 RSA 公钥 */
PRIVATE int parse_spki(const X509_DER *spki, X509_CERT *out)
{
	const t_8 *p = spki->p;
	const t_8 *end = spki->p + spki->len;
	const t_8 *val;
	int vlen;
	t_8 tag;
	X509_DER bits;

	/* SEQUENCE { AlgorithmIdentifier, BIT STRING } */
	if (der_read(&p, end, &tag, &val, &vlen) != X509_OK) return X509_ERR_DER;
	if (tag != 0x30) return X509_ERR_FORMAT;
	{
		const t_8 *q = val;
		const t_8 *qend = val + vlen;
		t_8 atag;
		const t_8 *aval;
		int alen;
		/* 先跳过 AlgorithmIdentifier, 再取 BIT STRING */
		if (der_read(&q, qend, &atag, &aval, &alen) != X509_OK) return X509_ERR_DER;
		if (atag != 0x30) return X509_ERR_FORMAT;
		(void)aval;
		(void)alen;
		if (der_read_content(&q, qend, 0x03, &bits) != X509_OK) return X509_ERR_FORMAT;
	}
	if (bits.len < 2 || bits.p[0] != 0) return X509_ERR_FORMAT;   /* 未用位数必须为 0 */

	/* BIT STRING 内容是 RSAPublicKey ::= SEQUENCE { n INTEGER, e INTEGER } */
	{
		const t_8 *q = bits.p + 1;
		const t_8 *qend = bits.p + bits.len;
		const t_8 *rsa;
		int rsa_len;

		if (der_read(&q, qend, &tag, &rsa, &rsa_len) != X509_OK) return X509_ERR_DER;
		if (tag != 0x30) return X509_ERR_FORMAT;
		{
			const t_8 *r = rsa;
			const t_8 *rend = rsa + rsa_len;
			if (der_read_content(&r, rend, 0x02, &out->rsa_n) != X509_OK) return X509_ERR_FORMAT;
			if (der_read_content(&r, rend, 0x02, &out->rsa_e) != X509_OK) return X509_ERR_FORMAT;
		}
	}
	/* DER INTEGER 为正数时会补前导 0, 取公钥时必须去掉 */
	while (out->rsa_n.len > 1 && out->rsa_n.p[0] == 0) {
		out->rsa_n.p++;
		out->rsa_n.len--;
	}
	while (out->rsa_e.len > 1 && out->rsa_e.p[0] == 0) {
		out->rsa_e.p++;
		out->rsa_e.len--;
	}
	if (out->rsa_n.len < 64 || out->rsa_n.len > 512) return X509_ERR_FORMAT;
	if (out->rsa_e.len < 1 || out->rsa_e.len > 4) return X509_ERR_FORMAT;
	return X509_OK;
}

PUBLIC int x509_parse(const t_8 *der, int len, X509_CERT *out)
{
	const t_8 *p = der;
	const t_8 *end = der + len;
	const t_8 *val;
	int vlen;
	t_8 tag;
	X509_DER cert_seq, tbs, sigalg, sigval;
	int rc;

	if (!der || !out || len <= 0) return X509_ERR_ARG;
	for (rc = 0; rc < (int)sizeof(X509_CERT); rc++) ((t_8 *)out)[rc] = 0;

	/* Certificate ::= SEQUENCE { tbs, sigAlg, signature } */
	if (der_read(&p, end, &tag, &val, &vlen) != X509_OK) return X509_ERR_DER;
	if (tag != 0x30) return X509_ERR_FORMAT;
	cert_seq.p = val; cert_seq.len = vlen;

	{
		const t_8 *q = cert_seq.p;
		const t_8 *qend = cert_seq.p + cert_seq.len;

		if (der_read_tlv(&q, qend, 0x30, &tbs) != X509_OK) return X509_ERR_FORMAT;
		out->tbs = tbs;
		if (der_read_tlv(&q, qend, 0x30, &sigalg) != X509_OK) return X509_ERR_FORMAT;
		if (der_read_content(&q, qend, 0x03, &sigval) != X509_OK) return X509_ERR_FORMAT;

		if (sigval.len < 2) return X509_ERR_FORMAT;
		out->sig.p = sigval.p + 1;              /* 跳过 unused-bits 字节 */
		out->sig.len = sigval.len - 1;

		if (parse_sig_alg(sigalg.p, sigalg.len, &out->sig_alg) != X509_OK) {
			return X509_ERR_ALG;
		}
	}

	/* 解析 TBS */
{
		const t_8 *q = tbs.p + 0;
		const t_8 *qend = tbs.p + tbs.len;
		const t_8 *inner;
		int inner_len;

		if (der_read(&q, qend, &tag, &inner, &inner_len) != X509_OK) return X509_ERR_DER;
		if (tag != 0x30) return X509_ERR_FORMAT;
		q = inner;
		qend = inner + inner_len;

		/* [0] version (可选) */
		{
			const t_8 *peek = q;
			const t_8 *pv;
			int pl;
			t_8 pt;
			if (der_read(&peek, qend, &pt, &pv, &pl) == X509_OK) {
				if (pt == 0xA0) q = peek;       /* 跳过 [0] */
			}
		}
		/* serialNumber INTEGER */
		if (der_read_tlv(&q, qend, 0x02, &sigval) != X509_OK) return X509_ERR_FORMAT;
		/* signature AlgorithmIdentifier */
		if (der_read_tlv(&q, qend, 0x30, &sigval) != X509_OK) return X509_ERR_FORMAT;
		/* issuer Name */
		if (der_read_tlv(&q, qend, 0x30, &out->issuer) != X509_OK) return X509_ERR_FORMAT;
		/* validity SEQUENCE { notBefore, notAfter } —— 注意要读 SEQUENCE 的内容 */
		{
			const t_8 *v;
			const t_8 *vend;
			t_8 vtag;
			const t_8 *vval;
			int vlen;
			if (der_read(&q, qend, &vtag, &vval, &vlen) != X509_OK) return X509_ERR_DER;
			if (vtag != 0x30) return X509_ERR_FORMAT;
			v = vval;
			vend = vval + vlen;
			if (der_read(&v, vend, &tag, &val, &vlen) != X509_OK) return X509_ERR_DER;
			if (tag != 0x17 && tag != 0x18) return X509_ERR_FORMAT;
			out->not_before.p = val;
			out->not_before.len = vlen;
			if (der_read(&v, vend, &tag, &val, &vlen) != X509_OK) return X509_ERR_DER;
			if (tag != 0x17 && tag != 0x18) return X509_ERR_FORMAT;
			out->not_after.p = val;
			out->not_after.len = vlen;
		}
		/* subject Name */
		if (der_read_tlv(&q, qend, 0x30, &out->subject) != X509_OK) return X509_ERR_FORMAT;
		/* subjectPublicKeyInfo */
		if (der_read_tlv(&q, qend, 0x30, &out->spki) != X509_OK) return X509_ERR_FORMAT;
		if (parse_spki(&out->spki, out) != X509_OK) return X509_ERR_FORMAT;
	}

	if (out->sig_alg == 0) return X509_ERR_ALG;   /* 不支持的签名算法 */
	return X509_OK;
}

/*======================================================================*
                          有效期 / 公钥
 *======================================================================*/

PUBLIC int x509_check_time(const X509_CERT *c, int year, int month, int day)
{
	int y, m, d;

	if (!c) return X509_ERR_ARG;
	if (parse_time(&c->not_before, &y, &m, &d) != X509_OK) return X509_ERR_TIME;
	if (date_cmp(year, month, day, y, m, d) < 0) return X509_ERR_TIME;   /* 还没生效 */
	if (parse_time(&c->not_after, &y, &m, &d) != X509_OK) return X509_ERR_TIME;
	if (date_cmp(year, month, day, y, m, d) > 0) return X509_ERR_TIME;   /* 已过期 */
	return X509_OK;
}

PUBLIC int x509_get_rsa(const X509_CERT *c, t_8 *n, int n_max, int *n_len,
                        t_32 *e)
{
	int i;
	t_32 ev = 0;

	if (!c || !n || !n_len || !e) return X509_ERR_ARG;
	if (c->rsa_n.len <= 0 || c->rsa_n.len > n_max) return X509_ERR_FORMAT;

	for (i = 0; i < c->rsa_n.len; i++) n[i] = c->rsa_n.p[i];
	*n_len = c->rsa_n.len;

	for (i = 0; i < c->rsa_e.len; i++) ev = (ev << 8) | (t_32)c->rsa_e.p[i];
	if (ev == 0 || ev > 0xFFFFFFF) return X509_ERR_FORMAT;
	*e = ev;
	return X509_OK;
}

/*======================================================================*
                          链校验
 *======================================================================*/

PUBLIC int x509_verify_signed_by(const X509_CERT *child, const X509_CERT *issuer)
{
	t_8 n[256];
	int n_len = 0;
	t_32 e = 0;
	t_8 hash[SHA256_DIGEST];

	if (!child || !issuer) return X509_ERR_ARG;

	/* 名字必须整段 DER 相等 */
	if (!der_eq(&child->issuer, &issuer->subject)) return X509_ERR_ISSUER;

	if (child->sig_alg != 1) return X509_ERR_ALG;      /* 只接受 sha256WithRSA */
	if (x509_get_rsa(issuer, n, (int)sizeof(n), &n_len, &e) != X509_OK) {
		return X509_ERR_FORMAT;
	}
	if (child->sig.len != n_len) return X509_ERR_SIG;

	/* 签名是对 tbsCertificate 的哈希做 RSA 校验 */
	sha256(child->tbs.p, child->tbs.len, hash);
	if (rsa_verify_pkcs1_sha256(n, n_len, e, child->sig.p, hash) != 0) {
		return X509_ERR_SIG;
	}
	return X509_OK;
}

PUBLIC int x509_verify_chain(const t_8 *const *ders, const int *lens, int count,
                             int year, int month, int day)
{
	static X509_CERT certs[4];
	int i;

	if (!ders || !lens || count <= 0 || count > 4) return X509_ERR_ARG;

	for (i = 0; i < count; i++) {
		if (x509_parse(ders[i], lens[i], &certs[i]) != X509_OK) return X509_ERR_FORMAT;
	}
	for (i = 0; i < count; i++) {
		if (x509_check_time(&certs[i], year, month, day) != X509_OK) return X509_ERR_TIME;
	}
	for (i = 0; i + 1 < count; i++) {
		if (x509_verify_signed_by(&certs[i], &certs[i + 1]) != X509_OK) {
			return X509_ERR_SIG;
		}
	}
	/* 根必须自签 */
	if (x509_verify_signed_by(&certs[count - 1], &certs[count - 1]) != X509_OK) {
		return X509_ERR_SIG;
	}
	return X509_OK;
}
