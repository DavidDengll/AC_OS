/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              tls.h
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                CatOS 内核 TLS 1.2 记录层 / 握手消息编解码

  范围 (本阶段):
    - 记录层: 5 字节头 (type, version, length) 的解析与生成
    - 握手消息: 4 字节头 (type, length24) 的读写
    - ClientHello 生成 (含 SNI 扩展)
    - ServerHello / Certificate / ServerHelloDone 解析
  尚未包含 (下一阶段):
    - 握手状态机 (ChangeCipherSpec / Finished / 密钥派生)
    - 记录加密 (AES-CBC + HMAC / AES-GCM)
    - ECDHE、X.509 证书链校验

  设计约束 (内核态):
    - 无动态分配; 所有输出写入调用者提供的缓冲区, 全部长度参数做边界检查
    - 解析函数只读取输入, 不修改; 越界/截断一律返回负错误码

  验证: tools/tls_test/ 用 Python 独立实现记录封装, 双向比对
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#ifndef _CATOS_TLS_H_
#define _CATOS_TLS_H_

#include "type.h"

/* ===== 记录层内容类型 ===== */
#define TLS_CT_CCS           20
#define TLS_CT_ALERT         21
#define TLS_CT_HANDSHAKE     22
#define TLS_CT_APPDATA       23

/* ===== 握手消息类型 ===== */
#define TLS_HS_CLIENT_HELLO       1
#define TLS_HS_SERVER_HELLO       2
#define TLS_HS_CERTIFICATE       11
#define TLS_HS_SERVER_KEY_EXCH   12
#define TLS_HS_CERT_REQUEST      13
#define TLS_HS_SERVER_HELLO_DONE 14
#define TLS_HS_CLIENT_KEY_EXCH   16
#define TLS_HS_FINISHED          20

/* ===== 版本 / 套件 ===== */
#define TLS_VERSION_12_MAJOR   3
#define TLS_VERSION_12_MINOR   3
#define TLS_SUITE_RSA_AES128_CBC_SHA   0x002F
#define TLS_SUITE_RSA_AES128_GCM_SHA256 0x009C

#define TLS_RECORD_MAX      16384      /* 协议上限 */
#define TLS_HANDSHAKE_MAX   12288      /* 我们的手缓冲上限 */

/* ===== 错误码 ===== */
#define TLS_OK              0
#define TLS_ERR_ARG        -1
#define TLS_ERR_SHORT      -2          /* 数据不足 */
#define TLS_ERR_VERSION    -3
#define TLS_ERR_TOO_BIG    -4
#define TLS_ERR_TYPE       -5
#define TLS_ERR_FORMAT     -6
#define TLS_ERR_TIME       -7            /* 证书过期/未生效 */
#define TLS_ERR_SIG        -8            /* 签名/Finished 校验失败 */

/* 一条记录 (payload 指向输入缓冲区内部, 不拷贝) */
typedef struct {
	t_8        type;
	t_8        major;
	t_8        minor;
	t_16       length;
	const t_8 *payload;
} TLS_RECORD;

/* ClientHello 参数 */
#define TLS_MAX_SUITES      8

typedef struct {
	t_8   version_major;
	t_8   version_minor;
	t_8   random[32];              /* 由调用者填入 (随机源) */
	t_16  suites[TLS_MAX_SUITES];
	int   suite_count;
	char  server_name[64];         /* 非空则带 SNI 扩展 */
} TLS_CLIENT_HELLO;

/* ServerHello 解析结果 */
typedef struct {
	t_8  version_major;
	t_8  version_minor;
	t_8  random[32];
	t_16 suite;
	t_8  compression;
	int  session_id_len;
	t_8  session_id[32];
	int  extensions_len;           /* 跳过的扩展总长 */
} TLS_SERVER_HELLO;

/* 证书列表 (指针指向输入) */
typedef struct {
	const t_8 *data;               /* 3 字节总长之后的证书列表起点 */
	int        length;             /* 列表总长 */
} TLS_CERT_LIST;

