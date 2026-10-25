/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
        tools/preview/selftest.c — browser.c 的宿主侧自检 / 模糊测试

  思路:
    直接 #include "../../kernel/browser.c", 这样测试代码与实现处于同一个
    编译单元, 可以检查那些静态缓冲区 (br_line / br_src / br.line_count ...)
    的结构不变式 —— 不需要给内核代码加任何测试钩子, 也不需要 ASan.

  检查内容:
    1. 各种畸形/边界 HTML 输入: 不崩溃, 不死循环, 结构不变式成立
    2. 长行 / 超多段落 / 超长单词: 缓冲不越界, 行数被正确截断
    3. 非 ASCII / 控制字符 / 内嵌 NUL: 不崩溃
    4. 翻页 / 首尾键: top_row 始终在 [0, rows-1]
    5. 随机模糊输入 2000 组
    6. 每个用例都校验: 行长 <= BR_LINE_MAX-1, 行数 <= BR_MAX_LINES,
       br_src 以 '\0' 结尾且长度 <= BR_SRC_MAX-1, 行种类合法

  编译 (在 tools/preview 目录):
    gcc -I shim -I ../../include -O1 -o selftest.exe selftest.c
  运行:
    ./selftest.exe
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include <stdio.h>
#include <stdlib.h>

#include "type.h"
#include "const.h"
#include "gfx.h"
#include "keyboard.h"
#include "fat.h"
#include "browser.h"

/* 把实现直接包含进来, 以便检查其静态状态 */
#include "../../kernel/browser.c"

/* ===== gfx.c 的全局参数 ===== */
int g_font_width = 8;
int g_font_height = 16;

/* ===== 模拟屏幕 ===== */
#define SCREEN_W 1920
#define SCREEN_H 1080
static int g_err;
static int g_draw_calls;

#define CHECK(cond, msg)                                              \
	do {                                                              \
		if (!(cond)) {                                                \
			printf("  [FAIL] %s (line %d)\n", msg, __LINE__);         \
			g_err++;                                                  \
		}                                                             \
	} while (0)

/* 本地实现的 strlen / memcpy (不能包含 <string.h>: shim 目录里有同名空头) */
static int strlen_local(const char *s)
{
	int n = 0;
	while (s[n]) n++;
	return n;
}

static void memcpy_local(void *dst, const void *src, int n)
{
	const char *s = (const char *)src;
	char *d = (char *)dst;
	int i;
	for (i = 0; i < n; i++) d[i] = s[i];
}

/*======================================================================
  绘制原语桩: 只做坐标/字符合法性检查并计数, 不真的画
======================================================================*/
void put_pixel(int x, int y, t_8 color)
{
	(void)color;
	if (x < -64 || x > SCREEN_W || y < -64 || y > SCREEN_H) {
		printf("  [FAIL] put_pixel out of screen: %d,%d\n", x, y);
		g_err++;
	}
}

void fill_rect(int x, int y, int w, int h, t_8 color)
{
	(void)color;
	if (w < 0 || h < 0) { printf("  [FAIL] fill_rect negative size\n"); g_err++; }
	if (x < 0 || y < 0 || x + w > SCREEN_W || y + h > SCREEN_H) {
		printf("  [FAIL] fill_rect out of screen: %d,%d %dx%d\n", x, y, w, h);
		g_err++;
	}
	g_draw_calls++;
}

void draw_hline(int x1, int x2, int y, t_8 color)
{
	(void)color;
	if (x1 > x2) { int t = x1; x1 = x2; x2 = t; }
	if (x1 < 0 || x2 >= SCREEN_W || y < 0 || y >= SCREEN_H) {
		printf("  [FAIL] draw_hline out of screen: %d..%d @%d\n", x1, x2, y);
		g_err++;
	}
	g_draw_calls++;
}

void draw_vline(int x, int y1, int y2, t_8 color)
{
	(void)color;
	if (x < 0 || x >= SCREEN_W) { printf("  [FAIL] draw_vline x\n"); g_err++; }
	g_draw_calls++;
}

