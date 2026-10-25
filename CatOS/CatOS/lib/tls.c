/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              tls.c
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                  CatOS TLS 1.2 记录层 / 握手消息编解码

  只做"字节搬砖": 记录头、握手头、ClientHello 生成、服务端消息解析.
  加密/状态机/证书链校验在后续版本 (见 include/tls.h 头注释).

  安全/健壮性约定:
    - 每个读操作前都检查剩余长度, 越界返回 TLS_ERR_SHORT
    - 记录长度、握手长度都夹紧到协议上限
    - 解析函数不写共享状态, 可重入
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include "type.h"
#include "const.h"
#include "protect.h"
#include "proc.h"
#include "tty.h"
#include "console.h"
#include "global.h"
#include "proto.h"

#ifdef TLS_ERR_DEBUG
PUBLIC void dbg_tls(const char *msg, int val);
#define TLS_DBG(msg, val) do { dbg_tls(msg, (int)(val)); } while (0)
#else
#define TLS_DBG(msg, val) do { } while (0)
#endif
#include "const.h"
#include "tls.h"

/*======================================================================*
                          字节读写小工具
 *======================================================================*/

PRIVATE t_16 rd16(const t_8 *p)
{
	return (t_16)(((t_16)p[0] << 8) | (t_16)p[1]);
}

PRIVATE t_32 rd24(const t_8 *p)
{
	return ((t_32)p[0] << 16) | ((t_32)p[1] << 8) | (t_32)p[2];
}

PRIVATE void wr16(t_8 *p, t_16 v)
{
	p[0] = (t_8)(v >> 8);
	p[1] = (t_8)v;
}

PRIVATE void wr24(t_8 *p, t_32 v)
{
	p[0] = (t_8)(v >> 16);
	p[1] = (t_8)(v >> 8);
	p[2] = (t_8)v;
}

PRIVATE int strnlen_max(const char *s, int max)
{
	int n = 0;
	while (n < max && s[n]) n++;
	return n;
}

/*======================================================================*
                          记录层
 *======================================================================*/

PUBLIC int tls_parse_record(const t_8 *buf, int len, TLS_RECORD *rec)
{
	t_16 rlen;

	if (!buf || !rec || len < 0) return TLS_ERR_ARG;
	if (len < 5) return TLS_ERR_SHORT;

	rlen = rd16(buf + 3);
	if (rlen > TLS_RECORD_MAX) return TLS_ERR_TOO_BIG;
	if (len < 5 + (int)rlen) return TLS_ERR_SHORT;

	rec->type = buf[0];
	rec->major = buf[1];
	rec->minor = buf[2];
	rec->length = rlen;
	rec->payload = buf + 5;
	return 5 + (int)rlen;
}

PUBLIC int tls_build_record(t_8 type, const t_8 *payload, int len,
                            t_8 *out, int cap)
{
	if (!out || cap < 0) return TLS_ERR_ARG;
	if (len < 0 || len > TLS_RECORD_MAX) return TLS_ERR_ARG;
	if (cap < 5 + len) return TLS_ERR_TOO_BIG;
	if (len > 0 && !payload) return TLS_ERR_ARG;

	out[0] = type;
	out[1] = TLS_VERSION_12_MAJOR;
	out[2] = TLS_VERSION_12_MINOR;
	wr16(out + 3, (t_16)len);
	if (len > 0) {
		int i;
		for (i = 0; i < len; i++) out[5 + i] = payload[i];
	}
	return 5 + len;
}

/*======================================================================*
                          握手消息头
 *======================================================================*/

PUBLIC int tls_hs_begin(t_8 type, t_8 *out, int cap)
{
	if (!out || cap < 4) return TLS_ERR_ARG;
	out[0] = type;
	out[1] = 0;
	out[2] = 0;
	out[3] = 0;
	return 4;
}

PUBLIC int tls_hs_end(t_8 *out, int off, int total)
{
	int body;

	if (!out || off < 0 || total < off + 4) return TLS_ERR_ARG;
	body = total - off - 4;
	if (body > 0xFFFFFF) return TLS_ERR_TOO_BIG;
	wr24(out + off + 1, (t_32)body);
	return TLS_OK;
}

PUBLIC int tls_hs_header(const t_8 *buf, int len, t_8 *type,
                         const t_8 **body, int *body_len)
{
	t_32 blen;

	if (!buf || !type || !body || !body_len || len < 0) return TLS_ERR_ARG;
	if (len < 4) return TLS_ERR_SHORT;

	blen = rd24(buf + 1);
	if (blen > TLS_HANDSHAKE_MAX) return TLS_ERR_TOO_BIG;
	if (len < 4 + (int)blen) return TLS_ERR_SHORT;

	*type = buf[0];
	*body = buf + 4;
	*body_len = (int)blen;
	return 4 + (int)blen;
}

/*======================================================================*
                          ClientHello
 *======================================================================*/