/* ===== 记录层 ===== */
/* 解析一条记录. 返回消耗的字节数 (>0), 或 TLS_ERR_* */
PUBLIC int tls_parse_record(const t_8 *buf, int len, TLS_RECORD *rec);
/* 生成一条记录到 out. 返回写入长度, 或 TLS_ERR_* */
PUBLIC int tls_build_record(t_8 type, const t_8 *payload, int len,
                            t_8 *out, int cap);

/* ===== 握手消息头 ===== */
/* 写 4 字节头 (type + 3 字节长度占位), 返回头长 (4) */
PUBLIC int tls_hs_begin(t_8 type, t_8 *out, int cap);
/* 回填长度 (off 为消息起始, total 为含头总长). 返回 TLS_OK */
PUBLIC int tls_hs_end(t_8 *out, int off, int total);

/* ===== ClientHello ===== */
/* 生成握手消息 (含 4 字节头). 返回消息总长, 或 TLS_ERR_* */
PUBLIC int tls_build_client_hello(const TLS_CLIENT_HELLO *ch, t_8 *out, int cap);

/* ===== 服务端消息解析 (输入为握手消息体, 不含 4 字节头) ===== */
PUBLIC int tls_parse_server_hello(const t_8 *msg, int len, TLS_SERVER_HELLO *sh);
PUBLIC int tls_parse_certificate(const t_8 *msg, int len, TLS_CERT_LIST *list);
/* 取第 idx 个证书; 返回 TLS_OK 或错误码 */
PUBLIC int tls_cert_at(const TLS_CERT_LIST *list, int idx,
                       const t_8 **cert, int *cert_len);
/* ServerHelloDone 校验 (必须为空) */
PUBLIC int tls_parse_server_hello_done(const t_8 *msg, int len);

/* 握手消息头解析: 返回消息类型, *body 指向消息体, *body_len 为消息体长;
 * 返回消耗字节数 (4+body_len), 或错误码 */
PUBLIC int tls_hs_header(const t_8 *buf, int len, t_8 *type,
                         const t_8 **body, int *body_len);

/* ==================================================================
   TLS 1.2 会话: 密钥派生 + Finished + 记录加解密 (仅 CBC-SHA 套件)
   已支持: TLS_RSA_WITH_AES_128_CBC_SHA (0x002F)
   后续:   AES-GCM (0x009C) / ECDHE
   ================================================================== */
#include "crypto.h"

#define TLS_PRE_MASTER_LEN   48
#define TLS_MASTER_LEN       48
#define TLS_FINISHED_LEN     12
#define TLS_MAX_MAC          32
#define TLS_MAX_KEY          32
#define TLS_MAX_IV           16
#define TLS_MAX_KEYBLOCK     (2 * (TLS_MAX_MAC + TLS_MAX_KEY + TLS_MAX_IV))

typedef struct {
	t_16 suite;
	int  mac_len;                  /* 每方向 MAC 密钥长度 */
	int  enc_len;                  /* 每方向加密密钥长度 */
	int  iv_len;                   /* 每方向 IV 长度 */

	t_8  client_random[32];
	t_8  server_random[32];
	t_8  master_secret[TLS_MASTER_LEN];

	t_8  client_mac[TLS_MAX_MAC];
	t_8  server_mac[TLS_MAX_MAC];
	t_8  client_key[TLS_MAX_KEY];
	t_8  server_key[TLS_MAX_KEY];
	t_8  client_iv[TLS_MAX_IV];
	t_8  server_iv[TLS_MAX_IV];

	t_32 seq_out;                  /* 发送序号 (64 位计数, 高 32 位恒 0) */
	t_32 seq_in;                   /* 接收序号 */
	int  encrypted;                /* 1 = 记录已启用加密 */
	int  skip_mac;                 /* 1 = 跳过 MAC/tag 校验 (仅 mock 用) */

	SHA256_CTX transcript;         /* 握手消息累积哈希 */
} TLS_SESSION;

