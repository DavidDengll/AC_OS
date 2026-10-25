/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              browser.c
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                     CatOS Browser — 内核内置离线浏览器

  功能 (第二版: 在"能显示网页"的基础上加了导航):
    1. 不联网: 只读本地 FAT 硬盘根目录的 HTML 文件, 没有任何网络代码
    2. 工具栏: 后退 < / 前进 > / 主页 H / 刷新 R 四个按钮 + 地址栏
    3. 地址栏: 显示当前地址, 可直接输入文件名后按 Enter 打开
    4. 链接: <a href="..."> 显示为蓝色下划线, 鼠标点击跳转 (已访问变紫)
    5. 历史: 前进/后退 (按钮, 或 ← → 方向键), 最多 8 条
    6. 内置页面: about:home / about:help / about:files (磁盘根目录列表)
       以及"无网络"提示页 (打开 http:// 等外部地址时显示)
    7. 翻页: PgUp/PgDn/↑/↓/Home/End 按"显示行"翻页, F5 重新读文件

  支持的 HTML 子集:
    <h1>…</h1>   标题 (蓝色加粗 + 前后空行)
    <p>…</p>     段落 (自动折行, 段前空行)
    <a href>…</a> 链接 (蓝色/紫色 + 下划线, 可点击)
    <br>         换行        <hr> 水平分隔线
    其他标签忽略 (保留其文字); <head>/<title>/<script>/<style> 整段跳过

  内存安全 (内核态运行!):
    - 全部静态缓冲区, 无任何动态分配, 不存在"分配失败 -> 缺页"路径
    - 读文件/解析/折行/滚动/命中测试全部边界夹紧, 无负索引, 除数恒 >= 1
    - 解析为单遍顺序扫描, 无递归; 畸形 HTML (未闭合标签/超长行/引号内 '>')
      由 tools/preview/selftest.c 的模糊测试覆盖

  尚未支持 (后续计划): 子目录页面、CSS/颜色/列表/图片、真实滚动条
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include "type.h"
#include "const.h"
#include "protect.h"
#include "string.h"
#include "proc.h"
#include "tty.h"
#include "console.h"
#include "global.h"
#include "proto.h"
#include "gfx.h"
#include "keyboard.h"
#include "wm.h"
#include "fat.h"
#include "hd.h"
#include "browser.h"

/* ===== 容量 (静态占用约 36KB BSS) ===== */
#define BR_SRC_MAX       4096    /* 读入/生成的 HTML 上限 */
#define BR_MAX_LINES       96    /* 逻辑行上限 */
#define BR_LINE_MAX       160    /* 单行字符上限 */
#define BR_URL_MAX         48    /* 地址/链接字符串长度 */
#define BR_LINKS_MAX        8    /* 每页链接上限 (按 href 去重) */
#define BR_HIST_MAX         8    /* 历史记录条数 */
#define BR_ATTR_MAX        96    /* 标签属性原文长度 */

/* ===== 行种类 ===== */
#define BR_LN_TEXT          0
#define BR_LN_BLANK         1
#define BR_LN_HR            2
#define BR_LN_IMG         3      /* BMP image line */
#define BR_LN_LIST        4      /* list item (indent + bullet) */

/* ===== 行样式 ===== */
#define BR_ST_NORMAL        0
#define BR_ST_H1            1

/* ===== 颜色 (全部取自 VGA 标准调色板前 16 色) ===== */
#define BR_COL_BG        0x0F    /* 页面背景: 白 */
#define BR_COL_TEXT      0x00    /* 正文: 黑 */
#define BR_COL_H1        0x01    /* 标题: 蓝 */
#define BR_COL_LINK      0x09    /* 链接: 亮蓝 */
#define BR_COL_VISITED   0x05    /* 已访问链接: 紫 */
#define BR_COL_HR        0x08    /* 分隔线: 深灰 */
#define BR_COL_ERR       0x0C    /* 错误: 红 */
#define BR_COL_STATUS    0x17    /* 状态栏: 白字蓝底 */
#define BR_COL_BAR       0x07    /* 工具栏: 浅灰 */
#define BR_COL_BAR_DARK  0x08    /* 分隔线: 深灰 */
#define BR_COL_BAR_LIGHT 0x0F    /* 高光: 白 */
#define BR_COL_BTN_TXT   0x00    /* 按钮文字: 黑 */
#define BR_COL_BTN_DIS   0x08    /* 按钮禁用: 深灰 */
#define BR_COL_ADDR_BG   0x0F    /* 地址栏: 白底 */
#define BR_COL_ADDR_TXT  0x00    /* 地址栏文字: 黑 */

/* ===== 工具栏按钮编号 ===== */
#define BR_BTN_BACK         0
#define BR_BTN_FWD          1
#define BR_BTN_HOME         2
#define BR_BTN_RELOAD       3

/* 默认首页文件名 (FAT 根目录) */
#define BR_DEFAULT_FILE  "INDEX.HTM"

/* ===== 状态 (单实例, 与终端/记事本一致) ===== */
PRIVATE struct {
	int  win_idx;                /* 窗口索引 */
	int  active;                 /* 1=窗口已打开 */

	char url[BR_URL_MAX];        /* 当前地址 (规范形式, 如 "/INDEX.HTM") */
	char file[16];               /* 当前文件名 (F5 重载用) */
	int  src_len;                /* 源 HTML 字节数 */
	int  line_count;             /* 逻辑行数 */
	int  top_row;                /* 首个可见显示行 (滚动位置) */
	int  ok;                     /* 1=加载成功, 0=显示错误信息 */
	char msg[64];                /* 状态栏信息 */

	int  cl_x, cl_y, cl_w, cl_h; /* 最近一次绘制的客户区矩形 */

	/* 地址栏 */
	int  addr_len;
	char addr[BR_URL_MAX];
	int  addr_focus;             /* 1=键盘输入进入地址栏 */

	/* 链接 */
	int  link_count;
	t_8  page_bg;                    /* <body bgcolor> */
	t_8  page_fg;                    /* <body text> */
	t_8  cur_fg;                     /* 当前 <font color> */
	int  cur_img;                    /* 当前 <img> 的缓存索引 */
	int  list_depth;                 /* <ul> 嵌套深度 */

	/* 历史 */
	int  hist_n;
	int  hist_pos;
} br;

/* ==================================================================
   大缓冲区放在 0x1C0000 起的固定 arena, 不占 .bss.

   ★ 这里原来写的是 0x200000 —— 那是错的, 不能用:
     0x200000 = PageDirBase (页目录), 0x201000 = PageTblBase (页表),
     见 boot/include/load.inc. 往那里放 arena 会把页表当场写坏,
     表现为 CR2=0xFD000000 (LFB PDE 丢失) + 三重故障.

   现在的选址: 0x1C0000 (task_stack 末端 0x1C0000 ~ PageDirBase 0x200000
   之间这 256KB 空闲区), 大小 20240 字节 (0x4F10),
   占用 0x1C0000~0x1C4F10, 与 0x1D0000 起的 wm arena 不冲突.
   这段物理内存被 loader 的 SetupPaging 恒等映射 (至少前 16MB), 可直接访问.

   宿主侧测试用 -DBR_HOST_BUILD 改成本地数组, 便于在 PC 上跑.
   ================================================================== */
#define BR_SPANS_PER_LINE  2
typedef struct {
	t_8 link;        /* 链接 id (0=无) */
	t_8 start;       /* 起始字符下标 */
	t_8 end;         /* 结束字符下标 (开区间) */
} BR_SPAN;

#define BR_ARENA_SIZE  (BR_MAX_LINES * BR_LINE_MAX +      /* br_line    */ \
                        BR_MAX_LINES +                    /* kind       */ \
                        BR_MAX_LINES +                    /* style      */ \
                        BR_MAX_LINES * BR_SPANS_PER_LINE * 3 + /* spans  */ \
                        BR_MAX_LINES +                          /* fg      */ \
                        BR_MAX_LINES * 2 +                      /* img idx */ \
                        BR_SRC_MAX + 16)                  /* src + 对齐 */

#ifdef BR_HOST_BUILD
PRIVATE char br_arena_mem[BR_ARENA_SIZE];
#define BR_ARENA_BASE ((char *)br_arena_mem)
#else
#define BR_ARENA_BASE ((char *)0x1C0000u)
#endif