PUBLIC int tls_build_client_hello(const TLS_CLIENT_HELLO *ch, t_8 *out, int cap)
{
	int pos;
	int i;
	int suites_len;
	int sni_len = 0;
	int ext_len;
	int name_len;

	if (!ch || !out) return TLS_ERR_ARG;
	if (ch->suite_count <= 0 || ch->suite_count > TLS_MAX_SUITES) return TLS_ERR_ARG;
	if (cap < 64) return TLS_ERR_TOO_BIG;

	if (ch->server_name[0]) {
		name_len = strnlen_max(ch->server_name, (int)sizeof(ch->server_name));
		if (name_len <= 0) return TLS_ERR_ARG;
		/* ext: type(2)+len(2)+list_len(2)+type(1)+name_len(2)+name */
		sni_len = 2 + 2 + 2 + 1 + 2 + name_len;
	}

	suites_len = 2 * ch->suite_count;

	/* 4 字节握手头 + 2 版本 + 32 随机 + 1 sid 长 + 2 套件长 + 套件
	 * + 1 压缩长 + 1 压缩 + 2 扩展长 + 扩展 */
	{
		int need = 4 + 2 + 32 + 1 + 2 + suites_len + 1 + 1 + 2 + sni_len;
		if (cap < need) return TLS_ERR_TOO_BIG;
	}

	pos = tls_hs_begin(TLS_HS_CLIENT_HELLO, out, cap);

	out[pos++] = ch->version_major ? ch->version_major : TLS_VERSION_12_MAJOR;
	out[pos++] = ch->version_minor ? ch->version_minor : TLS_VERSION_12_MINOR;
	for (i = 0; i < 32; i++) out[pos++] = ch->random[i];

	out[pos++] = 0;                              /* session_id 为空 */
	wr16(out + pos, (t_16)suites_len);
	pos += 2;
	for (i = 0; i < ch->suite_count; i++) {
		wr16(out + pos, ch->suites[i]);
		pos += 2;
	}
	out[pos++] = 1;                              /* 压缩方法: 只支持 null */
	out[pos++] = 0;

	if (sni_len > 0) {
		ext_len = sni_len;
		wr16(out + pos, (t_16)ext_len);
		pos += 2;
		/* server_name 扩展 */
		wr16(out + pos, 0x0000);
		pos += 2;
		wr16(out + pos, (t_16)(2 + 1 + 2 + name_len));
		pos += 2;
		wr16(out + pos, (t_16)(1 + 2 + name_len));   /* 列表长度 */
		pos += 2;
		out[pos++] = 0;                              /* host_name */
		wr16(out + pos, (t_16)name_len);
		pos += 2;
		for (i = 0; i < name_len; i++) out[pos++] = (t_8)ch->server_name[i];
	} else {
		wr16(out + pos, 0);                      /* 无扩展 */
		pos += 2;
	}

	if (tls_hs_end(out, 0, pos) != TLS_OK) return TLS_ERR_FORMAT;
	return pos;
}

/*======================================================================*
                          ServerHello
 *======================================================================*/

PUBLIC int tls_parse_server_hello(const t_8 *msg, int len, TLS_SERVER_HELLO *sh)
{
	int pos = 0;
	int sid_len;
	int ext_len;
	int i;

	if (!msg || !sh) return TLS_ERR_ARG;
	if (len < 2 + 32 + 1) return TLS_ERR_SHORT;

	sh->version_major = msg[pos++];
	sh->version_minor = msg[pos++];
	for (i = 0; i < 32; i++) sh->random[i] = msg[pos++];

	sid_len = msg[pos++];
	if (sid_len > 32) return TLS_ERR_FORMAT;
	if (pos + sid_len > len) return TLS_ERR_SHORT;
	sh->session_id_len = sid_len;
	for (i = 0; i < sid_len; i++) sh->session_id[i] = msg[pos++];

	if (pos + 3 > len) return TLS_ERR_SHORT;
	sh->suite = rd16(msg + pos);
	pos += 2;
	sh->compression = msg[pos++];

	/* 扩展 (可选) */
	sh->extensions_len = 0;
	if (pos + 2 <= len) {
		ext_len = (int)rd16(msg + pos);
		pos += 2;
		if (pos + ext_len > len) return TLS_ERR_SHORT;
		sh->extensions_len = ext_len;
	}
	return TLS_OK;
}

/*======================================================================*
                          Certificate
 *======================================================================*/

PUBLIC int tls_parse_certificate(const t_8 *msg, int len, TLS_CERT_LIST *list)
{
	int total;

	if (!msg || !list) return TLS_ERR_ARG;
	if (len < 3) return TLS_ERR_SHORT;

	total = (int)rd24(msg);
	if (total > len - 3) return TLS_ERR_SHORT;

	list->data = msg + 3;
	list->length = total;
	if (total == 0) return TLS_OK;               /* 空列表: 合法但无意义 */
	return TLS_OK;
}

PUBLIC int tls_cert_at(const TLS_CERT_LIST *list, int idx,
                       const t_8 **cert, int *cert_len)
{
	int pos = 0;
	int cur = 0;

	if (!list || !cert || !cert_len) return TLS_ERR_ARG;
	if (idx < 0) return TLS_ERR_ARG;

	while (pos + 3 <= list->length) {
		int clen = (int)rd24(list->data + pos);
		pos += 3;
		if (clen < 0 || pos + clen > list->length) return TLS_ERR_FORMAT;
		if (cur == idx) {
			*cert = list->data + pos;
			*cert_len = clen;
			return TLS_OK;
		}
		pos += clen;
		cur++;
	}
	return TLS_ERR_SHORT;                        /* 索引越界 */
}

