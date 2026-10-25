/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              http.c
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                CatOS 内置浏览器 — HTTP/1.1 客户端报文处理

  设计:
    - 头部解析一次扫完, 只记录我们需要的那几个字段; http_header_get 再按需扫描
    - 任何一行超过内部缓冲或没有 CRLF 都报错, 绝不越界
    - chunked 解码是"可续传"的: 半条 chunk 到达时返回 INCOMPLETE 并告知
      已经安全消耗了多少字节, 调用者把剩余部分留给下次
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include "type.h"
#include "const.h"
#include "http.h"

/*======================================================================*
                          小工具
 *======================================================================*/

PRIVATE char h_lower(char c)
{
	if (c >= 'A' && c <= 'Z') return (char)(c + 32);
	return c;
}

PRIVATE void h_copy(char *d, const t_8 *s, int n, int max)
{
	int i;
	if (max <= 0) return;
	for (i = 0; i < n && i < max - 1; i++) d[i] = (char)s[i];
	d[i] = 0;
}

/* 忽略大小写比较 (长度 len 的前缀 vs name) */
PRIVATE int h_ieq(const char *a, const char *b)
{
	int i = 0;
	while (a[i] && b[i]) {
		if (h_lower(a[i]) != h_lower(b[i])) return 0;
		i++;
	}
	return a[i] == b[i];
}

/* 在 [p, end) 里找 "\r\n"; 返回换行位置, 0=没找到 */
PRIVATE const t_8 *find_crlf(const t_8 *p, const t_8 *end)
{
	while (p + 1 < end) {
		if (p[0] == '\r' && p[1] == '\n') return p;
		p++;
	}
	return 0;
}

PRIVATE int parse_int(const t_8 *p, const t_8 *end, int *out)
{
	int v = 0;
	int digits = 0;

	while (p < end && *p == ' ') p++;
	while (p < end && *p >= '0' && *p <= '9') {
		if (v > 100000000) return HTTP_ERR_TOO_BIG;
		v = v * 10 + (*p - '0');
		p++;
		digits++;
	}
	if (digits == 0) return HTTP_ERR_FORMAT;
	*out = v;
	return HTTP_OK;
}

/*======================================================================*
                          状态行 / 头部
 *======================================================================*/