/* 行表 (指向 arena) */
PRIVATE char (*br_line)[BR_LINE_MAX];
PRIVATE t_8   *br_line_kind;
PRIVATE t_8   *br_line_st;
PRIVATE BR_SPAN (*br_line_span)[BR_SPANS_PER_LINE];
PRIVATE t_8   *br_line_fg;     /* line fg color (0xFF = inherit) */
PRIVATE t_16  *br_line_img;    /* BR_LN_IMG: BMP cache index */

/* ===== BMP cache (FAT root, up to 4 x 200x100) ===== */
#define BR_IMG_MAX   2
#define BR_IMG_W     100
#define BR_IMG_H     80
typedef struct {
	int used;
	int w, h;
	int bpp;                         /* 4, 8 or 24 */
	t_8  pal[256 * 3];               /* palette RGB */
	t_8  px[BR_IMG_W * BR_IMG_H];    /* 8bpp index */
} BR_IMG;
/* 缓冲放 0x1C5000 起的空闲区 (browser arena 0x1C4F10 之后, wm 画布 0x1D0000 之前),
 * 2 张 100x80 共约 17.5KB. 不占 .bss (内核 .bss 已顶到显存洞). */
#define BR_IMG_ARENA 0x1C5000u
#define br_imgs ((BR_IMG *)BR_IMG_ARENA)
PRIVATE int    br_img_count;

/* 页面 / 生成缓冲 (指向 arena) */
PRIVATE char *br_src;

/* 从 arena 中切出各缓冲区 (幂等) */
PRIVATE void br_arena_init(void)
{
	static int inited;
	char *p;

	if (inited) return;
	inited = 1;

	p = BR_ARENA_BASE;
	br_line = (char (*)[BR_LINE_MAX])p;
	p += BR_MAX_LINES * BR_LINE_MAX;
	br_line_kind = (t_8 *)p;
	p += BR_MAX_LINES;
	br_line_st = (t_8 *)p;
	p += BR_MAX_LINES;
	br_line_span = (BR_SPAN (*)[BR_SPANS_PER_LINE])p;
	br_line_fg = (t_8 *)p;
	p += BR_MAX_LINES;
	br_line_img = (t_16 *)p;
	p += BR_MAX_LINES * 2;
	p += BR_MAX_LINES * BR_SPANS_PER_LINE * 3;
	br_src = p;
	p += BR_SRC_MAX;

	/* arena 首次使用时清零 (br_src 需要以 '\0' 结尾) */
	{
		int i;
		for (i = 0; i < BR_ARENA_SIZE; i++) BR_ARENA_BASE[i] = 0;
	}
}

/* 链接表 (按 href 去重) */
PRIVATE char br_links[BR_LINKS_MAX][BR_URL_MAX];

/* 历史表 */
PRIVATE char br_hist[BR_HIST_MAX][BR_URL_MAX];

/* 生成页面时的输出游标 */
PRIVATE char *br_gen_p;
PRIVATE int   br_gen_left;

/* 当前解析标签的属性原文 */
PRIVATE char br_tag_attrs[BR_ATTR_MAX];

/*======================================================================*
                          字符串小工具
 *======================================================================*/

PRIVATE int br_len(const char *s)
{
	int n = 0;
	while (s[n]) n++;
	return n;
}

PRIVATE void br_copy(char *d, const char *s, int max)
{
	int i;
	if (max <= 0) return;
	for (i = 0; i < max - 1 && s[i]; i++) d[i] = s[i];
	d[i] = 0;
}

/* 追加 (长度安全) */
PRIVATE void br_cat(char *d, const char *s, int max)
{
	int i = br_len(d);
	int j = 0;
	while (i < max - 1 && s[j]) d[i++] = s[j++];
	d[i] = 0;
}

PRIVATE char br_lower(char c)
{
	if (c >= 'A' && c <= 'Z') return (char)(c + 32);
	return c;
}

PRIVATE char br_upper(char c)
{
	if (c >= 'a' && c <= 'z') return (char)(c - 32);
	return c;
}

PRIVATE int br_ieq(const char *a, const char *b)
{
	int i = 0;
	while (a[i] && b[i]) {
		if (br_lower(a[i]) != br_lower(b[i])) return 0;
		i++;
	}
	return a[i] == b[i];
}

PRIVATE int br_ipre(const char *s, const char *pre)
{
	int i = 0;
	while (pre[i]) {
		if (!s[i] || br_lower(s[i]) != br_lower(pre[i])) return 0;
		i++;
	}
	return 1;
}

/* 追加到状态栏信息 (长度安全) */
PRIVATE void br_msg_cat(const char *s, int max)
{
	int i = br_len(br.msg);
	int j = 0;
	while (i < max - 1 && s[j]) br.msg[i++] = s[j++];
	br.msg[i] = 0;
}

PRIVATE void br_set_msg(const char *a, const char *b)
{
	br.msg[0] = 0;
	if (a) br_cat(br.msg, a, sizeof(br.msg));
	if (b) br_msg_cat(b, sizeof(br.msg));
}

/*======================================================================*
                          链接表
 *======================================================================*/

/* 登记链接, 返回 1 起的 id (0=失败/空) */
PRIVATE t_8 br_add_link(const char *href)
{
	int i;
	if (!href || !*href) return 0;
	for (i = 0; i < br.link_count; i++) {
		if (br_ieq(br_links[i], href)) return (t_8)(i + 1);
	}
	if (br.link_count >= BR_LINKS_MAX) return 0;
	br_copy(br_links[br.link_count], href, BR_URL_MAX);
	br.link_count++;
	return (t_8)br.link_count;
}

/* 该 href 是否在历史里 (用于把已访问链接画成紫色) */
PRIVATE int br_is_visited(const char *href)
{
	int i;
	if (!href || !*href) return 0;
	for (i = 0; i < br.hist_n; i++) {
		const char *h = br_hist[i];
		const char *a = href;
		while (*a == '/') a++;
		while (*h == '/') h++;
		if (br_ieq(a, h)) return 1;
	}
	return 0;
}

/*======================================================================*
                          行表
 *======================================================================*/

/* 第 li 行第 pos 个字符所属的链接 id (0=无) */
PRIVATE t_8 br_link_at(int li, int pos)
{
	int k;
	for (k = 0; k < BR_SPANS_PER_LINE; k++) {
		if (br_line_span[li][k].link &&
		    pos >= (int)br_line_span[li][k].start &&
		    pos < (int)br_line_span[li][k].end) {
			return br_line_span[li][k].link;
		}
	}
	return 0;
}

/* 追加一个逻辑行. linkmap 可为 0; 空文本行不占位 */
PRIVATE void br_add_line(const char *text, const t_8 *linkmap, int len,
                         t_8 style, t_8 kind)
{
	int i;

	if (br.line_count >= BR_MAX_LINES) return;
	if (len < 0) len = 0;
	if (len > BR_LINE_MAX - 1) len = BR_LINE_MAX - 1;
	/* 去掉行尾空格 */
	while (len > 0 && text[len - 1] == ' ') len--;
	if (kind == BR_LN_TEXT && len <= 0) return;

	for (i = 0; i < len; i++) {
		br_line[br.line_count][i] = text[i];
	}
	br_line[br.line_count][len] = 0;

	/* 由逐字符 map 归并成区间 (最多 BR_SPANS_PER_LINE 段, 超出部分丢弃) */
	{
		int nspan = 0;
		int k = 0;
		for (k = 0; k < BR_SPANS_PER_LINE; k++) {
			br_line_span[br.line_count][k].link = 0;
			br_line_span[br.line_count][k].start = 0;
			br_line_span[br.line_count][k].end = 0;
		}
		k = 0;
		while (k < len && nspan < BR_SPANS_PER_LINE) {
			t_8 id = linkmap ? linkmap[k] : 0;
			int s;
			if (id == 0) { k++; continue; }
			s = k;
			while (k < len && (linkmap ? linkmap[k] : 0) == id) k++;
			br_line_span[br.line_count][nspan].link = id;
			br_line_span[br.line_count][nspan].start = (t_8)s;
			br_line_span[br.line_count][nspan].end = (t_8)k;
			nspan++;
		}
	}
	br_line_kind[br.line_count] = kind;
	br_line_st[br.line_count] = style;
	br_line_fg[br.line_count] = br.cur_fg;
	if (kind == BR_LN_IMG) br_line_img[br.line_count] = (t_16)br.cur_img;
	br.line_count++;
}