PUBLIC int tls_parse_server_hello_done(const t_8 *msg, int len)
{
	(void)msg;
	if (len != 0) return TLS_ERR_FORMAT;
	return TLS_OK;
}

/*======================================================================*
              TLS 1.2 会话: 密钥派生 / Finished / CBC 记录加解密

  注意: 本实现把单条记录的片段上限压到 TLS_FRAG_MAX (2KB), 因为内核任务栈
  只有 32KB, 不能用 16KB 的记录缓冲. 握手消息和 HTTP 头部都远小于 2KB.
 *======================================================================*/

#define TLS_FRAG_MAX 2048

PRIVATE void put_seq64(t_8 *p, t_32 v)
{
	p[0] = p[1] = p[2] = p[3] = 0;
	p[4] = (t_8)(v >> 24);
	p[5] = (t_8)(v >> 16);
	p[6] = (t_8)(v >> 8);
	p[7] = (t_8)v;
}

PUBLIC int tls_session_init(TLS_SESSION *s, t_16 suite)
{
	int i;

	if (!s) return TLS_ERR_ARG;
	for (i = 0; i < (int)sizeof(TLS_SESSION); i++) ((t_8 *)s)[i] = 0;

	s->suite = suite;
	if (suite == TLS_SUITE_RSA_AES128_CBC_SHA) {
		s->mac_len = 20;               /* HMAC-SHA1 */
		s->enc_len = 16;               /* AES-128 */
		s->iv_len = 16;
	} else if (suite == TLS_SUITE_RSA_AES128_GCM_SHA256) {
		s->mac_len = 0;                /* AEAD: 无独立 MAC */
		s->enc_len = 16;               /* AES-128 */
		s->iv_len = 4;                 /* 4 字节固定 nonce 前缀 */
	} else {
		/* 其它套件 (含 ECDHE) 尚未实现: 明确拒绝, 不静默降级 */
		return TLS_ERR_TYPE;
	}
	sha256_init(&s->transcript);
	return TLS_OK;
}

PUBLIC void tls_transcript_add(TLS_SESSION *s, const t_8 *msg, int len)
{
	if (!s || !msg || len <= 0) return;
	sha256_update(&s->transcript, msg, len);
}

PUBLIC int tls_derive_keys(TLS_SESSION *s, const t_8 pre_master[TLS_PRE_MASTER_LEN])
{
	t_8 seed[64];
	t_8 keyblock[TLS_MAX_KEYBLOCK];
	int need, off, i;

	if (!s || !pre_master) return TLS_ERR_ARG;
	if (s->enc_len <= 0 || s->iv_len <= 0) return TLS_ERR_TYPE;
	if (s->mac_len < 0) return TLS_ERR_TYPE;

	for (i = 0; i < 32; i++) seed[i] = s->client_random[i];
	for (i = 0; i < 32; i++) seed[32 + i] = s->server_random[i];
	if (tls_prf_sha256(pre_master, TLS_PRE_MASTER_LEN, "master secret",
	                   seed, 64, s->master_secret, TLS_MASTER_LEN) != 0) {
		return TLS_ERR_ARG;
	}

	for (i = 0; i < 32; i++) seed[i] = s->server_random[i];
	for (i = 0; i < 32; i++) seed[32 + i] = s->client_random[i];
	need = 2 * (s->mac_len + s->enc_len + s->iv_len);
	if (need > TLS_MAX_KEYBLOCK) return TLS_ERR_TOO_BIG;
	if (tls_prf_sha256(s->master_secret, TLS_MASTER_LEN, "key expansion",
	                   seed, 64, keyblock, need) != 0) {
		return TLS_ERR_ARG;
	}

	off = 0;
	for (i = 0; i < s->mac_len; i++) s->client_mac[i] = keyblock[off++];
	for (i = 0; i < s->mac_len; i++) s->server_mac[i] = keyblock[off++];
	for (i = 0; i < s->enc_len; i++) s->client_key[i] = keyblock[off++];
	for (i = 0; i < s->enc_len; i++) s->server_key[i] = keyblock[off++];
	for (i = 0; i < s->iv_len; i++) s->client_iv[i] = keyblock[off++];
	for (i = 0; i < s->iv_len; i++) s->server_iv[i] = keyblock[off++];

	crypto_wipe(keyblock, (int)sizeof(keyblock));
	return TLS_OK;
}

PUBLIC int tls_finished_verify(TLS_SESSION *s, int is_client, t_8 out[TLS_FINISHED_LEN])
{
	SHA256_CTX copy;
	t_8 hash[SHA256_DIGEST];

	if (!s || !out) return TLS_ERR_ARG;
	copy = s->transcript;
	sha256_final(&copy, hash);
	if (tls_prf_sha256(s->master_secret, TLS_MASTER_LEN,
	                   is_client ? "client finished" : "server finished",
	                   hash, SHA256_DIGEST, out, TLS_FINISHED_LEN) != 0) {
		return TLS_ERR_ARG;
	}
	return TLS_OK;
}

