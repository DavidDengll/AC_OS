/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
     tools/tls_test/test_http.c — HTTP/1.1 报文处理测试

  直接 include ../../lib/http.c, 用例全部是手工构造的 RFC 形态报文.
  编译到 hs_test.exe 这个名字是因为这台机器的 Device Guard 只放行已批准路径.

  编译: gcc -I shim -I ../../include -O2 -Wall -o hs_test.exe test_http.c
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include <stdio.h>

#include "type.h"
#include "const.h"
#include "http.h"

#include "../../lib/http.c"

static int g_err;

#define CHECK(cond, msg)                                              \
	do {                                                              \
		if (!(cond)) {                                                \
			printf("  [FAIL] %s (line %d)\n", msg, __LINE__);         \
			g_err++;                                                  \
		}                                                             \
	} while (0)

static int s_len(const char *s) { int n = 0; while (s[n]) n++; return n; }

static int feed(const char *text, HTTP_RESP *r)
{
	return http_parse_head((const t_8 *)text, s_len(text), r);
}

int main(void)
{
	static HTTP_RESP r;
	char val[HTTP_VALUE_MAX];
	int n, consumed;
	static unsigned char out[512];

	printf("=== HTTP/1.1 parser test ===\n");

	/* ---------- 1. 基本 200 + Content-Length ---------- */
	{
		static const char resp[] =
			"HTTP/1.1 200 OK\r\n"
			"Content-Type: text/html; charset=utf-8\r\n"
			"Content-Length: 1234\r\n"
			"Connection: close\r\n"
			"\r\n";
		CHECK(feed(resp, &r) == HTTP_OK, "basic response parses");
		CHECK(r.status == 200, "status 200");
		CHECK(r.http_major == 1 && r.http_minor == 1, "HTTP/1.1");
		CHECK(r.content_length == 1234, "content-length");
		CHECK(r.connection_close == 1, "connection close");
		CHECK(!r.chunked, "not chunked");
		CHECK(r.head_len == (int)(s_len(resp)), "head length");
		CHECK(http_header_get(&r, "content-type", val, sizeof(val)) == 1,
		      "header lookup (lowercase)");
		CHECK(val[0] == 't', "header value");
		CHECK(http_header_get(&r, "CONTENT-LENGTH", val, sizeof(val)) == 1,
		      "header lookup (uppercase)");
		CHECK(val[0] == '1', "content-length value");
		CHECK(http_header_get(&r, "x-missing", val, sizeof(val)) == 0,
		      "missing header returns 0");
		CHECK(r.reason[0] == 'O', "reason phrase");
	}

	/* ---------- 2. 302 重定向 + Location ---------- */
	{
		static const char resp[] =
			"HTTP/1.1 302 Found\r\n"
			"Location: https://example.com/new\r\n"
			"Content-Length: 0\r\n"
			"\r\n";
		CHECK(feed(resp, &r) == HTTP_OK, "redirect parses");
		CHECK(http_status_is_redirect(r.status), "302 is redirect");
		CHECK(!http_status_is_ok(r.status), "302 is not 2xx");
		CHECK(http_header_get(&r, "location", val, sizeof(val)) == 1, "Location found");
		{
			const char *want = "https://example.com/new";
			int i, same = 1;
			for (i = 0; want[i] || val[i]; i++) {
				if (want[i] != val[i]) { same = 0; break; }
			}
			CHECK(same, "Location value");
		}
	}

	/* ---------- 3. chunked ---------- */
	{
		static const char resp[] =
			"HTTP/1.1 200 OK\r\n"
			"Transfer-Encoding: chunked\r\n"
			"\r\n";
		CHECK(feed(resp, &r) == HTTP_OK, "chunked header parses");
		CHECK(r.chunked == 1, "chunked flag");
		CHECK(r.content_length == -1, "no content-length");
	}

	/* ---------- 4. gzip + 大小写混杂 ---------- */
	{
		static const char resp[] =
			"HTTP/1.1 200 OK\r\n"
			"cOnTeNt-EnCoDiNg: gzip\r\n"
			"TrAnSfEr-EnCoDiNg: Chunked\r\n"
			"\r\n";
		CHECK(feed(resp, &r) == HTTP_OK, "mixed case parses");
		CHECK(r.gzip == 1, "gzip detected");
		CHECK(r.chunked == 1, "chunked detected (mixed case)");
	}

	/* ---------- 5. 不完整输入 ---------- */
	{
		static const char partial[] = "HTTP/1.1 200 OK\r\nContent-Le";
		CHECK(feed(partial, &r) == HTTP_ERR_INCOMPLETE, "partial head is incomplete");

		{
			static const char no_blank[] =
				"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n";
			CHECK(feed(no_blank, &r) == HTTP_ERR_INCOMPLETE,
			      "missing final CRLF is incomplete");
		}
	}

	/* ---------- 6. 畸形输入 ---------- */
	{
		static const char bad1[] = "HTTP/1.1 20\r\n\r\n";
		CHECK(feed(bad1, &r) != HTTP_OK, "short status rejected");

		static const char bad2[] = "HTTP/1.1 200 OK\r\nNoColonHere\r\n\r\n";
		CHECK(feed(bad2, &r) == HTTP_ERR_FORMAT, "header without colon rejected");

		static const char bad3[] = "GET / HTTP/1.1\r\n\r\n";
		CHECK(feed(bad3, &r) == HTTP_ERR_FORMAT, "request line is not a response");

		static const char bad4[] = "HTTP/1.1 200 OK\r\nContent-Length: abc\r\n\r\n";
		CHECK(feed(bad4, &r) == HTTP_ERR_FORMAT, "bad content-length rejected");

		static const char bad5[] = "HTTP/1.1 999 Nope\r\n\r\n";
		CHECK(feed(bad5, &r) == HTTP_ERR_FORMAT, "status 999 rejected");
	}

	/* ---------- 7. 请求构造 ---------- */
	{
		static const char want[] =
			"GET /index.htm HTTP/1.1\r\n"
			"Host: catos.test\r\n"
			"User-Agent: CatOS-Browser/1.0\r\n"
			"Accept: text/html,*/*\r\n"
			"Accept-Encoding: identity\r\n"
			"Connection: close\r\n"
			"\r\n";
		n = http_build_get("catos.test", "/index.htm", 0, out, (int)sizeof(out));
		CHECK(n == (int)(s_len(want)), "request length");
		if (n == (int)s_len(want)) {
			int i, same = 1;
			for (i = 0; i < n; i++) {
				if (out[i] != (t_8)want[i]) { same = 0; break; }
			}
			CHECK(same, "request bytes");
		}
		CHECK(http_build_get("catos.test", "index.htm", 0, out, (int)sizeof(out))
		      == HTTP_ERR_ARG, "path without leading slash rejected");
		CHECK(http_build_get(0, "/", 0, out, (int)sizeof(out)) == HTTP_ERR_ARG,
		      "NULL host rejected");
		CHECK(http_build_get("catos.test", "/x", 0, out, 8) == HTTP_ERR_TOO_BIG,
		      "tiny buffer rejected");
		/* keep-alive 版本 */
		n = http_build_get("h", "/", 1, out, (int)sizeof(out));
		CHECK(n > 0, "keep-alive request built");
	}

	/* ---------- 8. chunked 解码 ---------- */
	{
		static const char body[] =
			"4\r\nWiki\r\n"
			"5;ext=1\r\npedia\r\n"
			"0\r\n\r\n";
		n = http_chunk_decode((const t_8 *)body, (int)s_len(body), out,
		                      (int)sizeof(out), &consumed);
		CHECK(n == 9, "chunked decodes to 9 bytes");
		CHECK(consumed == (int)s_len(body), "chunked consumes whole input");
		CHECK(out[0] == 'W' && out[4] == 'p' && out[8] == 'a', "chunked body bytes");

		/* trailer 版本 */
		{
			static const char body2[] = "3\r\nabc\r\n0\r\nX-Trailer: 1\r\n\r\n";
			n = http_chunk_decode((const t_8 *)body2, (int)s_len(body2), out,
			                      (int)sizeof(out), &consumed);
			CHECK(n == 3, "chunked with trailer decodes");
			CHECK(consumed == (int)s_len(body2), "trailer consumed");
		}

		/* 分片喂入: 先给一半, 应该 INCOMPLETE 且告知已消耗 */
		{
			static const char body3[] = "10\r\n0123456789abcdef\r\n0\r\n\r\n";
			int half = 12;                      /* 长度行 + 部分数据 */
			n = http_chunk_decode((const t_8 *)body3, half, out,
			                      (int)sizeof(out), &consumed);
			CHECK(n == HTTP_ERR_INCOMPLETE, "partial chunk is incomplete");
			CHECK(consumed == 4, "consumed up to end of size line");
			n = http_chunk_decode((const t_8 *)body3, (int)s_len(body3), out,
			                      (int)sizeof(out), &consumed);
			CHECK(n == 16, "full chunk decodes after retry");
		}

		/* 畸形 chunk */
		CHECK(http_chunk_decode((const t_8 *)"zz\r\n", 4, out, (int)sizeof(out),
		                        &consumed) == HTTP_ERR_FORMAT,
		      "bad chunk size rejected");
		CHECK(http_chunk_decode((const t_8 *)"10\r\nabc\r\n", 10, out,
		                        (int)sizeof(out), &consumed) == HTTP_ERR_INCOMPLETE,
		      "chunk smaller than declared is incomplete");
		CHECK(http_chunk_decode((const t_8 *)"10\r\n0123456789abcdefXX", 22, out,
		                        (int)sizeof(out), &consumed) == HTTP_ERR_FORMAT,
		      "missing chunk terminator rejected");
		CHECK(http_chunk_decode((const t_8 *)"4\r\nWiki\r\n", 10, out, 2,
		                        &consumed) == HTTP_ERR_TOO_BIG,
		      "output buffer too small rejected");
	}

	printf("=== %s: %d failure(s) ===\n", g_err ? "FAILED" : "ALL PASSED", g_err);
	return g_err ? 1 : 0;
}