/* 段落间隔: 最后一行不是空行时补一个 */
PRIVATE void br_add_blank(void)
{
	if (br.line_count == 0) return;
	if (br_line_kind[br.line_count - 1] == BR_LN_BLANK) return;
	br_add_line(0, 0, 0, BR_ST_NORMAL, BR_LN_BLANK);
}

/*======================================================================*
                          标签属性解析
 *======================================================================*/

/* 从属性原文中取出下一个 name=value. 返回下一位置, 0=结束 */
PRIVATE char *br_next_attr(char *s, char *name, int name_max,
                           char *val, int val_max)
{
	int i = 0;

	while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') s++;
	if (!*s) return 0;
	while (*s && *s != '=' && *s != ' ' && *s != '\t' &&
	       *s != '\r' && *s != '\n') {
		if (i < name_max - 1) name[i++] = br_lower(*s);
		s++;
	}
	name[i] = 0;
	val[0] = 0;
	while (*s == ' ' || *s == '\t') s++;
	if (*s == '=') {
		int j = 0;
		s++;
		while (*s == ' ' || *s == '\t') s++;
		if (*s == '"' || *s == '\'') {
			char qc = *s++;
			while (*s && *s != qc) {
				if (j < val_max - 1) val[j++] = *s;
				s++;
			}
			if (*s == qc) s++;
		} else {
			while (*s && *s != ' ' && *s != '\t' &&
			       *s != '\r' && *s != '\n') {
				if (j < val_max - 1) val[j++] = *s;
				s++;
			}
		}
		val[j] = 0;
	}
	return s;
}

/* 取属性值 (忽略大小写). 返回 1=找到 */
PRIVATE int br_attr(const char *name, char *out, int out_max)
{
	char *s = br_tag_attrs;
	char nm[16];
	char vl[BR_URL_MAX];

	if (out_max > 0) out[0] = 0;
	while ((s = br_next_attr(s, nm, sizeof(nm), vl, sizeof(vl))) != 0) {
		if (br_ieq(nm, name)) {
			br_copy(out, vl, out_max);
			return 1;
		}
	}
	return 0;
}

/*======================================================================*
                          HTML 解析
 *======================================================================*/

/* 解析 HTML 颜色: #RGB / #RRGGBB / 常用英文名. 返回调色板索引, -1=无效 */
PRIVATE int br_parse_color(const char *s)
{
	int v[6];
	int i, r, g, b, n;

	if (!s || !*s) return -1;
	if (s[0] == '#') {
		n = 0;
		s++;
		while (n < 6) {
			int d;
			if (*s >= '0' && *s <= '9') d = *s - '0';
			else if (*s >= 'a' && *s <= 'f') d = *s - 'a' + 10;
			else if (*s >= 'A' && *s <= 'F') d = *s - 'A' + 10;
			else break;
			v[n++] = d;
			s++;
		}
		if (n == 3) { r = v[0]*17; g = v[1]*17; b = v[2]*17; }
		else if (n == 6) {
			r = v[0]*16 + v[1];
			g = v[2]*16 + v[3];
			b = v[4]*16 + v[5];
		} else return -1;
	}
	else if (br_ipre(s, "black"))   { r=0;   g=0;   b=0;   }
	else if (br_ipre(s, "white"))   { r=255; g=255; b=255; }
	else if (br_ipre(s, "red"))     { r=255; g=0;   b=0;   }
	else if (br_ipre(s, "green"))   { r=0;   g=128; b=0;   }
	else if (br_ipre(s, "lime"))    { r=0;   g=255; b=0;   }
	else if (br_ipre(s, "blue"))    { r=0;   g=0;   b=255; }
	else if (br_ipre(s, "yellow"))  { r=255; g=255; b=0;   }
	else if (br_ipre(s, "cyan"))    { r=0;   g=255; b=255; }
	else if (br_ipre(s, "magenta")) { r=255; g=0;   b=255; }
	else if (br_ipre(s, "gray"))    { r=128; g=128; b=128; }
	else if (br_ipre(s, "silver"))  { r=192; g=192; b=192; }
	else if (br_ipre(s, "navy"))    { r=0;   g=0;   b=128; }
	else if (br_ipre(s, "orange"))  { r=255; g=165; b=0;   }
	else if (br_ipre(s, "purple"))  { r=128; g=0;   b=128; }
	else return -1;

	/* 调色板 32~247 是 6x6x6 立方体 (见 gfx.c: gfx_set_palette) */
	return 32 + (r * 5 / 255) * 36 + (g * 5 / 255) * 6 + (b * 5 / 255);
}
PRIVATE int br_load_bmp(const char *name);

/* 跳过 <name ...> 到 </name> 之间的内容 (head/script/style/title) */
PRIVATE char *br_skip_element(char *p, char *end, const char *name)
{
	char close_tag[16];
	int n = 0, i;

	close_tag[n++] = '<';
	close_tag[n++] = '/';
	for (i = 0; name[i] && n < 13; i++) close_tag[n++] = name[i];
	close_tag[n++] = '>';
	close_tag[n] = 0;

	while (p < end) {
		if (*p == '<' && br_ipre(p, close_tag)) {
			p += n;
			return p;
		}
		p++;
	}
	return end;
}