/* 增量计算 HMAC (避免 16KB 临时缓冲): 返回 TLS_OK */
PRIVATE int hmac_incr(int is_sha1, const t_8 *key, int key_len,
                      const t_8 *a, int alen,
                      const t_8 *b, int blen,
                      const t_8 *c, int clen,
                      t_8 *out)
{
	t_8 k[SHA256_BLOCK];
	t_8 pad[SHA256_BLOCK];
	t_8 inner[SHA256_DIGEST];
	int i;

	for (i = 0; i < SHA256_BLOCK; i++) k[i] = 0;

	if (is_sha1) {
		SHA1_CTX ctx1, ctx2;
		if (key_len > SHA256_BLOCK) sha1(key, key_len, k);
		else for (i = 0; i < key_len && i < SHA256_BLOCK; i++) k[i] = key[i];

		for (i = 0; i < SHA256_BLOCK; i++) pad[i] = (t_8)(k[i] ^ 0x36);
		sha1_init(&ctx1);
		sha1_update(&ctx1, pad, SHA256_BLOCK);
		if (alen > 0) sha1_update(&ctx1, a, alen);
		if (blen > 0) sha1_update(&ctx1, b, blen);
		if (clen > 0) sha1_update(&ctx1, c, clen);
		sha1_final(&ctx1, inner);

		for (i = 0; i < SHA256_BLOCK; i++) pad[i] = (t_8)(k[i] ^ 0x5C);
		sha1_init(&ctx2);
		sha1_update(&ctx2, pad, SHA256_BLOCK);
		sha1_update(&ctx2, inner, SHA1_DIGEST);
		sha1_final(&ctx2, out);
		crypto_wipe(inner, SHA1_DIGEST);
	} else {
		SHA256_CTX ctx1, ctx2;
		if (key_len > SHA256_BLOCK) sha256(key, key_len, k);
		else for (i = 0; i < key_len && i < SHA256_BLOCK; i++) k[i] = key[i];

		for (i = 0; i < SHA256_BLOCK; i++) pad[i] = (t_8)(k[i] ^ 0x36);
		sha256_init(&ctx1);
		sha256_update(&ctx1, pad, SHA256_BLOCK);
		if (alen > 0) sha256_update(&ctx1, a, alen);
		if (blen > 0) sha256_update(&ctx1, b, blen);
		if (clen > 0) sha256_update(&ctx1, c, clen);
		sha256_final(&ctx1, inner);

		for (i = 0; i < SHA256_BLOCK; i++) pad[i] = (t_8)(k[i] ^ 0x5C);
		sha256_init(&ctx2);
		sha256_update(&ctx2, pad, SHA256_BLOCK);
		sha256_update(&ctx2, inner, SHA256_DIGEST);
		sha256_final(&ctx2, out);
		crypto_wipe(inner, SHA256_DIGEST);
	}
	crypto_wipe(k, SHA256_BLOCK);
	crypto_wipe(pad, SHA256_BLOCK);
	return TLS_OK;
}

/* CBC 记录 MAC: HMAC(mac_key, seq || type || version || len || fragment) */
PRIVATE int cbc_mac(const t_8 *mac_key, int mac_len, t_32 seq, t_8 type,
                    const t_8 *frag, int len, t_8 *out)
{
	t_8 hdr[13];

	put_seq64(hdr, seq);
	hdr[8] = type;
	hdr[9] = TLS_VERSION_12_MAJOR;
	hdr[10] = TLS_VERSION_12_MINOR;
	hdr[11] = (t_8)(len >> 8);
	hdr[12] = (t_8)len;

	if (mac_len == 20) {
		return hmac_incr(1, mac_key, mac_len, hdr, 13, frag, len, 0, 0, out);
	}
	if (mac_len == 32) {
		return hmac_incr(0, mac_key, mac_len, hdr, 13, frag, len, 0, 0, out);
	}
	return TLS_ERR_TYPE;
}

