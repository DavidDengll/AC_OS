/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              http.h
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                   CatOS 内置浏览器 — HTTP/1.1 报文处理

  范围 (只做客户端需要的部分):
    - 解析响应状态行 + 头部 (大小写不敏感的名字匹配)
    - Content-Length / Transfer-Encoding: chunked / Connection: close
    - 构造请求 (GET, HTTP/1.1, Host/UA/Connection/Accept-Encoding)
    - chunked 解码 (支持分片喂入与 trailer)
  不做: HTTP/2 / gzip 解压 / 缓存 / 认证 / multipart

  约束: 无动态分配; 输入只读; 所有长度做边界检查
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#ifndef _CATOS_HTTP_H_
#define _CATOS_HTTP_H_

#include "type.h"

#define HTTP_OK              0
#define HTTP_ERR_ARG        -1
#define HTTP_ERR_INCOMPLETE -2       /* 数据还没收全, 需要继续读 */
#define HTTP_ERR_FORMAT     -3
#define HTTP_ERR_TOO_BIG    -4

#define HTTP_REASON_MAX     40
#define HTTP_VALUE_MAX      96

typedef struct {
	int        status;                  /* 200 / 301 / 404 ... */
	char       reason[HTTP_REASON_MAX];
	int        http_major;              /* 1 */
	int        http_minor;              /* 0 或 1 */
	int        content_length;          /* -1 = 未给出 */
	int        chunked;                 /* 1 = chunked 传输 */
	int        connection_close;        /* 1 = 连接将关闭 */
	int        gzip;                    /* 1 = Content-Encoding 含 gzip */
	int        head_len;                /* 头部总长 (含结尾空行) */
	const t_8 *raw;                     /* 原始头部 (指向输入缓冲) */
	int        raw_len;
} HTTP_RESP;

/* 解析响应头. 返回 HTTP_OK / HTTP_ERR_INCOMPLETE / HTTP_ERR_* */
PUBLIC int http_parse_head(const t_8 *buf, int len, HTTP_RESP *out);

/* 取某个头部的值 (名字大小写不敏感). 返回 1=找到, 0=没有 */
PUBLIC int http_header_get(const HTTP_RESP *r, const char *name,
                           char *val, int max);

/* 构造 GET 请求. 返回长度, <0 错误 */
PUBLIC int http_build_get(const char *host, const char *path,
                          int keep_alive, t_8 *out, int cap);

/* chunked 解码: 把已收到的字节解成正文.
 * *consumed 返回消耗的输入字节数; 返回解码出的字节数, 或 HTTP_ERR_INCOMPLETE
 * (此时 *consumed 是已安全消耗的字节数, 调用者应保留剩余部分) */
PUBLIC int http_chunk_decode(const t_8 *in, int len, t_8 *out, int cap,
                             int *consumed);

/* 状态码分类 */
PUBLIC int http_status_is_redirect(int status);
PUBLIC int http_status_is_ok(int status);

#endif /* _CATOS_HTTP_H_ */