PUBLIC int http_parse_head(const t_8 *buf, int len, HTTP_RESP *out)
{
	const t_8 *p;
	const t_8 *end;

	if (!buf || !out || len <= 0) return HTTP_ERR_ARG;

	/* 清零输出 */
	{
		int i;
		for (i = 0; i < (int)sizeof(HTTP_RESP); i++) ((t_8 *)out)[i] = 0;
	}
	out->content_length = -1;
	out->http_major = 1;
	out->http_minor = 1;

	p = buf;
	end = buf + len;

	/* ---- 状态行: "HTTP/1.1 200 OK" ---- */
	{
		const t_8 *eol = find_crlf(p, end);
		const t_8 *q;

		if (!eol) return HTTP_ERR_INCOMPLETE;
		if (eol - p < 12) return HTTP_ERR_FORMAT;
		if (!(p[0] == 'H' && p[1] == 'T' && p[2] == 'T' && p[3] == 'P' &&
		      p[4] == '/')) {
			return HTTP_ERR_FORMAT;
		}
		q = p + 5;
		if (*q < '0' || *q > '9') return HTTP_ERR_FORMAT;
		out->http_major = *q - '0';
		q++;
		if (q >= eol || *q != '.') return HTTP_ERR_FORMAT;
		q++;
		if (q >= eol || *q < '0' || *q > '9') return HTTP_ERR_FORMAT;
		out->http_minor = *q - '0';
		q++;
		if (q >= eol || *q != ' ') return HTTP_ERR_FORMAT;
		q++;
		if (parse_int(q, eol, &out->status) != HTTP_OK) return HTTP_ERR_FORMAT;
		if (out->status < 100 || out->status > 599) return HTTP_ERR_FORMAT;

		/* reason phrase */
		{
			const t_8 *r = q;
			while (r < eol && *r != ' ') r++;
			while (r < eol && *r == ' ') r++;
			h_copy(out->reason, r, (int)(eol - r), HTTP_REASON_MAX);
		}
		p = eol + 2;
	}

	/* ---- 头部行 ---- */
	while (1) {
		const t_8 *eol = find_crlf(p, end);
		const t_8 *colon;
		char name[32];
		int nlen;

		if (!eol) return HTTP_ERR_INCOMPLETE;
		if (eol == p) {                       /* 空行: 头部结束 */
			p += 2;
			break;
		}
		colon = p;
		while (colon < eol && *colon != ':') colon++;
		if (colon >= eol) return HTTP_ERR_FORMAT;   /* 没有冒号 */
		nlen = (int)(colon - p);
		if (nlen <= 0 || nlen >= (int)sizeof(name)) return HTTP_ERR_FORMAT;
		h_copy(name, p, nlen, (int)sizeof(name));

		{
			const t_8 *v = colon + 1;
			const t_8 *vend = eol;
			int vlen;

			while (v < vend && *v == ' ') v++;
			while (vend > v && (vend[-1] == ' ' || vend[-1] == '\t')) vend--;
			vlen = (int)(vend - v);

			if (h_ieq(name, "content-length")) {
				int cl = 0;
				if (parse_int(v, vend, &cl) != HTTP_OK) return HTTP_ERR_FORMAT;
				out->content_length = cl;
			} else if (h_ieq(name, "transfer-encoding")) {
				/* 只要出现 chunked (大小写不敏感) 就按 chunked 处理 */
				int i;
				for (i = 0; i + 7 <= vlen; i++) {
					char w[8];
					h_copy(w, v + i, 7, (int)sizeof(w));
					if (h_ieq(w, "chunked")) { out->chunked = 1; break; }
				}
			} else if (h_ieq(name, "connection")) {
				int i;
				for (i = 0; i + 5 <= vlen; i++) {
					char w[8];
					h_copy(w, v + i, 5, (int)sizeof(w));
					if (h_ieq(w, "close")) { out->connection_close = 1; break; }
				}
			} else if (h_ieq(name, "content-encoding")) {
				int i;
				for (i = 0; i + 4 <= vlen; i++) {
					char w[8];
					h_copy(w, v + i, 4, (int)sizeof(w));
					if (h_ieq(w, "gzip")) { out->gzip = 1; break; }
				}
			}
		}
		p = eol + 2;
	}

	out->head_len = (int)(p - buf);
	out->raw = buf;
	out->raw_len = out->head_len;
	return HTTP_OK;
}

PUBLIC int http_header_get(const HTTP_RESP *r, const char *name,
                           char *val, int max)
{
	const t_8 *p;
	const t_8 *end;

	if (!r || !name || !val || max <= 0) return 0;
	val[0] = 0;
	if (!r->raw || r->raw_len <= 0) return 0;

	p = r->raw;
	end = r->raw + r->raw_len;

	/* 跳过状态行 */
	{
		const t_8 *eol = find_crlf(p, end);
		if (!eol) return 0;
		p = eol + 2;
	}
	while (p + 1 < end) {
		const t_8 *eol = find_crlf(p, end);
		const t_8 *colon;
		char hname[32];
		int nlen;

		if (!eol) return 0;
		if (eol == p) return 0;                   /* 头部结束 */
		colon = p;
		while (colon < eol && *colon != ':') colon++;
		if (colon >= eol) return 0;
		nlen = (int)(colon - p);
		if (nlen <= 0 || nlen >= (int)sizeof(hname)) return 0;
		h_copy(hname, p, nlen, (int)sizeof(hname));
		if (h_ieq(hname, name)) {
			const t_8 *v = colon + 1;
			const t_8 *vend = eol;
			while (v < vend && *v == ' ') v++;
			while (vend > v && (vend[-1] == ' ' || vend[-1] == '\t')) vend--;
			h_copy(val, v, (int)(vend - v), max);
			return 1;
		}
		p = eol + 2;
	}
	return 0;
}