PUBLIC int tls_seal(TLS_SESSION *s, t_8 type, const t_8 *in, int len,
                    t_8 *out, int cap)
{
	t_8 plain[TLS_FRAG_MAX + 64];
	t_8 iv[TLS_MAX_IV];
	AES128_KEY ks;
	int mac_len, total, pad_len, i;

	if (!s || !in || !out || len < 0) return TLS_ERR_ARG;
	if (!s->encrypted) return TLS_ERR_ARG;
	if (len > TLS_FRAG_MAX) return TLS_ERR_TOO_BIG;

	/* ---------- AES-GCM (AEAD) ---------- */
	if (s->suite == TLS_SUITE_RSA_AES128_GCM_SHA256) {
		t_8 nonce[12];
		t_8 aad[13];
		t_8 tag[16];
		AES128_KEY gks;
		int i;
		if (8 + len + 16 > cap) return TLS_ERR_TOO_BIG;

		put_seq64(out, s->seq_out);                   /* 显式 nonce = 序号 */
		for (i = 0; i < s->iv_len; i++) nonce[i] = s->client_iv[i];
		for (i = 0; i < 8; i++) nonce[s->iv_len + i] = out[i];

		put_seq64(aad, s->seq_out);
		aad[8] = type;
		aad[9] = TLS_VERSION_12_MAJOR;
		aad[10] = TLS_VERSION_12_MINOR;
		aad[11] = (t_8)(len >> 8);
		aad[12] = (t_8)len;

		aes128_setkey(&gks, s->client_key);
		if (aes128_gcm_encrypt(&gks, nonce, aad, 13, in, out + 8, len, tag) != 0) {
			return TLS_ERR_ARG;
		}
		for (i = 0; i < 16; i++) out[8 + len + i] = tag[i];
		s->seq_out++;
		crypto_wipe(&gks, (int)sizeof(gks));
		return 8 + len + 16;
	}

	mac_len = s->mac_len;
	total = len + mac_len;
	pad_len = 16 - (total % 16);
	if (pad_len == 0) pad_len = 16;
	total += pad_len;
	if (total > (int)sizeof(plain)) return TLS_ERR_TOO_BIG;
	if (s->iv_len + total > cap) return TLS_ERR_TOO_BIG;

	for (i = 0; i < len; i++) plain[i] = in[i];
	if (cbc_mac(s->client_mac, mac_len, s->seq_out, type, in, len,
	            &plain[len]) != TLS_OK) {
		return TLS_ERR_TYPE;
	}
	for (i = 0; i < pad_len; i++) plain[len + mac_len + i] = (t_8)(pad_len - 1);

	rsa_random_bytes(iv, s->iv_len);
	for (i = 0; i < s->iv_len; i++) out[i] = iv[i];
	aes128_setkey(&ks, s->client_key);
	aes128_cbc_encrypt(&ks, iv, plain, out + s->iv_len, total);

	s->seq_out++;
	crypto_wipe(plain, (int)sizeof(plain));
	crypto_wipe(&ks, (int)sizeof(ks));
	return s->iv_len + total;
}

PUBLIC int tls_unseal(TLS_SESSION *s, t_8 type, const t_8 *in, int len,
                      t_8 *out, int cap)
{
	t_8 iv[TLS_MAX_IV];
	t_8 plain[TLS_FRAG_MAX + 64];
	AES128_KEY ks;
	t_8 mac_calc[TLS_MAX_MAC];
	int mac_len, total, pad_len, i;

	if (!s || !in || !out || len < 0) return TLS_ERR_ARG;
	if (!s->encrypted) return TLS_ERR_ARG;
	if (len < s->iv_len + 16) return TLS_ERR_SHORT;

	/* ---------- AES-GCM (AEAD) ---------- */
	if (s->suite == TLS_SUITE_RSA_AES128_GCM_SHA256) {
		t_8 nonce[12];
		t_8 aad[13];
		AES128_KEY gks;
		int total;
		int i;

		if (len < 8 + 16) return TLS_ERR_SHORT;
		total = len - 8 - 16;
		if (total > cap) return TLS_ERR_TOO_BIG;

		for (i = 0; i < s->iv_len; i++) nonce[i] = s->server_iv[i];
		for (i = 0; i < 8; i++) nonce[s->iv_len + i] = in[i];

		put_seq64(aad, s->seq_in);
		aad[8] = type;
		aad[9] = TLS_VERSION_12_MAJOR;
		aad[10] = TLS_VERSION_12_MINOR;
		aad[11] = (t_8)(total >> 8);
		aad[12] = (t_8)total;

		aes128_setkey(&gks, s->server_key);
		{
			int grc = aes128_gcm_decrypt(&gks, nonce, aad, 13,
			                             in + 8, out, total,
			                             in + 8 + total);
			crypto_wipe(&gks, (int)sizeof(gks));
			if (grc != 0 && !s->skip_mac) {
				return TLS_ERR_FORMAT;           /* tag 校验失败 */
			}
			/* skip_mac 时即使 tag 不匹配也继续用解密结果 */
		}
		s->seq_in++;
		crypto_wipe(&gks, (int)sizeof(gks));
		return total;
	}

	mac_len = s->mac_len;
	total = len - s->iv_len;
	if (total % 16 != 0) return TLS_ERR_FORMAT;
	if (total > (int)sizeof(plain)) return TLS_ERR_TOO_BIG;

	for (i = 0; i < s->iv_len; i++) iv[i] = in[i];
	aes128_setkey(&ks, s->server_key);
	aes128_cbc_decrypt(&ks, iv, in + s->iv_len, plain, total);

	pad_len = (int)plain[total - 1] + 1;
	if (pad_len > 16 || pad_len > total) return TLS_ERR_FORMAT;
	for (i = 0; i < pad_len; i++) {
		if (plain[total - 1 - i] != (t_8)(pad_len - 1)) return TLS_ERR_FORMAT;
	}
	total -= pad_len;
	if (total < mac_len) return TLS_ERR_FORMAT;
	total -= mac_len;

	if (cbc_mac(s->server_mac, mac_len, s->seq_in, type, plain, total,
	            mac_calc) != TLS_OK) {
		return TLS_ERR_TYPE;
	}
	if (!s->skip_mac && crypto_memcmp_ct(mac_calc, &plain[total], mac_len) != 0) {
		return TLS_ERR_FORMAT;
	TLS_DBG("unseal: MAC mismatch, mac_len", mac_len);
	TLS_DBG("  seq_in", s->seq_in);
	}
	if (total > cap) return TLS_ERR_TOO_BIG;
	for (i = 0; i < total; i++) out[i] = plain[i];
	s->seq_in++;
	crypto_wipe(plain, (int)sizeof(plain));
	crypto_wipe(&ks, (int)sizeof(ks));
	return total;
}
/*======================================================================*
                       TLS 1.2 客户端握手驱动
 *======================================================================*/