void draw_char(int x, int y, char ch, t_8 fg, t_8 bg)
{
	(void)fg; (void)bg;
	if (ch < 32 || ch > 126) {
		printf("  [FAIL] draw_char with control char 0x%02X\n", (unsigned char)ch);
		g_err++;
	}
	if (x < 0 || x + g_font_width > SCREEN_W || y < 0 || y + g_font_height > SCREEN_H) {
		printf("  [FAIL] draw_char out of screen: %d,%d\n", x, y);
		g_err++;
	}
	g_draw_calls++;
}

void draw_char_bold(int x, int y, char ch, t_8 fg, t_8 bg)
{
	draw_char(x, y, ch, fg, bg);
}

void draw_string(int x, int y, const char *str, t_8 fg, t_8 bg)
{
	while (*str) {
		draw_char(x, y, *str, fg, bg);
		x += g_font_width;
		str++;
	}
}

/*======================================================================
  FAT 桩: 一个内存中的"假文件系统" + 直接注入的测试文件
======================================================================*/
static const char *g_case_src;
static int g_case_len;

#define FS_MAX 8
static struct {
	char name[16];
	const char *body;
	int len;
} g_fs[FS_MAX];
static int g_fs_n;
static char g_last_title[40];

static void fs_reset(void)
{
	g_fs_n = 0;
	g_case_src = 0;
	g_case_len = 0;
	g_last_title[0] = 0;
}

static void fs_add(const char *name, const char *body)
{
	if (g_fs_n >= FS_MAX) return;
	br_copy(g_fs[g_fs_n].name, name, sizeof(g_fs[g_fs_n].name));
	g_fs[g_fs_n].body = body;
	g_fs[g_fs_n].len = strlen_local(body);
	g_fs_n++;
}

/* 只比较路径最后一段, 忽略大小写 */
static const char *path_tail(const char *p)
{
	const char *tail = p;
	while (*p) {
		if (*p == '/' || *p == '\\') tail = p + 1;
		p++;
	}
	return tail;
}

static int name_eq(const char *a, const char *b)
{
	return br_ieq(path_tail(a), path_tail(b));
}

int fat_init(void)
{
	return 0;
}

int fat_read_file_in(t_32 dir_cluster, const char *name, void *buf, int bufsize)
{
	int i, n;

	(void)dir_cluster;

	/* 内核只会传 BR_SRC_MAX-1, 顺便断言一下 */
	if (bufsize > BR_SRC_MAX - 1) {
		printf("  [FAIL] bufsize %d > BR_SRC_MAX-1\n", bufsize);
		g_err++;
	}

	/* 假文件系统优先 */
	for (i = 0; i < g_fs_n; i++) {
		if (name_eq(g_fs[i].name, name)) {
			n = g_fs[i].len;
			if (n > bufsize) n = bufsize;
			if (n > 0) memcpy_local(buf, g_fs[i].body, n);
			return n;
		}
	}

	/* run_case 直接注入的页面 */
	if (g_case_src && (br_ieq(name, "TEST.HTM") || br_ieq(name, "FUZZ.HTM"))) {
		n = g_case_len;
		if (n > bufsize) n = bufsize;
		if (n > 0) memcpy_local(buf, g_case_src, n);
		return n;
	}
	return -1;                                  /* 文件不存在 */
}

/* about:files 用: 枚举假文件系统 */
void fat_list_dir(t_32 dir_cluster, void (*callback)(FAT_DIR_ENTRY *))
{
	int i, k;
	FAT_DIR_ENTRY de;

	(void)dir_cluster;
	if (!callback) return;
	for (i = 0; i < g_fs_n; i++) {
		for (k = 0; k < 8; k++) de.name[k] = ' ';
		for (k = 0; k < 3; k++) de.ext[k] = ' ';
		for (k = 0; k < 8 && g_fs[i].name[k] && g_fs[i].name[k] != '.'; k++)
			de.name[k] = g_fs[i].name[k];
		{
			const char *dot = g_fs[i].name;
			while (*dot && *dot != '.') dot++;
			if (*dot == '.') {
				dot++;
				for (k = 0; k < 3 && dot[k]; k++) de.ext[k] = dot[k];
			}
		}
		de.attr = FAT_ATTR_ARCHIVE;
		de.file_size = (t_32)g_fs[i].len;
		de.start_cluster = (t_16)(i + 2);
		callback(&de);
	}
}

