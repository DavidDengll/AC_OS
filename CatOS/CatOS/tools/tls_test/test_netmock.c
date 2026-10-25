/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
     tools/tls_test/test_netmock.c — netmock 的 TLS+HTTP 层宿主侧测试

  只测 netmock_fetch() 的解密与 HTTP 解析 (不 include browser.c,
  因为浏览器渲染层依赖内核头, 已由 selftest.exe 单独覆盖).

  编译: gcc -I shim -I ../../include -O2 -o nm_check.exe test_netmock.c
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include <stdio.h>

#include "type.h"
#include "const.h"
#include "netmock.h"
#include "tls.h"
#include "http.h"

#include "../../lib/crypto.c"
#include "../../lib/rsa.c"
#include "../../lib/x509.c"
#include "../../lib/http.c"
#include "../../lib/tls.c"
#include "../../kernel/netmock.c"

static int g_err;

#define CHECK(cond, msg)                                              \
	do {                                                              \
		if (!(cond)) {                                                \
			printf("  [FAIL] %s (line %d)\n", msg, __LINE__);         \
			g_err++;                                                  \
		}                                                             \
	} while (0)

static char g_last_stage[40];

static void nm_progress(int stage, const char *detail)
{
	const char *s;
	switch (stage) {
	case NETMOCK_ST_CONNECTING:    s = "Connecting...";    break;
	case NETMOCK_ST_TLS_HANDSHAKE: s = "TLS Handshake..."; break;
	case NETMOCK_ST_DECRYPTING:    s = "Decrypting...";    break;
	case NETMOCK_ST_DONE:          s = "Done";             break;
	default:                       s = "ERROR";            break;
	}
	printf("  [%s]\n", s);
	{
		int k = 0;
		for (; s[k] && k < 39; k++) g_last_stage[k] = s[k];
		g_last_stage[k] = 0;
	}
	(void)detail;
}

int main(void)
{
	static char html[16384];
	HTTP_RESP resp;
	int n;

	printf("=== netmock TLS+HTTP pipeline test ===\n");

	/* ---------- 1. fetch ---------- */
	n = netmock_fetch("https://mock.catos.test/", nm_progress,
	                  (t_8 *)html, (int)sizeof(html));
	CHECK(n > 0, "netmock_fetch returned body");
	CHECK(n < (int)sizeof(html), "body fits");

	/* ---------- 2. 进度阶段覆盖 ---------- */
	CHECK(g_last_stage[0] == 'D', "last stage is Done");

	/* ---------- 3. HTTP 响应解析 ---------- */
	{
		int rc = http_parse_head((const t_8 *)html, n, &resp);
		CHECK(rc == HTTP_OK, "HTTP head parses");
		CHECK(resp.status == 200, "status 200");
		CHECK(resp.http_minor == 1, "HTTP/1.1");
		if (rc == HTTP_OK) {
			char val[HTTP_VALUE_MAX];
			CHECK(http_header_get(&resp, "content-type", val, sizeof(val)) == 1,
			      "content-type header present");
			CHECK(resp.content_length > 0 || resp.chunked,
			      "body length known or chunked");
		}
	}

	/* ---------- 4. 正文内容 (真 TLS 解密产物) ---------- */
	{
		const char *body = (const char *)html + resp.head_len;
		int blen = n - resp.head_len;
		int has_html = 0, has_h1 = 0, has_font = 0, has_li = 0, has_img = 0;
		int i;
		for (i = 0; i + 5 < blen; i++) {
			if (body[i] == '<' && body[i+1] == 'h' && body[i+2] == 't' &&
			    body[i+3] == 'm' && body[i+4] == 'l') has_html = 1;
			if (body[i] == '<' && body[i+1] == 'h' && body[i+2] == '1') has_h1 = 1;
			if (body[i] == '<' && body[i+1] == 'f' && body[i+2] == 'o' &&
			    body[i+3] == 'n' && body[i+4] == 't') has_font = 1;
			if (body[i] == '<' && body[i+1] == 'l' && body[i+2] == 'i') has_li = 1;
			if (body[i] == '<' && body[i+1] == 'i' && body[i+2] == 'm' &&
			    body[i+3] == 'g') has_img = 1;
		}
		CHECK(has_html, "body starts with <html>");
		CHECK(has_h1, "body has <h1>");
		CHECK(has_font, "body has <font color>");
		CHECK(has_li, "body has <li>");
		CHECK(has_img, "body has <img>");
		(void)body;
	}

	/* ---------- 5. 幂等性: 连续两次 fetch 结果一致 ---------- */
	{
		static char html2[16384];
		int n2 = netmock_fetch("https://mock.catos.test/x", 0,
		                       (t_8 *)html2, (int)sizeof(html2));
		CHECK(n2 == n, "second fetch same length");
		if (n2 == n) {
			int i, same = 1;
			for (i = 0; i < n; i++) {
				if (html2[i] != html[i]) { same = 0; break; }
			}
			CHECK(same, "second fetch same bytes (deterministic)");
		}
	}

	/* ---------- 6. 参数校验 ---------- */
	CHECK(netmock_fetch(0, 0, (t_8 *)html, (int)sizeof(html)) < 0,
	      "NULL url rejected");
	CHECK(netmock_fetch("https://x", 0, 0, 100) < 0, "NULL output rejected");

	printf("=== %s: %d failure(s) ===\n", g_err ? "FAILED" : "ALL PASSED", g_err);
	return g_err ? 1 : 0;
}