/* 解析 br_src 为逻辑行. 返回 0=成功, -1=无内容 */
PRIVATE int br_parse(void)
{
	char *p;
	char *end;
	char cur[BR_LINE_MAX];
	t_8  cur_link[BR_LINE_MAX];
	t_8  cur_fg_buf[BR_LINE_MAX];
	int  cur_len = 0;
	t_8  style = BR_ST_NORMAL;
	t_8  link = 0;

	br.line_count = 0;
	br.link_count = 0;
	br.top_row = 0;
	br.page_bg = BR_COL_BG;
	br.page_fg = BR_COL_TEXT;
	br.cur_fg = 0xFF;
	br.cur_img = -1;
	br.list_depth = 0;
	if (br.src_len <= 0) return -1;

	p = br_src;
	end = br_src + br.src_len;

	while (p < end && br.line_count < BR_MAX_LINES) {
		/* ---------- 标签 ---------- */
		if (*p == '<') {
			char name[10];
			int  n = 0;
			int  closing = 0;
			int  ai = 0;
			char *q = p + 1;

			br_tag_attrs[0] = 0;

			if (q < end && *q == '/') { closing = 1; q++; }
			/* 注释 / <!DOCTYPE> / <? ?> */
			if (q < end && (*q == '!' || *q == '?')) {
				if (q + 2 < end && q[1] == '-' && q[2] == '-') {
					p = q + 3;
					while (p + 2 < end &&
					       !(p[0] == '-' && p[1] == '-' && p[2] == '>')) p++;
					p = (p + 2 < end) ? p + 3 : end;
				} else {
					while (q < end && *q != '>') q++;
					p = (q < end) ? q + 1 : end;
				}
				continue;
			}
			/* 标签名 */
			while (q < end && n < 9 &&
			       ((*q >= 'a' && *q <= 'z') || (*q >= 'A' && *q <= 'Z') ||
			        (*q >= '0' && *q <= '9'))) {
				name[n++] = br_lower(*q);
				q++;
			}
			name[n] = 0;
			/* 属性原文 (跳过引号内的 '>') */
			{
				int in_q = 0;
				char qc = 0;
				while (q < end) {
					if (in_q) {
						if (*q == qc) in_q = 0;
					} else if (*q == '>') {
						break;
					} else if (*q == '"' || *q == '\'') {
						in_q = 1;
						qc = *q;
					}
					if (ai < BR_ATTR_MAX - 1) br_tag_attrs[ai++] = *q;
					q++;
				}
				br_tag_attrs[ai] = 0;
				p = (q < end) ? q + 1 : end;
			}

			/* 整段跳过的元素 */
			if (!closing && (br_ieq(name, "head") || br_ieq(name, "script") ||
			                 br_ieq(name, "style") || br_ieq(name, "title"))) {
				p = br_skip_element(p, end, name);
				continue;
			}

			/* 链接: <a href="..."> */
			if (br_ieq(name, "a")) {
				if (closing) {
					link = 0;
				} else {
					char href[BR_URL_MAX];
					if (br_attr("href", href, sizeof(href))) {
						link = br_add_link(href);
					} else {
						link = 0;
					}
				}
				continue;
			}

			/* 标题 */
			if (br_ieq(name, "h1")) {
				br_add_line(cur, cur_link, cur_len, style, BR_LN_TEXT);
				cur_len = 0;
				style = closing ? BR_ST_NORMAL : BR_ST_H1;
				link = 0;
				br_add_blank();
				continue;
			}

			/* 图片: <img src="X.BMP"> */
			if (br_ieq(name, "img") && !closing) {
				char src[BR_URL_MAX];
				if (br_attr("src", src, sizeof(src)) && src[0]) {
					int idx = br_load_bmp(src);
					if (idx >= 0) {
						br_add_line(cur, cur_link, cur_len, style, BR_LN_TEXT);
						cur_len = 0;
						br.cur_img = idx;
						br_add_line(0, 0, 0, style, BR_LN_IMG);
						br.cur_img = -1;
					} else {
						/* 加载失败: 显示占位文字 */
						int i2;
						const char *alt = "[image]";
						br_add_line(cur, cur_link, cur_len, style, BR_LN_TEXT);
						cur_len = 0;
						for (i2 = 0; alt[i2]; i2++) {
							if (cur_len < BR_LINE_MAX - 1) {
								cur[cur_len] = alt[i2];
								cur_link[cur_len] = link;
								cur_len++;
							}
						}
					}
				}
				continue;
			}

			/* 列表 */
			if (br_ieq(name, "ul")) {
				if (!closing) br.list_depth++;
				else if (br.list_depth > 0) br.list_depth--;
				continue;
			}
			if (br_ieq(name, "li") && !closing) {
				int k2;
				br_add_line(cur, cur_link, cur_len, style, BR_LN_TEXT);
				cur_len = 0;
				/* 缩进: 每层 2 空格 */
				for (k2 = 0; k2 < br.list_depth * 2 && cur_len < BR_LINE_MAX - 4; k2++) {
					cur[cur_len] = ' ';
					cur_link[cur_len] = 0;
					cur_len++;
				}
				/* 项目符号: "* " */
				if (cur_len < BR_LINE_MAX - 3) {
					cur[cur_len] = '*';
					cur_link[cur_len] = 0;
					cur_len++;
					cur[cur_len] = ' ';
					cur_link[cur_len] = 0;
					cur_len++;
				}
				continue;
			}

			/* 段落 */
			if (br_ieq(name, "p")) {
				br_add_line(cur, cur_link, cur_len, style, BR_LN_TEXT);
				cur_len = 0;
				link = 0;
				if (!closing) br_add_blank();
				continue;
			}

			/* 换行 / 分隔线 */
			if (br_ieq(name, "br")) {
				br_add_line(cur, cur_link, cur_len, style, BR_LN_TEXT);
				cur_len = 0;
				continue;
			}
			if (br_ieq(name, "hr")) {
				br_add_line(cur, cur_link, cur_len, style, BR_LN_TEXT);
				cur_len = 0;
				br_add_line(0, 0, 0, style, BR_LN_HR);
				continue;
			}
			/* 其他标签: 忽略, 保留文字 */
			continue;
		}

		/* ---------- 文字 ---------- */
		{
			char c = *p++;

			if (c == '\r') continue;
			if (c == '\n' || c == '\t' || c == ' ') {
				if (cur_len > 0 && cur_len < BR_LINE_MAX - 1 &&
				    cur[cur_len - 1] != ' ') {
					cur[cur_len] = ' ';
					cur_link[cur_len] = link;
					cur_len++;
	cur_fg_buf[cur_len] = br.cur_fg;
				}
				continue;
			}
			if (c == '&') {
				if (br_ipre(p, "amp;"))       { c = '&';  p += 4; }
				else if (br_ipre(p, "lt;"))    { c = '<';  p += 3; }
				else if (br_ipre(p, "gt;"))    { c = '>';  p += 3; }
				else if (br_ipre(p, "quot;"))  { c = '"';  p += 5; }
				else if (br_ipre(p, "apos;"))  { c = '\''; p += 5; }
				else if (br_ipre(p, "nbsp;"))  { c = ' ';  p += 5; }
				else {
					char *r = p;
					int k = 0;
					while (r < end && *r != ';' && k < 10) { r++; k++; }
					if (r < end && *r == ';') { p = r + 1; continue; }
					c = '&';
				}
			}
			if ((t_8)c >= 0x80) {
				/* 非 ASCII: 无字形, 用 '.' 占位并跳过 UTF-8 续字节 */
				c = '.';
				while (p < end && ((t_8)*p & 0xC0) == 0x80) p++;
			}
			/* 控制字符 (含内嵌 NUL) 丢弃 */
			if ((t_8)c < 32) continue;
			/* 单行超缓冲: 先落行再继续 (排版时还会折行) */
			if (cur_len >= BR_LINE_MAX - 1) {
				br_add_line(cur, cur_link, cur_len, style, BR_LN_TEXT);
				cur_len = 0;
			}
			cur[cur_len] = c;
			cur_link[cur_len] = link;
			cur_len++;
	cur_fg_buf[cur_len] = br.cur_fg;
		}
	}

	br_add_line(cur, cur_link, cur_len, style, BR_LN_TEXT);
	if (br.line_count == 0) return -1;
	return 0;
}

/*======================================================================*
                          页面生成 (内置页面)
 *======================================================================*/

PRIVATE void br_gen_reset(void)
{
	br_gen_p = br_src;
	br_gen_left = BR_SRC_MAX - 1;
	*br_gen_p = 0;
}

PRIVATE void br_gen_ch(char c)
{
	if (br_gen_left > 0) {
		*br_gen_p++ = c;
		br_gen_left--;
		*br_gen_p = 0;
	}
}

PRIVATE void br_gen_str(const char *s)
{
	while (*s) br_gen_ch(*s++);
}

PRIVATE void br_gen_int(int v)
{
	char b[12];
	int n = 0;

	if (v < 0) { br_gen_ch('-'); v = -v; }
	if (v == 0) b[n++] = '0';
	while (v > 0 && n < 11) { b[n++] = (char)('0' + v % 10); v /= 10; }
	while (n > 0) br_gen_ch(b[--n]);
}

PRIVATE int br_gen_len(void)
{
	return (int)(br_gen_p - br_src);
}

/* 把 URL 安全地写进 HTML (过滤掉 '<' '&' 等) */
PRIVATE void br_gen_text(const char *s)
{
	while (s && *s) {
		char c = *s++;
		if (c == '<') c = '(';
		else if (c == '>') c = ')';
		else if ((t_8)c >= 0x80 || c < 32) c = '.';
		br_gen_ch(c);
	}
}

/* 生成 about:home */
PRIVATE void br_gen_home(void)
{
	br_gen_reset();
	br_gen_str("<h1>CatOS Browser</h1>\n<hr>\n");
	br_gen_str("<p>Welcome to the built-in browser. It runs inside the CatOS "
	           "kernel and only reads HTML files from the local FAT disk. "
	           "There is no network support at all.</p>\n");
	br_gen_str("<h1>Quick links</h1>\n");
	br_gen_str("<p><a href=\"about:files\">about:files</a> - list files in the disk root</p>\n");
	br_gen_str("<p><a href=\"about:help\">about:help</a> - supported HTML tags</p>\n");
	br_gen_str("<p><a href=\"" BR_DEFAULT_FILE "\">" BR_DEFAULT_FILE "</a> - the sample page</p>\n");
	br_gen_str("<h1>How to use</h1>\n");
	br_gen_str("<p>Type a file name in the address bar and press Enter. "
	           "Click blue links to follow them. LEFT and RIGHT arrows go back "
	           "and forward in history. PageUp and PageDown scroll the page, "
	           "F5 reloads it, and ESC leaves the desktop.</p>\n");
}