void wm_set_window_title(int idx, const char *title)
{
	(void)idx;
	br_copy(g_last_title, title, sizeof(g_last_title));
}

/*======================================================================
  结构不变式检查
======================================================================*/
static void check_invariants(const char *what)
{
	int li;

	CHECK(br.src_len >= 0 && br.src_len <= BR_SRC_MAX - 1, "src_len in range");
	CHECK(br_src[br.src_len] == 0, "src is NUL terminated");
	CHECK(br.line_count >= 0 && br.line_count <= BR_MAX_LINES, "line_count in range");
	if (br.line_count > 0) {
		CHECK(br.top_row >= 0, "top_row >= 0");
	}
	for (li = 0; li < br.line_count; li++) {
		int len = br_len(br_line[li]);
		if (len > BR_LINE_MAX - 1) {
			printf("  [FAIL] line %d too long (%d)\n", li, len);
			g_err++;
		}
		if (br_line_kind[li] > BR_LN_HR) {
			printf("  [FAIL] line %d bad kind %d\n", li, br_line_kind[li]);
			g_err++;
		}
		if (br_line_kind[li] == BR_LN_TEXT) {
			int k;
			if (len == 0) {
				printf("  [FAIL] text line %d is empty (should be skipped)\n", li);
				g_err++;
			}
			for (k = 0; k < len; k++) {
				unsigned char c = (unsigned char)br_line[li][k];
				if (c < 32 || c > 126) {
					printf("  [FAIL] line %d has byte 0x%02X\n", li, c);
					g_err++;
					break;
				}
			}
		}
		{
			int k;
			for (k = 0; k < BR_SPANS_PER_LINE; k++) {
				BR_SPAN *sp = &br_line_span[li][k];
				if (sp->link == 0) continue;
				if (sp->link > br.link_count) {
					printf("  [FAIL] line %d span %d link id %d > link_count %d\n",
					       li, k, sp->link, br.link_count);
					g_err++;
				}
				if (!(sp->start < sp->end) || (int)sp->end > len) {
					printf("  [FAIL] line %d span %d bad range %d..%d (len %d)\n",
					       li, k, sp->start, sp->end, len);
					g_err++;
				}
			}
		}
		if (br_line_st[li] != BR_ST_NORMAL && br_line_st[li] != BR_ST_H1) {
			printf("  [FAIL] line %d bad style %d\n", li, br_line_st[li]);
			g_err++;
		}
	}
	(void)what;
}

/*======================================================================
  用例驱动
======================================================================*/
static void draw_at(int w, int h, int win_x, int win_y)
{
	/* 客户区尺寸按 wm.c 的算法: 标题栏 + 3px 边框 */
	int title_h = g_font_height + 6;
	int border = 3;
	int cx = win_x + border;
	int cy = win_y + title_h;
	int cw = w - 2 * border;
	int ch = h - title_h - border;

	br_draw_client(0, cx, cy, cw, ch);
}

/* 用内存中的 HTML 打开并绘制一次, 然后检查不变式 */
static int run_case(const char *name, const char *html, int len,
                    int expect_code, int win_w, int win_h)
{
	int rc;

	g_case_src = html;
	g_case_len = len;
	br_reset();
	rc = br_open(0, "TEST.HTM");
	if (rc != expect_code) {
		printf("  [FAIL] %s: br_open returned %d, expected %d\n",
		       name, rc, expect_code);
		g_err++;
	}
	check_invariants(name);
	draw_at(win_w, win_h, 10, 10);
	check_invariants(name);
	return rc;
}