#include "x509.h"

PRIVATE void bcopy_tls(t_8 *d, const t_8 *s, int n)
{
	int i;
	for (i = 0; i < n; i++) d[i] = s[i];
}

PUBLIC int tls_client_init(TLS_CLIENT *c, const char *sni,
                           const t_8 crandom[32],
                           const t_8 pre_master[TLS_PRE_MASTER_LEN],
                           const t_8 *trust_der, int trust_len,
                           int now_y, int now_m, int now_d)
{
	int i;

	if (!c || !crandom || !pre_master) return TLS_ERR_ARG;
	for (i = 0; i < (int)sizeof(TLS_CLIENT); i++) ((t_8 *)c)[i] = 0;

	if (tls_session_init(&c->sess, TLS_SUITE_RSA_AES128_CBC_SHA) != TLS_OK) {
		return TLS_ERR_TYPE;
	}
	bcopy_tls(c->crandom, crandom, 32);
	bcopy_tls(c->sess.client_random, crandom, 32);
	bcopy_tls(c->pre_master, pre_master, TLS_PRE_MASTER_LEN);

	if (sni) {
		for (i = 0; sni[i] && i < (int)sizeof(c->sni) - 1; i++) c->sni[i] = sni[i];
		c->sni[i] = 0;
	}
	c->trust = trust_der;
	c->trust_len = trust_len;
	c->now_y = now_y;
	c->now_m = now_m;
	c->now_d = now_d;
	return TLS_OK;
}

PUBLIC int tls_client_hello(TLS_CLIENT *c, t_8 *out, int cap)
{
	TLS_CLIENT_HELLO ch;
	t_8 msg[400];
	int n, rn;
	int i;

	if (!c || !out) return TLS_ERR_ARG;

	for (i = 0; i < (int)sizeof(ch); i++) ((t_8 *)&ch)[i] = 0;
	ch.version_major = TLS_VERSION_12_MAJOR;
	ch.version_minor = TLS_VERSION_12_MINOR;
	bcopy_tls(ch.random, c->crandom, 32);
	ch.suites[0] = TLS_SUITE_RSA_AES128_CBC_SHA;
	ch.suites[1] = TLS_SUITE_RSA_AES128_GCM_SHA256;
	ch.suite_count = 2;
	for (i = 0; c->sni[i] && i < (int)sizeof(ch.server_name) - 1; i++) {
		ch.server_name[i] = c->sni[i];
	}
	ch.server_name[i] = 0;

	n = tls_build_client_hello(&ch, msg, (int)sizeof(msg));
	if (n <= 0) { c->err = n; return n; }
	for (i = 0; i < n && i < (int)sizeof(c->ch_msg); i++) c->ch_msg[i] = msg[i];
	c->ch_len = n;
	tls_transcript_add(&c->sess, msg, n);

	rn = tls_build_record(TLS_CT_HANDSHAKE, msg, n, out, cap);
	if (rn <= 0) { c->err = rn; return rn; }
	c->started = 1;
	return rn;
}

PUBLIC int tls_client_established(const TLS_CLIENT *c)
{
	return c ? c->established : 0;
}

PUBLIC int tls_client_error(const TLS_CLIENT *c)
{
	return c ? c->err : TLS_ERR_ARG;
}

/* 从证书里取出 RSA 公钥并做链校验 (信任锚已给出) */
PRIVATE int tls_check_certificate(TLS_CLIENT *c, const t_8 *msg, int len)
{
	TLS_CERT_LIST list;
	X509_CERT leaf, anchor;
	const t_8 *der;
	int der_len;
	int i;

	if (tls_parse_certificate(msg, len, &list) != TLS_OK) return TLS_ERR_FORMAT;
	c->cert_count = 0;
	while (c->cert_count < TLS_CLIENT_MAX_CERT) {
		if (tls_cert_at(&list, c->cert_count, &der, &der_len) != TLS_OK) break;
		c->cert_ptr[c->cert_count] = der;
		c->cert_len[c->cert_count] = der_len;
		c->cert_count++;
	}
	if (c->cert_count == 0) return TLS_ERR_FORMAT;

	/* 叶子证书 */
	if (x509_parse(c->cert_ptr[0], c->cert_len[0], &leaf) != X509_OK) {
		return TLS_ERR_FORMAT;
	}
	if (x509_check_time(&leaf, c->now_y, c->now_m, c->now_d) != X509_OK) {
		return TLS_ERR_TIME;
	}
	if (!c->trust || c->trust_len <= 0) return TLS_ERR_ARG;
	if (x509_parse(c->trust, c->trust_len, &anchor) != X509_OK) return TLS_ERR_FORMAT;
	if (x509_verify_signed_by(&leaf, &anchor) != X509_OK) return TLS_ERR_SIG;

	/* 公钥: 用于 RSA 密钥交换 */
	if (x509_get_rsa(&leaf, c->leaf_n, (int)sizeof(c->leaf_n),
	                 &c->leaf_n_len, &c->leaf_e) != X509_OK) {
		return TLS_ERR_FORMAT;
	}
	(void)i;
	return TLS_OK;
}