/* 生成 about:help */
PRIVATE void br_gen_help(void)
{
	br_gen_reset();
	br_gen_str("<h1>Supported HTML</h1>\n<hr>\n");
	br_gen_str("<p><b>&lt;h1&gt; ... &lt;/h1&gt;</b> - heading: blue, bold, "
	           "with a blank line before and after</p>\n");
	br_gen_str("<p><b>&lt;p&gt; ... &lt;/p&gt;</b> - paragraph: wrapped to the "
	           "window width</p>\n");
	br_gen_str("<p><b>&lt;a href=\"file.htm\"&gt; ... &lt;/a&gt;</b> - link: "
	           "click it to open another local page</p>\n");
	br_gen_str("<p><b>&lt;br&gt;</b> - line break, <b>&lt;hr&gt;</b> - rule</p>\n");
	br_gen_str("<p>All other tags are ignored, but the text inside them is kept. "
	           "&lt;head&gt;, &lt;title&gt;, &lt;script&gt; and &lt;style&gt; are "
	           "skipped completely. Entities like &amp;amp; &amp;lt; &amp;gt; "
	           "&amp;quot; &amp;nbsp; are decoded.</p>\n");
	br_gen_str("<h1>Built-in pages</h1>\n");
	br_gen_str("<p><a href=\"about:home\">about:home</a>, "
	           "<a href=\"about:help\">about:help</a>, "
	           "<a href=\"about:files\">about:files</a></p>\n");
	br_gen_str("<p>Non-ASCII characters are shown as '.', because the VGA "
	           "bitmap font only contains ASCII.</p>\n");
}

/* 生成"无网络"页面 */
PRIVATE void br_gen_offline(const char *url)
{
	br_gen_reset();
	br_gen_str("<h1>No network access</h1>\n<hr>\n");
	br_gen_str("<p>CatOS has no network stack, so this address cannot be "
	           "opened:</p>\n<p><b>");
	br_gen_text(url);
	br_gen_str("</b></p>\n");
	br_gen_str("<p>Only local files can be shown. Try a file name such as "
	           "<a href=\"" BR_DEFAULT_FILE "\">" BR_DEFAULT_FILE "</a>, or go "
	           "back to <a href=\"about:home\">about:home</a>.</p>\n");
}

/* 生成磁盘根目录文件列表 (about:files) */
PRIVATE char br_files_name[16];

PRIVATE void br_files_fmt(const FAT_DIR_ENTRY *de, char *out)
{
	int i, j = 0;

	for (i = 0; i < 8 && de->name[i] != ' '; i++) out[j++] = de->name[i];
	if (de->ext[0] != ' ') {
		out[j++] = '.';
		for (i = 0; i < 3 && de->ext[i] != ' '; i++) out[j++] = de->ext[i];
	}
	out[j] = 0;
}

PRIVATE void br_files_cb(FAT_DIR_ENTRY *de)
{
	if (de->name[0] == '.') return;                       /* . / .. */
	if (de->attr & FAT_ATTR_DIRECTORY) return;            /* 子目录暂不列出 */
	if (de->attr & FAT_ATTR_VOLUME_ID) return;
	br_files_fmt(de, br_files_name);
	if (!br_files_name[0]) return;
	br_gen_str("<p><a href=\"");
	br_gen_text(br_files_name);
	br_gen_str("\">");
	br_gen_text(br_files_name);
	br_gen_str("</a> - ");
	br_gen_int((int)de->file_size);
	br_gen_str(" bytes</p>\n");
}

PRIVATE int br_gen_files(void)
{
	br_gen_reset();
	br_gen_str("<h1>Files in /</h1>\n<hr>\n");
	if (fat_init() != 0) {
		br_gen_str("<p>No FAT filesystem found.</p>\n");
	} else {
		fat_list_dir(0, br_files_cb);
		br_gen_str("<p><a href=\"about:home\">back to about:home</a></p>\n");
	}
	return br_gen_len();
}


/*======================================================================*
                          BMP 图片加载 (FAT 根目录)
 *======================================================================*/
PRIVATE t_16 rd16le(const t_8 *p) { return (t_16)(p[0] | (p[1] << 8)); }
PRIVATE t_32 rd32le(const t_8 *p)
{
	return (t_32)p[0] | ((t_32)p[1] << 8) | ((t_32)p[2] << 16) | ((t_32)p[3] << 24);
}

/* 读 BMP 到缓存, 返回索引 (0 起), -1=失败. 支持 4/8/24bpp 非压缩 */
PRIVATE int br_load_bmp(const char *name)
{
	static t_8 buf[BR_IMG_W * BR_IMG_H + 1078];   /* 头+调色板上限 */
	int n, i, j;
	t_32 off, w, h, bpp, dsize;
	int slot;
	BR_IMG *img;

	if (fat_init() != 0) return -1;
	n = fat_read_file_in(0, name, buf, (int)sizeof(buf) - 1);
	if (n < 54) return -1;
	if (buf[0] != 'B' || buf[1] != 'M') return -1;

	off  = rd32le(&buf[10]);
	w    = rd32le(&buf[18]);
	h    = rd32le(&buf[22]);
	bpp  = rd16le(&buf[28]);
	dsize= rd32le(&buf[34]);

	if (w <= 0 || h <= 0 || w > BR_IMG_W || h > BR_IMG_H) return -1;
	if (bpp != 4 && bpp != 8 && bpp != 24) return -1;
	if (dsize == 0) dsize = n - off;
	if (off <= 0 || off >= (t_32)n) return -1;
	if (rd32le(&buf[30]) != 0) return -1;          /* BI_RGB only */

	if (br_img_count >= BR_IMG_MAX) return -1;
	slot = br_img_count;
	img = &br_imgs[slot];

	/* 调色板 */
	if (bpp == 24) {
		for (i = 0; i < 256 * 3; i++) img->pal[i] = 0;
	} else {
		t_32 palcnt = rd32le(&buf[46]);
		t_32 pend;
		if (palcnt == 0) palcnt = (bpp == 4) ? 16 : 256;
		pend = off;
		if (palcnt > 256) palcnt = 256;
		for (i = 0; i < (int)palcnt; i++) {
			const t_8 *e = &buf[pend + i * 4];
			if (e + 3 > &buf[n]) break;
			img->pal[i * 3]     = e[2];   /* BGR -> RGB */
			img->pal[i * 3 + 1] = e[1];
			img->pal[i * 3 + 2] = e[0];
		}
	}

	/* 像素 (BMP 自下而上; 统一转成自上而下的 8bpp 索引) */
	img->w = (int)w;
	img->h = (int)h;
	img->bpp = (int)bpp;
	for (j = 0; j < img->h; j++) {
		int src_y = img->h - 1 - j;                /* 自下而上 */
		const t_8 *row = &buf[off] + (t_32)src_y *
		                  (((w * bpp + 31) / 32) * 4);
		if (row + ((w * bpp + 7) / 8) > &buf[n]) break;
		for (i = 0; i < img->w; i++) {
			int v = 0;
			if (bpp == 24) {
				const t_8 *px = row + i * 3;
				if (px + 2 >= &buf[n]) break;
				/* 24 位转 8bpp: 取亮度, 映射到调色板区 (灰度近似) */
				v = (px[2] * 30 + px[1] * 59 + px[0] * 11) / 100;
				img->px[j * img->w + i] = (t_8)v;
				continue;
			}
			if (bpp == 8) {
				v = row[i];
			} else {                             /* 4bpp */
				v = (i & 1) ? (row[i / 2] & 0x0F) : (row[i / 2] >> 4);
			}
			img->px[j * img->w + i] = (t_8)v;
		}
	}

	img->used = 1;
	br_img_count++;
	(void)dsize;
	return slot;
}
/*======================================================================*
                          导航 / 历史
 *======================================================================*/

PRIVATE void br_update_title(void);   /* 前向声明 (定义在后面) */

/* 判定 URL 类别: 0=本地文件 1=about: 页面 2=外部网络 */
PRIVATE int br_classify(const char *url)
{
	if (br_ipre(url, "about:")) return 1;
	if (br_ipre(url, "http://") || br_ipre(url, "https://") ||
	    br_ipre(url, "ftp://") || br_ipre(url, "www.")) return 2;
	return 0;
}