static void key_case(const char *name, t_32 key)
{
	br_handle_key(0, key);
	draw_at(320, 200, 10, 10);
	check_invariants(name);
	/* 滚动位置必须落在合法范围 */
	{
		int rows = br_total_rows();
		if (rows < 1) rows = 1;
		CHECK(br.top_row >= 0 && br.top_row <= rows - 1,
		      "top_row within [0, rows-1]");
	}
}

/*======================================================================
  随机模糊测试
======================================================================*/
static unsigned int g_seed = 12345;

static unsigned int rnd(void)
{
	g_seed = g_seed * 1103515245u + 12345u;
	return (g_seed >> 16) & 0x7FFF;
}

static void fuzz(int iterations)
{
	char buf[256];
	const char *alphabet = "<>h1p/br&;\"'= \r\n\tabcXYZ0243456789#&;:,.!?-_[]{}\\|`~";
	int alphabet_len = (int)strlen_local(alphabet);
	int it;

	for (it = 0; it < iterations; it++) {
		int len = (int)(rnd() % 200);
		int i;
		int err_before = g_err;

		for (i = 0; i < len; i++) {
			unsigned int r = rnd() % 100;
			if (r < 8) {
				buf[i] = (char)(1 + (rnd() % 31));           /* 控制字符 */
			} else if (r < 14) {
				buf[i] = (char)(0x80 + (rnd() % 0x80));      /* 高位字节 */
			} else if (r < 20) {
				buf[i] = 0;                                   /* 内嵌 NUL */
			} else {
				buf[i] = alphabet[rnd() % alphabet_len];
			}
		}

		g_case_src = buf;
		g_case_len = len;
		br_reset();
		br_open(0, "FUZZ.HTM");
		check_invariants("fuzz/open");
		draw_at(320, 200, 10, 10);
		draw_at(640, 480, 10, 10);
		check_invariants("fuzz/draw");
		key_case("fuzz/key1", PAGEDOWN);
		key_case("fuzz/key2", END);
		key_case("fuzz/key3", HOME);
		key_case("fuzz/key4", PAGEUP);

		if (g_err > err_before) {
			printf("  (fuzz stopped at iteration %d, len=%d)\n", it, len);
			return;
		}
	}
	printf("  fuzz: %d random inputs OK\n", iterations);
}

/* 结构化模糊: 用"标签片段"拼出形似网页的输入, 覆盖嵌套/跳过/实体等路径 */
static void fuzz_html(int iterations)
{
	static const char *tokens[] = {
		"<h1>", "</h1>", "<p>", "</p>", "<br>", "<hr>",
		"<b>", "</b>", "<script>", "</script>", "<head>", "</head>",
		"<title>", "</title>", "<!--", "-->", "<a href=\"x>y\">", "</a>",
		"hello ", "world", "&amp;", "&lt;", "&nbsp;", "&bogus;",
		"<p align=center>", "\r\n", "\t", "\"", "'", "<", ">", "&",
		"0123456789", "<div class='c'>", "</div>"
	};
	int token_count = (int)(sizeof(tokens) / sizeof(tokens[0]));
	char buf[1200];
	int it;

	for (it = 0; it < iterations; it++) {
		int n = (int)(rnd() % 60);
		int pos = 0;
		int i;
		int err_before = g_err;

		for (i = 0; i < n; i++) {
			const char *t = tokens[rnd() % token_count];
			int k;
			for (k = 0; t[k] && pos < (int)sizeof(buf) - 2; k++) buf[pos++] = t[k];
		}
		buf[pos] = 0;

		g_case_src = buf;
		g_case_len = pos;
		br_reset();
		br_open(0, "FUZZ.HTM");
		check_invariants("fuzz_html/open");
		draw_at(640, 480, 10, 10);
		key_case("fuzz_html/key", PAGEDOWN);

		if (g_err > err_before) {
			printf("  (html fuzz stopped at iteration %d)\n", it);
			return;
		}
	}
	printf("  html fuzz: %d structured inputs OK\n", iterations);
}