/* 初始化会话 (只支持 0x002F; 其它套件返回 TLS_ERR_TYPE) */
PUBLIC int tls_session_init(TLS_SESSION *s, t_16 suite);
/* 累积一条握手消息 (含 4 字节握手头) 到 transcript */
PUBLIC void tls_transcript_add(TLS_SESSION *s, const t_8 *msg, int len);
/* 由 pre-master 派生 master secret 与密钥块; 需要 client/server random 已填 */
PUBLIC int tls_derive_keys(TLS_SESSION *s, const t_8 pre_master[TLS_PRE_MASTER_LEN]);
/* Finished 的 verify_data (12 字节); is_client=1 用 "client finished" */
PUBLIC int tls_finished_verify(TLS_SESSION *s, int is_client, t_8 out[TLS_FINISHED_LEN]);
/* 加密: in 为明文片段, out 为记录负载 (显式 IV || 密文). 返回负载长度 */
PUBLIC int tls_seal(TLS_SESSION *s, t_8 type, const t_8 *in, int len,
                    t_8 *out, int cap);
/* 解密: in 为记录负载 (显式 IV || 密文), out 为明文片段. 返回片段长度 */
PUBLIC int tls_unseal(TLS_SESSION *s, t_8 type, const t_8 *in, int len,
                      t_8 *out, int cap);
/* ==================================================================
   TLS 1.2 客户端握手驱动 (字节进 / 字节出, 不做任何 I/O)
   - tls_client_hello(): 生成 ClientHello 记录
   - tls_client_feed(): 输入一条服务端记录 (含 5 字节记录头),
                        可能输出 0..N 条客户端记录 (ClientKeyExchange / CCS / Finished)
   - 支持握手消息跨记录分片与多条消息共用一条记录
   - Certificate 消息到达时用调用者传入的信任锚做链校验
   - Alert 记录一律按错误处理
   ================================================================== */

#define TLS_CLIENT_HS_ACC   4096        /* 握手重组缓冲 */
#define TLS_CLIENT_MAX_CERT 4

typedef struct {
	TLS_SESSION sess;

	const t_8 *trust;                  /* 信任锚 (DER) */
	int        trust_len;
	int        now_y, now_m, now_d;    /* 用于证书有效期检查 */

	char       sni[64];
	t_8        pre_master[TLS_PRE_MASTER_LEN];
	t_8        crandom[32];

	int        started;                /* ClientHello 已发出 */
	int        skip_server_finished;   /* 1 = 收到加密记录即视为 established (mock 用) */
	int        got_hello, got_cert, got_done;
	int        established;            /* 服务端 Finished 已验证 */
	int        err;                    /* 最近一次错误码 */

	int        cert_count;
	const t_8 *cert_ptr[TLS_CLIENT_MAX_CERT];
	int        cert_len[TLS_CLIENT_MAX_CERT];
	t_8        leaf_n[256];
	int        leaf_n_len;
	t_32       leaf_e;

	t_8        ch_msg[400];            /* ClientHello 握手消息 (切换套件后重放) */
	int        ch_len;
	t_8        hs_acc[TLS_CLIENT_HS_ACC];
	int        hs_len;
} TLS_CLIENT;

/* 初始化: 固定 random 与 pre-master 由调用者提供 (内核里来自随机源) */
PUBLIC int tls_client_init(TLS_CLIENT *c, const char *sni,
                           const t_8 crandom[32],
                           const t_8 pre_master[TLS_PRE_MASTER_LEN],
                           const t_8 *trust_der, int trust_len,
                           int now_y, int now_m, int now_d);
/* 生成 ClientHello 记录到 out, 返回记录长度 */
PUBLIC int tls_client_hello(TLS_CLIENT *c, t_8 *out, int cap);
/* 处理一条服务端记录; out/out_len 接收客户端要发送的记录 (可为 0 条) */
PUBLIC int tls_client_feed(TLS_CLIENT *c, const t_8 *rec, int len,
                           t_8 *out, int cap, int *out_len);
PUBLIC int tls_client_established(const TLS_CLIENT *c);
PUBLIC int tls_client_error(const TLS_CLIENT *c);

/* ===== 信任锚存储 (内核里放一张根证书 DER) =====
 * 真实部署应放多个根 / 由用户导入; 这里先提供单一锚的最小实现. */
#define TLS_TRUST_MAX 2048
PUBLIC int  tls_trust_set(const t_8 *der, int len);      /* 0=成功 */
PUBLIC const t_8 *tls_trust_get(int *len);               /* 0=未设置 */
#endif /* _CATOS_TLS_H_ */