PRIVATE void br_hist_add(const char *url)
{
	int i;

	if (!url || !*url) return;
	if (br.hist_pos >= 0 && br.hist_pos < br.hist_n &&
	    br_ieq(br_hist[br.hist_pos], url)) {
		return;                                  /* 同一地址不重复记录 */
	}
	if (br.hist_pos + 1 >= BR_HIST_MAX) {        /* 满了: 丢弃最旧的一条 */
		for (i = 0; i < BR_HIST_MAX - 1; i++) {
			br_copy(br_hist[i], br_hist[i + 1], BR_URL_MAX);
		}
		br.hist_pos = BR_HIST_MAX - 2;
		br.hist_n = BR_HIST_MAX - 1;
	}
	br.hist_pos++;
	br_copy(br_hist[br.hist_pos], url, BR_URL_MAX);
	br.hist_n = br.hist_pos + 1;
}

/* 读根目录文件并排版. 返回 0=成功 */
PRIVATE int br_load_file(const char *name)
{
	int n;

	if (fat_init() != 0) {
		br.ok = 0;
		br_set_msg("No FAT filesystem", 0);
		return -1;
	}
	n = fat_read_file_in(0, name, br_src, BR_SRC_MAX - 1);
	if (n < 0) {
		br.ok = 0;
		br_set_msg("File not found: /", name);
		return -1;
	}
	if (n >= BR_SRC_MAX) n = BR_SRC_MAX - 1;
	br_src[n] = 0;
	br.src_len = n;
	if (n == 0) {
		br.ok = 0;
		br_set_msg("Empty file: /", name);
		return -1;
	}
	if (br_parse() != 0) {
		br.ok = 0;
		br_set_msg("No text in /", name);
		return -1;
	}
	br.ok = 1;
	br_set_msg("/", name);
	return 0;
}

/* 把 URL 规范成文件名的形式: 去前导 '/' 与 './' */
PRIVATE void br_to_filename(const char *url, char *out, int max)
{
	const char *s = url;
	while (*s == '/') s++;
	while (s[0] == '.' && s[1] == '/') s += 2;
	while (*s == '/') s++;
	br_copy(out, *s ? s : BR_DEFAULT_FILE, max);
}

/*======================================================================*
                          导航 / 历史
 *======================================================================*/

PRIVATE int br_navigate(const char *url, int record)
{
	char name[16];
	char canon[BR_URL_MAX];
	int cls;
	int i;

	if (!url) return -1;
	while (*url == ' ') url++;
	if (!*url) url = "about:home";

	cls = br_classify(url);

	if (cls == 2) {
		br_gen_offline(url);
		br.src_len = br_gen_len();
		if (br_parse() != 0) { br.ok = 0; br_set_msg("Empty page", 0); return -1; }
		br.ok = 1;
		br_copy(canon, "about:offline", sizeof(canon));
		br.file[0] = 0;
		br_set_msg(canon, 0);
	} else if (cls == 1) {
		if (br_ieq(url + 6, "help")) {
			br_gen_help();
			br_copy(canon, "about:help", sizeof(canon));
		} else if (br_ieq(url + 6, "files")) {
			br.src_len = br_gen_files();
			if (br_parse() != 0) { br.ok = 0; br_set_msg("Empty page", 0); return -1; }
			br.ok = 1;
			br_copy(canon, "about:files", sizeof(canon));
			br.file[0] = 0;
			br_set_msg(canon, 0);
			goto done;
		} else {
			br_gen_home();
			br_copy(canon, "about:home", sizeof(canon));
		}
		br.src_len = br_gen_len();
		if (br_parse() != 0) { br.ok = 0; br_set_msg("Empty page", 0); return -1; }
		br.ok = 1;
		br.file[0] = 0;
		br_set_msg(canon, 0);
	} else {
		char wanted[16];
		br_to_filename(url, wanted, sizeof(wanted));
		for (i = 0; wanted[i] && i < 15; i++) name[i] = br_upper(wanted[i]);
		name[i] = 0;
		br_copy(br.file, name, sizeof(br.file));
		if (br_load_file(name) != 0) {
			br_copy(canon, "/", sizeof(canon));
			br_cat(canon, name, sizeof(canon));
			br_copy(br.url, canon, sizeof(br.url));
			br_copy(br.addr, canon, sizeof(br.addr));
			br.addr_len = br_len(br.addr);
			if (record) br_hist_add(canon);
			return -1;
		}
		br_copy(canon, "/", sizeof(canon));
		br_cat(canon, name, sizeof(canon));
	}

done:
	br_copy(br.url, canon, sizeof(br.url));
	br_copy(br.addr, canon, sizeof(br.addr));
	br.addr_len = br_len(br.addr);
	br.top_row = 0;
	if (record) br_hist_add(canon);
	return 0;
}

PRIVATE int br_history_go(int delta)
{
	int want = br.hist_pos + delta;
	if (want < 0 || want >= br.hist_n) return 0;
	br.hist_pos = want;
	br_navigate(br_hist[want], 0);
	return 1;
}

PUBLIC int br_open(int win_idx, const char *name)
{
	char url[BR_URL_MAX];

	br.win_idx = win_idx;
	br.active = 1;
	br.ok = 0;
	br.top_row = 0;
	br.src_len = 0;
	br.line_count = 0;
	br.link_count = 0;
	br.hist_n = 0;
	br.hist_pos = -1;
	br.addr_focus = 1;
	br.msg[0] = 0;
	br.file[0] = 0;
	br.url[0] = 0;
	br_src[0] = 0;

	if (name && *name) {
		while (*name == '/' || *name == '\\') name++;
		if (br_ipre(name, "about:") || br_ipre(name, "http://") ||
		    br_ipre(name, "https://") || br_ipre(name, "ftp://") ||
		    br_ipre(name, "www.")) {
			br_copy(url, name, sizeof(url));
		} else {
			br_copy(url, "/", sizeof(url));
			br_cat(url, name, sizeof(url));
		}
	} else {
		br_copy(url, "about:home", sizeof(url));
	}

	br_navigate(url, 1);
	return br.ok ? 0 : -1;
}

PRIVATE int br_toolbar_h(void)  { return g_font_height + 6; }
PRIVATE int br_status_h(void)   { return g_font_height + 2; }
PRIVATE int br_btn_w(void)      { return g_font_width + 5; }
PRIVATE int br_content_y(void)  { return br.cl_y + br_toolbar_h(); }
PRIVATE int br_content_h(void)  { return br.cl_h - br_toolbar_h() - br_status_h(); }
PRIVATE int br_text_w(void)     { return br.cl_w - 8; }

PRIVATE int br_addr_x(void)
{
	return br.cl_x + 2 + 4 * br_btn_w() + 2;
}

PRIVATE int br_addr_w(void)
{
	int w = br.cl_w - (4 * br_btn_w() + 8);
	if (w < 4 * g_font_width) w = 4 * g_font_width;
	return w;
}

PRIVATE int br_max_chars(void)
{
	int n = br_text_w() / g_font_width;
	if (n < 1) n = 1;
	return n;
}

/*======================================================================*
                          折行计算
 *======================================================================*/

PRIVATE int br_fit_chars(int li, int start, int max_chars)
{
	const char *s = br_line[li];
	int total = br_len(s);
	int n = 0;
	int last_space = -1;

	if (start >= total) return 0;
	if (max_chars < 1) max_chars = 1;

	while (start + n < total && n < max_chars) {
		if (s[start + n] == ' ') last_space = n;
		n++;
	}
	if (n < 1) n = 1;
	if (start + n < total && last_space > 0 && last_space + 1 < n) {
		n = last_space + 1;
	}
	return n;
}

PRIVATE int br_rows_of_line(int li, int max_chars)
{
	int total;
	int start = 0;
	int rows = 0;

	if (br_line_kind[li] == BR_LN_IMG) {
		int idx = (int)br_line_img[li];
		int rows2 = 1;
		if (idx >= 0 && idx < br_img_count) {
			rows2 = br_imgs[idx].h / g_font_height + 1;
		}
		return rows2;
	}
	if (br_line_kind[li] != BR_LN_TEXT) return 1;
	total = br_len(br_line[li]);
	while (start < total) {
		int n = br_fit_chars(li, start, max_chars);
		if (n <= 0) break;
		start += n;
		rows++;
	}
	if (rows < 1) rows = 1;
	return rows;
}