/*======================================================================*
                          请求构造
 *======================================================================*/

PUBLIC int http_build_get(const char *host, const char *path,
                          int keep_alive, t_8 *out, int cap)
{
	int pos = 0;
	const char *parts[8];
	int i;

	if (!host || !path || !out || cap <= 0) return HTTP_ERR_ARG;
	if (!*host || !*path || path[0] != '/') return HTTP_ERR_ARG;

	parts[0] = "GET ";
	parts[1] = path;
	parts[2] = " HTTP/1.1\r\nHost: ";
	parts[3] = host;
	parts[4] = "\r\nUser-Agent: CatOS-Browser/1.0\r\nAccept: text/html,*/*\r\n"
	           "Accept-Encoding: identity\r\nConnection: ";
	parts[5] = keep_alive ? "keep-alive" : "close";
	parts[6] = "\r\n\r\n";
	parts[7] = 0;

	for (i = 0; parts[i]; i++) {
		const char *s = parts[i];
		while (*s) {
			if (pos >= cap) return HTTP_ERR_TOO_BIG;
			out[pos++] = (t_8)*s++;
		}
	}
	return pos;
}

/*======================================================================*
                          chunked 解码
 *======================================================================*/

PUBLIC int http_chunk_decode(const t_8 *in, int len, t_8 *out, int cap,
                             int *consumed)
{
	int ip = 0;
	int op = 0;

	if (!in || !out || !consumed || len < 0 || cap < 0) return HTTP_ERR_ARG;
	*consumed = 0;

	while (1) {
		int size = 0;
		int digits = 0;
		const t_8 *line;
		const t_8 *eol;

		/* ---- chunk 长度行 ---- */
		line = in + ip;
		eol = find_crlf(line, in + len);
		if (!eol) { *consumed = ip; return HTTP_ERR_INCOMPLETE; }

		{
			const t_8 *q = line;
			while (q < eol && *q != ';') {           /* 忽略 chunk extension */
				int d;
				if (*q >= '0' && *q <= '9') d = *q - '0';
				else if (*q >= 'a' && *q <= 'f') d = *q - 'a' + 10;
				else if (*q >= 'A' && *q <= 'F') d = *q - 'A' + 10;
				else if (*q == ' ' || *q == '\t') { q++; continue; }
				else return HTTP_ERR_FORMAT;
				if (size > 0x10000000) return HTTP_ERR_TOO_BIG;
				size = size * 16 + d;
				digits++;
				q++;
			}
		}
		if (digits == 0) return HTTP_ERR_FORMAT;
		ip = (int)(eol + 2 - in);

		if (size == 0) {
			/* ---- trailer (可选) 到空行结束 ---- */
			while (1) {
				const t_8 *t = in + ip;
				const t_8 *te = find_crlf(t, in + len);
				if (!te) { *consumed = ip; return HTTP_ERR_INCOMPLETE; }
				ip = (int)(te + 2 - in);
				if (te == t) { *consumed = ip; return op; }   /* 结束 */
			}
		}

		if (size > cap - op) return HTTP_ERR_TOO_BIG;
		if (ip + size + 2 > len) {                    /* 数据还没到齐 */
			*consumed = ip;
			return HTTP_ERR_INCOMPLETE;
		}
		{
			int i;
			for (i = 0; i < size; i++) out[op + i] = in[ip + i];
			op += size;
		}
		ip += size;
		if (in[ip] != '\r' || in[ip + 1] != '\n') return HTTP_ERR_FORMAT;
		ip += 2;
	}
}

/*======================================================================*
                          状态码分类
 *======================================================================*/

PUBLIC int http_status_is_redirect(int status)
{
	return (status == 301 || status == 302 || status == 303 ||
	        status == 307 || status == 308) ? 1 : 0;
}

PUBLIC int http_status_is_ok(int status)
{
	return (status >= 200 && status < 300) ? 1 : 0;
}