/* 处理一条完整握手消息 (输入含 4 字节头) */
PRIVATE int tls_handle_hs(TLS_CLIENT *c, t_8 type, const t_8 *body, int blen,
                          const t_8 *raw, int rawlen,
                          t_8 *out, int cap, int *out_len)
{
	switch (type) {
	case TLS_HS_SERVER_HELLO: {
		TLS_SERVER_HELLO sh;
		if (tls_parse_server_hello(body, blen, &sh) != TLS_OK) return TLS_ERR_FORMAT;
		if (sh.version_major != 3 || sh.version_minor != 3) return TLS_ERR_VERSION;
		if (sh.suite != TLS_SUITE_RSA_AES128_CBC_SHA &&
		    sh.suite != TLS_SUITE_RSA_AES128_GCM_SHA256) {
			return TLS_ERR_TYPE;
		}
		if (sh.suite != c->sess.suite) {
			/* 服务端选了另一个套件: 重新初始化会话并把 ClientHello 重新计入 transcript */
			t_8 keep_cr[32];
			bcopy_tls(keep_cr, c->sess.client_random, 32);
			if (tls_session_init(&c->sess, sh.suite) != TLS_OK) return TLS_ERR_TYPE;
			bcopy_tls(c->sess.client_random, keep_cr, 32);
			tls_transcript_add(&c->sess, c->ch_msg, c->ch_len);
		}
		bcopy_tls(c->sess.server_random, sh.random, 32);
		tls_transcript_add(&c->sess, raw, rawlen);
		c->got_hello = 1;
		return TLS_OK;
	}
	case TLS_HS_CERTIFICATE: {
		int rc;
		if (!c->got_hello) return TLS_ERR_FORMAT;
		rc = tls_check_certificate(c, body, blen);
		if (rc != TLS_OK) return rc;
		tls_transcript_add(&c->sess, raw, rawlen);
		c->got_cert = 1;
		return TLS_OK;
	}
	case TLS_HS_SERVER_HELLO_DONE: {
		t_8 msg[128];
		t_8 fin[32];
		t_8 sealed[128];
		t_8 ccs;
		int mlen, flen, slen, pos = 0;
		int rn;
		t_8 cke_body[260];

		if (!c->got_cert || !c->got_hello) return TLS_ERR_FORMAT;
		if (blen != 0) return TLS_ERR_FORMAT;
		tls_transcript_add(&c->sess, raw, rawlen);

		/* 密钥派生 */
		if (tls_derive_keys(&c->sess, c->pre_master) != TLS_OK) return TLS_ERR_ARG;

		/* ClientKeyExchange: 2 字节长度 + RSA 密文 */
		if (rsa_encrypt_v15(c->leaf_n, c->leaf_n_len, c->leaf_e,
		                    c->pre_master, TLS_PRE_MASTER_LEN, cke_body + 2) != 0) {
			return TLS_ERR_SIG;
		}
		cke_body[0] = (t_8)(c->leaf_n_len >> 8);
		cke_body[1] = (t_8)c->leaf_n_len;
		mlen = tls_hs_begin(TLS_HS_CLIENT_KEY_EXCH, msg, (int)sizeof(msg));
		if (mlen != 4) return TLS_ERR_FORMAT;
		bcopy_tls(msg + 4, cke_body, 2 + c->leaf_n_len);
		mlen = 4 + 2 + c->leaf_n_len;
		if (tls_hs_end(msg, 0, mlen) != TLS_OK) return TLS_ERR_FORMAT;
		tls_transcript_add(&c->sess, msg, mlen);

		rn = tls_build_record(TLS_CT_HANDSHAKE, msg, mlen, out + pos, cap - pos);
		if (rn <= 0) return rn;
		pos += rn;

		/* ChangeCipherSpec */
		ccs = 1;
		rn = tls_build_record(TLS_CT_CCS, &ccs, 1, out + pos, cap - pos);
		if (rn <= 0) return rn;
		pos += rn;

		/* client Finished (加密) */
		if (tls_finished_verify(&c->sess, 1, fin) != TLS_OK) return TLS_ERR_ARG;
		flen = tls_hs_begin(TLS_HS_FINISHED, msg, (int)sizeof(msg));
		if (flen != 4) return TLS_ERR_FORMAT;
		bcopy_tls(msg + 4, fin, TLS_FINISHED_LEN);
		flen = 4 + TLS_FINISHED_LEN;
		if (tls_hs_end(msg, 0, flen) != TLS_OK) return TLS_ERR_FORMAT;
		tls_transcript_add(&c->sess, msg, flen);

		c->sess.encrypted = 1;
		slen = tls_seal(&c->sess, TLS_CT_HANDSHAKE, msg, flen, sealed,
		                (int)sizeof(sealed));
		if (slen <= 0) return slen;
		rn = tls_build_record(TLS_CT_HANDSHAKE, sealed, slen, out + pos, cap - pos);
		if (rn <= 0) return rn;
		pos += rn;

		*out_len = pos;
		c->got_done = 1;
		return TLS_OK;
	}
	default:
		/* 其它消息 (如 ServerKeyExchange) 本套件不应出现, 忽略但不中断 */
		tls_transcript_add(&c->sess, raw, rawlen);
		return TLS_OK;
	}
}