/*======================================================================
  主程序
======================================================================*/
int main(void)
{
	int i;
	static char big[900];
	static char longword[520];

	printf("=== browser.c self test ===\n");

	/* 1. 空文件 / 文件不存在 */
	printf("[case] empty file\n");
	run_case("empty", "", 0, -1, 640, 480);
	printf("[case] missing file\n");
	g_case_src = 0;
	br_reset();
	CHECK(br_open(0, "NOPE.HTM") == -1, "missing file returns -1");
	check_invariants("missing");
	draw_at(640, 480, 10, 10);

	/* 2. 基本功能 */
	printf("[case] plain text\n");
	run_case("plain", "hello world", 11, 0, 640, 480);
	CHECK(br.line_count == 1, "plain text is one line");
	CHECK(br_len(br_line[0]) == 11, "plain text length kept");

	printf("[case] h1 + p\n");
	run_case("h1p", "<h1>Title</h1><p>Body text</p>", 33, 0, 640, 480);
	CHECK(br.line_count >= 2, "h1 + p produce at least 2 lines");
	CHECK(br_len(br_line[0]) == 5 && br_line_st[0] == BR_ST_H1, "first line is h1");

	/* 3. 畸形标签 */
	printf("[case] malformed tags\n");
	run_case("unclosed-h1", "<h1>abc", 8, 0, 640, 480);
	CHECK(br_line_st[0] == BR_ST_H1, "unclosed h1 keeps heading style");
	run_case("tag-no-gt", "<p abc", 6, -1, 640, 480);
	run_case("lt-at-eof", "abc<", 4, 0, 640, 480);
	run_case("comment-open", "<!-- abc", 8, -1, 640, 480);
	run_case("comment-ok", "a<!-- x -->b", 13, 0, 640, 480);
	CHECK(br_len(br_line[0]) == 2, "comment removed");
	run_case("script-skip", "<script>var x=1;</script>VISIBLE", 32, 0, 640, 480);
	CHECK(br_len(br_line[0]) == 7, "script body skipped");
	run_case("head-skip", "<head><title>T</title></head>BODY", 34, 0, 640, 480);
	CHECK(br_len(br_line[0]) == 4, "head skipped");
	run_case("attrs-with-gt", "<p class=\"a>b\">x</p>", 21, 0, 640, 480);
	CHECK(br_len(br_line[0]) == 1, "attribute containing > handled");
	run_case("uppercase", "<H1>UP</H1><P>p</P>", 21, 0, 640, 480);
	run_case("nested", "<h1>a<p>b</p>c</h1>", 21, 0, 640, 480);
	run_case("hr-only", "<hr>", 4, 0, 640, 480);
	CHECK(br_line_kind[0] == BR_LN_HR, "hr line kind");
	run_case("amp-at-eof", "abc&", 4, 0, 640, 480);
	CHECK(br_len(br_line[0]) == 4, "trailing & kept");

	printf("[case] entities\n");
	run_case("entities", "&amp;&lt;&gt;&quot;&apos;&nbsp;&bogus;", 38, 0, 640, 480);

	printf("[case] crlf and tabs\n");
	run_case("crlf-tabs", "a\r\n\tb", 6, 0, 640, 480);
	CHECK(br_len(br_line[0]) == 3, "whitespace collapsed to single space");

	printf("[case] non-ascii\n");
	run_case("chinese", "<p>\xe4\xb8\xad\xe6\x96\x87</p>", 13, 0, 640, 480);

	printf("[case] embedded NUL\n");
	run_case("nul", "a\0b", 3, 0, 640, 480);

	/* 4. 长行 / 超长单词 */
	printf("[case] long word (500 chars)\n");
	for (i = 0; i < 500; i++) longword[i] = 'A';
	longword[500] = 0;
	run_case("long-word", longword, 500, 0, 320, 200);
	CHECK(br.line_count >= 3, "long word split across lines");

	/* 5. 超多段落 (行数上限) */
	printf("[case] 200 paragraphs\n");
	{
		int pos = 0;
		for (i = 0; i < 200 && pos < (int)sizeof(big) - 20; i++) {
			const char *chunk = "<p>para</p>";
			int k;
			for (k = 0; chunk[k]; k++) big[pos++] = chunk[k];
		}
		run_case("many-paras", big, pos, 0, 640, 480);
		CHECK(br.line_count <= BR_MAX_LINES, "line cap respected");
	}

	/* 6. 各分辨率下绘制 (窗口按 wm.c 的 4/5 宽、3/4 高居中放置) */
	printf("[case] render at several sizes\n");
	for (i = 0; i < 6; i++) {
		int sizes[6][2] = {
			{320, 200}, {640, 480}, {800, 600}, {1024, 768}, {1280, 1024}, {1920, 1080}
		};
		int sw = sizes[i][0], sh = sizes[i][1];
		int ww = sw * 4 / 5, wh = sh * 3 / 4;

		g_case_src = "<h1>Title</h1><p>The quick brown fox jumps over the lazy dog. "
		             "Pack my box with five dozen liquor jugs.</p><hr><p>end</p>";
		g_case_len = (int)strlen_local(g_case_src);
		br_reset();
		CHECK(br_open(0, "TEST.HTM") == 0, "open for size test");
		draw_at(ww, wh, sw / 10, sh / 10);
		check_invariants("size test");
	}

	/* 7. 同一页面在窗口尺寸变化后重新排版 (模拟最大化) */
	printf("[case] relayout after resize\n");
	{
		g_case_src = "<h1>Resize</h1><p>alpha beta gamma delta epsilon zeta eta theta</p>";
		g_case_len = (int)strlen_local(g_case_src);
		br_reset();
		CHECK(br_open(0, "TEST.HTM") == 0, "open for resize test");
		draw_at(320, 200, 10, 10);
		{
			int rows_small = br_total_rows();
			draw_at(1024, 768, 10, 10);
			{
				int rows_big = br_total_rows();
				CHECK(rows_big <= rows_small, "wider window needs no more rows");
			}
		}
		check_invariants("resize");
	}

	/* 8. 翻页/首尾键边界 */
	printf("[case] key edges\n");
	{
		g_case_src = "<h1>A</h1><p>1</p><p>2</p><p>3</p><p>4</p><p>5</p><p>6</p>";
		g_case_len = (int)strlen_local(g_case_src);
		br_reset();
		CHECK(br_open(0, "TEST.HTM") == 0, "open for key test");
		draw_at(320, 200, 10, 10);
		for (i = 0; i < 40; i++) key_case("pagedown x40", PAGEDOWN);
		for (i = 0; i < 40; i++) key_case("pageup x40", PAGEUP);
		for (i = 0; i < 10; i++) key_case("down x10", DOWN);
		for (i = 0; i < 10; i++) key_case("up x10", UP);
		key_case("end", END);
		key_case("home", HOME);
		/* F5 会重新读文件 */
		key_case("f5", F5);
		CHECK(br.ok == 1, "reload keeps page loaded");
		/* 未打开的窗口索引不应被处理 */
		CHECK(br_handle_key(7, PAGEDOWN) == 0, "foreign window key ignored");
		CHECK(br_handle_click(7, 10, 10) == 0, "foreign window click ignored");
	}

	/* 8b. 链接点击 / 导航 / 地址栏 / 历史 / 内置页面 */
	printf("[case] links and navigation\n");
	{
		static const char page_a[] = "<h1>A</h1><p><a href=\"B.HTM\">to B</a></p>";
		static const char page_link_first[] = "<p><a href=\"B.HTM\">B</a></p>";
		static const char page_b[] = "<h1>B</h1><p>page B</p>";

		fs_reset();
		fs_add("A.HTM", page_a);
		fs_add("B.HTM", page_b);
		g_font_width = 8;
		g_font_height = 16;

		/* 链接解析 */
		br_reset();
		CHECK(br_open(0, "A.HTM") == 0, "open A.HTM");
		CHECK(br_ieq(br.url, "/A.HTM"), "url is /A.HTM");
		CHECK(br.link_count == 1, "one link recorded");
		CHECK(br_ieq(br_links[0], "B.HTM"), "href parsed");
		CHECK(g_last_title[0] != 0 && g_last_title[1] != 0, "window title updated");
		{
			int found = 0, li, ci;
			for (li = 0; li < br.line_count; li++)
				for (ci = 0; ci < BR_LINE_MAX && br_line[li][ci]; ci++)
					if (br_link_at(li, ci) == 1) found++;
			CHECK(found > 0, "link map marks link text");
		}

		/* 点击第一行的链接 -> 跳转到 B.HTM */
		br_reset();
		CHECK(br_open(0, "LINK.HTM") != 0, "LINK.HTM does not exist yet");
		fs_add("LINK.HTM", page_link_first);
		CHECK(br_open(0, "LINK.HTM") == 0, "open LINK.HTM");
		draw_at(640, 480, 10, 10);
		{
			int cx = 10 + 3;
			int cy = 10 + (g_font_height + 6);
			int px = cx + 4 + 2;
			int py = cy + br_toolbar_h() + 2 + 8;
			CHECK(br_handle_click(0, px, py) == 1, "click handled");
			CHECK(br_ieq(br.url, "/B.HTM"), "click followed the link");
			CHECK(br.line_count >= 1, "page B parsed");
		}

		/* 地址栏: 退格清空 + 输入 + 回车 */
		{
			int k;
			for (k = 0; k < BR_URL_MAX; k++) br_handle_key(0, BACKSPACE);
			CHECK(br.addr_len == 0, "address bar cleared by backspace");
			br_handle_key(0, 'A');
			br_handle_key(0, '.');
			br_handle_key(0, 'H');
			br_handle_key(0, 'T');
			br_handle_key(0, 'M');
			CHECK(br_ieq(br.addr, "A.HTM"), "typing reaches address bar");
			br_handle_key(0, ENTER);
			CHECK(br_ieq(br.url, "/A.HTM"), "enter navigates");
			CHECK(br.hist_n == 3, "history has 3 entries");
		}

		/* 历史: 后退 / 前进 */
		br_handle_key(0, LEFT);
		CHECK(br_ieq(br.url, "/B.HTM"), "left goes back to /B.HTM");
		br_handle_key(0, RIGHT);
		CHECK(br_ieq(br.url, "/A.HTM"), "right goes forward to /A.HTM");
		br_handle_key(0, LEFT);
		br_handle_key(0, LEFT);
		CHECK(br_ieq(br.url, "/LINK.HTM"), "back twice reaches /LINK.HTM");

		/* 访问过的链接应变紫 (visited) */
		CHECK(br_is_visited("B.HTM"), "navigated target is marked visited");

		/* 内置页面 */
		printf("[case] builtin pages\n");
		br_reset();
		CHECK(br_open(0, "about:files") == 0, "about:files opens");
		CHECK(br.link_count >= 1, "files page contains links");
		CHECK(br_open(0, "about:help") == 0, "about:help opens");
		CHECK(br_open(0, "about:home") == 0, "about:home opens");
		CHECK(br_open(0, "http://example.com") == 0, "external url handled");
		CHECK(br_ieq(br.url, "about:offline"), "offline page recorded");
		draw_at(640, 480, 10, 10);
		check_invariants("builtin pages");
		{
			/* 未知文件: 打开失败但状态栏给出原因, 不崩溃 */
			br_reset();
			CHECK(br_open(0, "GONE.HTM") != 0, "missing file fails");
			CHECK(br.ok == 0, "ok cleared on failure");
			CHECK(br_len(br.msg) > 0, "failure message present");
			draw_at(320, 200, 10, 10);
			check_invariants("missing page");
		}
	}

	/* 9. 随机模糊 */
	printf("[case] random fuzz\n");
	fuzz(20000);

	printf("[case] structured html fuzz\n");
	fuzz_html(5000);

	printf("\n=== %s: %d failure(s), %d draw calls ===\n",
	       g_err ? "FAILED" : "ALL PASSED", g_err, g_draw_calls);
	return g_err ? 1 : 0;
}