PRIVATE int br_total_rows(void)
{
	int max_chars = br_max_chars();
	int li;
	int rows = 0;

	for (li = 0; li < br.line_count; li++) {
		rows += br_rows_of_line(li, max_chars);
	}
	return rows;
}

/*======================================================================*
                          绘制
 *======================================================================*/

PRIVATE void br_draw_button(int x, int y, int w, int h, char glyph, int enabled)
{
	t_8 fg = enabled ? BR_COL_BTN_TXT : BR_COL_BTN_DIS;

	fill_rect(x, y, w, h, BR_COL_BAR);
	draw_hline(x, x + w - 1, y, BR_COL_BAR_LIGHT);
	draw_vline(x, y, y + h - 1, BR_COL_BAR_LIGHT);
	draw_hline(x, x + w - 1, y + h - 1, BR_COL_BAR_DARK);
	draw_vline(x + w - 1, y, y + h - 1, BR_COL_BAR_DARK);
	draw_char(x + (w - g_font_width) / 2, y + (h - g_font_height) / 2,
	          glyph, fg, BR_COL_BAR);
}

PRIVATE void br_draw_text(int li, int x, int y, int off, int len, t_8 style)
{
	int i;

	for (i = 0; i < len; i++) {
		char c = br_line[li][off + i];
		t_8 link = br_link_at(li, off + i);
		t_8 fg;

		if (c == ' ' || c < 32 || c > 126) continue;

		if (link > 0 && link <= br.link_count) {
			fg = br_is_visited(br_links[link - 1]) ? BR_COL_VISITED : BR_COL_LINK;
			draw_char(x + i * g_font_width, y, c, fg, br.page_bg);
			draw_hline(x + i * g_font_width, x + (i + 1) * g_font_width - 1,
			           y + g_font_height - 2, fg);
		} else if (style == BR_ST_H1) {
			draw_char_bold(x + i * g_font_width, y, c, BR_COL_H1, br.page_bg);
		} else {
			fg = (br_line_fg[li] != 0xFF) ? br_line_fg[li] : br.page_fg;
			draw_char(x + i * g_font_width, y, c, fg, br.page_bg);
		}
	}
}

PRIVATE void br_draw_toolbar(void)
{
	int th = br_toolbar_h();
	int bh = g_font_height + 1;
	int by = br.cl_y + (th - bh) / 2;
	int i;
	int can_back = (br.hist_pos > 0);
	int can_fwd = (br.hist_pos >= 0 && br.hist_pos + 1 < br.hist_n);
	char glyphs[4];

	glyphs[0] = '<'; glyphs[1] = '>'; glyphs[2] = 'H'; glyphs[3] = 'R';

	fill_rect(br.cl_x, br.cl_y, br.cl_w, th, BR_COL_BAR);
	draw_hline(br.cl_x, br.cl_x + br.cl_w - 1, br.cl_y + th - 1, BR_COL_BAR_DARK);

	for (i = 0; i < 4; i++) {
		int enabled = 1;
		if (i == BR_BTN_BACK) enabled = can_back;
		if (i == BR_BTN_FWD) enabled = can_fwd;
		br_draw_button(br.cl_x + 2 + i * br_btn_w(), by, br_btn_w(), bh,
		               glyphs[i], enabled);
	}

	{
		int ax = br_addr_x();
		int aw = br_addr_w();
		int ay = by;
		int fit = (aw - 6) / g_font_width;
		const char *s = br.addr;
		int n = br.addr_len;

		if (fit < 1) fit = 1;
		fill_rect(ax, ay, aw, bh, BR_COL_ADDR_BG);
		draw_hline(ax, ax + aw - 1, ay, BR_COL_BAR_DARK);
		draw_hline(ax, ax + aw - 1, ay + bh - 1, BR_COL_BAR_DARK);
		draw_vline(ax, ay, ay + bh - 1, BR_COL_BAR_DARK);
		draw_vline(ax + aw - 1, ay, ay + bh - 1, BR_COL_BAR_DARK);

		if (n > fit) { s += n - fit; n = fit; }
		{
			int k;
			int tx = ax + 3;
			int ty = ay + (bh - g_font_height) / 2;
			for (k = 0; k < n; k++) {
				if (s[k] != ' ') {
					draw_char(tx + k * g_font_width, ty, s[k],
					          BR_COL_ADDR_TXT, BR_COL_ADDR_BG);
				}
			}
			if (br.addr_focus) {
				int cx2 = tx + n * g_font_width;
				if (cx2 + g_font_width > ax + aw - 2) cx2 = ax + aw - 2 - g_font_width;
				draw_vline(cx2, ty - 1, ty + g_font_height - 1, BR_COL_ADDR_TXT);
			}
		}
	}
}

PUBLIC void br_draw_client(int win_idx, int cx, int cy, int cw, int ch)
{
	int status_h = br_status_h();
	int text_h;
	int max_chars;
	int li;
	int y;
	int first_li;
	int first_start = 0;
	int skip;

	if (win_idx != br.win_idx) return;
	if (cw <= 0 || ch <= 0) return;

	br.cl_x = cx;
	br.cl_y = cy;
	br.cl_w = cw;
	br.cl_h = ch;

	fill_rect(cx, cy, cw, ch, br.page_bg);

	text_h = br_content_h();
	if (text_h < g_font_height) text_h = g_font_height;
	max_chars = br_max_chars();

	if (!br.ok || br.line_count == 0) {
		draw_string(cx + 4, cy + br_toolbar_h() + 4,
		            br.msg[0] ? br.msg : "Nothing to show",
		            BR_COL_ERR, br.page_bg);
	} else {
		first_li = br.line_count;
		skip = br.top_row;
		for (li = 0; li < br.line_count; li++) {
			int rows = br_rows_of_line(li, max_chars);
			if (skip <= 0) { first_li = li; first_start = 0; break; }
			if (skip >= rows) { skip -= rows; continue; }
			{
				int start = 0;
				int k;
				for (k = 0; k < skip; k++) {
					int n = br_fit_chars(li, start, max_chars);
					if (n <= 0) break;
					start += n;
				}
				first_li = li;
				first_start = start;
			}
			break;
		}

		y = br_content_y() + 2;
		for (li = first_li; li < br.line_count; li++) {
			if (br_line_kind[li] == BR_LN_BLANK) {
				if (y + g_font_height / 2 > br_content_y() + text_h) break;
				y += g_font_height / 2 + 2;
			} else if (br_line_kind[li] == BR_LN_HR) {
				if (y + g_font_height / 2 > br_content_y() + text_h) break;
				draw_hline(cx + 4, cx + cw - 5, y + g_font_height / 4, BR_COL_HR);
				y += g_font_height / 2 + 2;
			} else if (br_line_kind[li] == BR_LN_IMG) {
				int idx = (int)br_line_img[li];
				int ih;
				if (idx >= 0 && idx < br_img_count) {
					int pi2, pj2;
					ih = br_imgs[idx].h;
					for (pj2 = 0; pj2 < ih; pj2++) {
						if (y + pj2 >= br_content_y() + text_h) break;
						for (pi2 = 0; pi2 < br_imgs[idx].w; pi2++) {
							t_8 pi = br_imgs[idx].px[pj2 * br_imgs[idx].w + pi2];
							t_8 pr, pg, pb;
							if (br_imgs[idx].bpp == 24) {
								put_pixel(cx + 4 + pi2, y + pj2, pi);
							} else if (pi * 3 + 2 < (int)sizeof(br_imgs[idx].pal)) {
								pr = br_imgs[idx].pal[pi * 3];
								pg = br_imgs[idx].pal[pi * 3 + 1];
								pb = br_imgs[idx].pal[pi * 3 + 2];
								put_pixel(cx + 4 + pi2, y + pj2,
								          32 + (pr * 5 / 255) * 36 +
								          (pg * 5 / 255) * 6 + (pb * 5 / 255));
							}
						}
					}
				}
				y += ih + g_font_height / 2;
			} else if (br_line_kind[li] == BR_LN_LIST) {
				int total = br_len(br_line[li]);
				int start = (li == first_li) ? first_start : 0;
				int indent = g_font_width * 2;

				if (start == 0 && y + g_font_height <= br_content_y() + text_h) {
					int bx = cx + 4 + indent - g_font_width - 2;
					int by = y + g_font_height / 2 - 1;
					fill_rect(bx, by, 3, 3, br.page_fg);
				}
				while (start < total) {
					int n = br_fit_chars(li, start, max_chars - 2);
					if (n <= 0) break;
					if (y + g_font_height > br_content_y() + text_h) break;
					br_draw_text(li, cx + 4 + indent, y, start, n, br_line_st[li]);
					y += g_font_height;
					start += n;
				}
			} else {
				int total = br_len(br_line[li]);
				int start = (li == first_li) ? first_start : 0;
				while (start < total) {
					int n = br_fit_chars(li, start, max_chars);
					if (n <= 0) break;
					if (y + g_font_height > br_content_y() + text_h) break;
					br_draw_text(li, cx + 4, y, start, n, br_line_st[li]);
					y += g_font_height;
					start += n;
				}
			}
		}
	}

	br_draw_toolbar();

	{
		int sy = cy + ch - status_h;
		int hint_x = cx + cw - 9 * g_font_width;
		fill_rect(cx, sy, cw, status_h, BR_COL_STATUS);
		draw_string(cx + 4, sy + 1, br.msg, BR_COL_BAR_LIGHT, BR_COL_STATUS);
		if (hint_x > cx + 4) {
			draw_string(hint_x, sy + 1, "PgUp/PgDn", BR_COL_BAR_LIGHT, BR_COL_STATUS);
		}
	}
}