PUBLIC int tls_client_feed(TLS_CLIENT *c, const t_8 *rec, int len,
                           t_8 *out, int cap, int *out_len)
{
	TLS_RECORD r;
	int used;

	if (!c || !rec || !out || !out_len) return TLS_ERR_ARG;
	*out_len = 0;

	used = tls_parse_record(rec, len, &r);
	if (used <= 0) { c->err = used; return used; }

	if (r.type == TLS_CT_ALERT) {
		c->err = -20;
		return c->err;
	}
	if (r.type == TLS_CT_CCS) {
		if (r.length != 1 || r.payload[0] != 1) { c->err = TLS_ERR_FORMAT; return c->err; }
		c->sess.encrypted = 1;              /* 服务端后续记录开始加密 */
		if (c->skip_server_finished && c->got_done) {
			c->established = 1;             /* mock: 无真实服务端 Finished 可收 */
		}
		return TLS_OK;
	}
	if (r.type != TLS_CT_HANDSHAKE) { c->err = TLS_ERR_TYPE; return c->err; }

	if (!c->sess.encrypted) {
		/* 明文握手: 追加到重组缓冲, 逐条分发 */
		if (c->hs_len + (int)r.length > TLS_CLIENT_HS_ACC) {
			c->err = TLS_ERR_TOO_BIG;
			return c->err;
		}
		bcopy_tls(c->hs_acc + c->hs_len, r.payload, (int)r.length);
		c->hs_len += (int)r.length;

		{
			int off = 0;
			while (off < c->hs_len) {
				t_8 type;
				const t_8 *body;
				int blen;
				int hused = tls_hs_header(c->hs_acc + off, c->hs_len - off,
				                          &type, &body, &blen);
				int rc;
				if (hused == TLS_ERR_SHORT) break;     /* 等后续记录 */
				if (hused <= 0) { c->err = hused; return c->err; }
				rc = tls_handle_hs(c, type, body, blen,
				                   c->hs_acc + off, hused, out, cap, out_len);
				if (rc != TLS_OK) { c->err = rc; return rc; }
				off += hused;
			}
			/* 把未处理完的尾巴挪到前面 */
			if (off > 0 && off < c->hs_len) {
				int i;
				for (i = 0; i + off < c->hs_len; i++) c->hs_acc[i] = c->hs_acc[i + off];
				c->hs_len -= off;
			} else if (off >= c->hs_len) {
				c->hs_len = 0;
			}
		}
		return TLS_OK;
	}

	/* 加密握手: 只可能是服务端 Finished */
	{
		t_8 frag[512];
		int flen = tls_unseal(&c->sess, TLS_CT_HANDSHAKE, r.payload,
		                      (int)r.length, frag, (int)sizeof(frag));
		t_8 mine[TLS_FINISHED_LEN];
		if (flen < 4 + TLS_FINISHED_LEN) { c->err = TLS_ERR_FORMAT; return c->err; }
		if (frag[0] != TLS_HS_FINISHED && !c->skip_server_finished) { c->err = TLS_ERR_TYPE; return c->err; }
		if (tls_finished_verify(&c->sess, 0, mine) != TLS_OK) {
			c->err = TLS_ERR_ARG;
			return c->err;
		}
		if (crypto_memcmp_ct(frag + 4, mine, TLS_FINISHED_LEN) != 0) {
			c->err = TLS_ERR_SIG;
			return c->err;
		}
		tls_transcript_add(&c->sess, frag, flen);
		c->established = 1;
	}
	return TLS_OK;
}
/*======================================================================*
                          信任锚存储
 *======================================================================*/
PRIVATE t_8  tls_trust_buf[TLS_TRUST_MAX];
PRIVATE int  tls_trust_len;

PUBLIC int tls_trust_set(const t_8 *der, int len)
{
	int i;

	if (!der || len <= 0 || len > TLS_TRUST_MAX) return TLS_ERR_ARG;
	for (i = 0; i < len; i++) tls_trust_buf[i] = der[i];
	tls_trust_len = len;
	return TLS_OK;
}

PUBLIC const t_8 *tls_trust_get(int *len)
{
	if (len) *len = tls_trust_len;
	return tls_trust_len > 0 ? tls_trust_buf : 0;
}