/*======================================================================*
                          命中测试
 *======================================================================*/

PRIVATE int br_hit_button(int mx, int my)
{
	int bh = g_font_height + 1;
	int by = br.cl_y + (br_toolbar_h() - bh) / 2;
	int i;

	if (my < by || my >= by + bh) return -1;
	for (i = 0; i < 4; i++) {
		int x = br.cl_x + 2 + i * br_btn_w();
		if (mx >= x && mx < x + br_btn_w()) return i;
	}
	return -1;
}

PRIVATE int br_hit_addr(int mx, int my)
{
	int bh = g_font_height + 1;
	int by = br.cl_y + (br_toolbar_h() - bh) / 2;

	if (my < by || my >= by + bh) return 0;
	return (mx >= br_addr_x() && mx < br_addr_x() + br_addr_w()) ? 1 : 0;
}

PRIVATE int br_row_at(int my, int *out_li, int *out_start)
{
	int max_chars = br_max_chars();
	int text_h = br_content_h();
	int li;
	int y = br_content_y() + 2;
	int skip = br.top_row;

	if (text_h < g_font_height) text_h = g_font_height;

	for (li = 0; li < br.line_count; li++) {
		if (br_line_kind[li] == BR_LN_BLANK) {
			int h = g_font_height / 2 + 2;
			if (y + h > br_content_y() + text_h) return 0;
			if (skip > 0) { skip--; y += h; continue; }
			if (my >= y && my < y + h) return 0;
			y += h;
		} else if (br_line_kind[li] == BR_LN_HR) {
			int h = g_font_height / 2 + 2;
			if (y + h > br_content_y() + text_h) return 0;
			if (skip > 0) { skip--; y += h; continue; }
			if (my >= y && my < y + h) return 0;
			y += h;
		} else {
			int total = br_len(br_line[li]);
			int start = 0;
			while (start < total) {
				int n = br_fit_chars(li, start, max_chars);
				if (n <= 0) break;
				if (y + g_font_height > br_content_y() + text_h) return 0;
				if (skip > 0) { skip--; y += g_font_height; start += n; continue; }
				if (my >= y && my < y + g_font_height) {
					*out_li = li;
					*out_start = start;
					return 1;
				}
				y += g_font_height;
				start += n;
			}
		}
	}
	return 0;
}

/*======================================================================*
                          键盘
 *======================================================================*/

PUBLIC int br_handle_key(int win_idx, t_32 key)
{
	int total;
	int page;
	int cl_h;

	if (win_idx != br.win_idx) return 0;

	if (!(key & FLAG_EXT)) {
		char c = (char)(key & 0xFF);
		if (c >= 32 && c <= 126) {
			if (br.addr_len < BR_URL_MAX - 1) {
				br.addr[br.addr_len] = c;
				br.addr_len++;
				br.addr[br.addr_len] = 0;
			}
			br.addr_focus = 1;
			return 1;
		}
		return 0;
	}

	if (key == ENTER) {
		char url[BR_URL_MAX];
		br_copy(url, br.addr, sizeof(url));
		br_navigate(url, 1);
		br.addr_focus = 1;
		return 1;
	}
	if (key == BACKSPACE) {
		if (br.addr_len > 0) {
			br.addr_len--;
			br.addr[br.addr_len] = 0;
		}
		br.addr_focus = 1;
		return 1;
	}
	if (key == LEFT)  { br_history_go(-1); return 1; }
	if (key == RIGHT) { br_history_go(1);  return 1; }
	if (key == F5) {
		br_navigate(br.url[0] ? br.url : "about:home", 0);
		return 1;
	}

	cl_h = br_content_h();
	if (cl_h <= 0) cl_h = g_font_height * 8;
	page = (cl_h - g_font_height * 2) / g_font_height;
	if (page < 1) page = 1;

	if (key == PAGEDOWN)      br.top_row += page;
	else if (key == PAGEUP)   br.top_row -= page;
	else if (key == DOWN)     br.top_row += 1;
	else if (key == UP)       br.top_row -= 1;
	else if (key == HOME)     br.top_row = 0;
	else if (key == END)      br.top_row = br_total_rows() - 1;
	else return 0;

	total = br_total_rows();
	if (br.top_row > total - 1) br.top_row = total - 1;
	if (br.top_row < 0) br.top_row = 0;
	return 1;
}

/*======================================================================*
                          鼠标
 *======================================================================*/

PUBLIC int br_handle_click(int win_idx, int mx, int my)
{
	int b;

	if (win_idx != br.win_idx) return 0;

	if (my >= br.cl_y && my < br.cl_y + br_toolbar_h()) {
		b = br_hit_button(mx, my);
		if (b == BR_BTN_BACK) {
			if (!br_history_go(-1)) br_set_msg("No previous page", 0);
			return 1;
		}
		if (b == BR_BTN_FWD) {
			if (!br_history_go(1)) br_set_msg("No next page", 0);
			return 1;
		}
		if (b == BR_BTN_HOME) {
			br_navigate("about:home", 1);
			return 1;
		}
		if (b == BR_BTN_RELOAD) {
			br_navigate(br.url[0] ? br.url : "about:home", 0);
			return 1;
		}
		br.addr_focus = br_hit_addr(mx, my);
		return 1;
	}

	{
		int li = 0;
		int start = 0;
		if (br_row_at(my, &li, &start)) {
			int col = (mx - (br.cl_x + 4)) / g_font_width;
			int total = br_len(br_line[li]);
			int idx;
			if (col < 0) col = 0;
			idx = start + col;
			if (idx >= 0 && idx < total) {
				t_8 id = br_link_at(li, idx);
				if (id > 0 && id <= br.link_count) {
					br_navigate(br_links[id - 1], 1);
					br.addr_focus = 1;
					return 1;
				}
			}
		}
		br.addr_focus = 0;
	}
	return 1;
}

/*======================================================================*
                          生命周期
 *======================================================================*/

PUBLIC int br_is_window(int win_idx)
{
	return (br.active && win_idx == br.win_idx) ? 1 : 0;
}

PUBLIC void br_reset(void)
{
	int i;

	br.win_idx = -1;
	br.active = 0;
	br.ok = 0;
	br.src_len = 0;
	br.line_count = 0;
	br.top_row = 0;
	br.link_count = 0;
	br.cl_x = br.cl_y = br.cl_w = br.cl_h = 0;
	br.addr_len = 0;
	br.addr[0] = 0;
	br.addr_focus = 1;
	br.hist_n = 0;
	br.hist_pos = -1;
	br.msg[0] = 0;
	br.file[0] = 0;
	br.url[0] = 0;
	for (i = 0; i < BR_MAX_LINES; i++) {
		br_line[i][0] = 0;
		br_line_kind[i] = BR_LN_TEXT;
		br_line_st[i] = BR_ST_NORMAL;
	}
}
