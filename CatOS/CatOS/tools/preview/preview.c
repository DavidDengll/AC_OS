/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
              tools/preview/preview.c — 宿主侧渲染预览

  用途:
    在没有 QEMU/Bochs 的机器上, 直接编译 kernel/browser.c 并用真实的
    8x16 位图字体把它渲染成一张 BMP 图片, 用来检查排版/折行/翻页是否正常.

  编译 (在 tools/preview 目录):
    gcc -I shim -I ../../include -O1 -o preview.exe preview.c ../../kernel/browser.c

  用法:
    python mkfont.py ../../kernel/gfx.c font8x16.bin
    ./preview.exe font8x16.bin ../../samples/INDEX.HTM out.bmp 640 480 [pagedowns]

  说明:
    - 只实现了 browser.c 依赖的少量外部符号 (绘制原语 / FAT 读取)
    - FAT 读取被替换成"直接读宿主机文件", 以便加载示例页面
    - 调色板与 kernel/gfx.c: gfx_set_palette 保持一致
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#include <stdio.h>
#include <stdlib.h>

#include "type.h"
#include "const.h"
#include "gfx.h"
#include "keyboard.h"
#include "fat.h"
#include "browser.h"

/* 注意: 不能包含 <string.h> — shim 目录里有一个同名空头文件会把它遮蔽,
 * 所以这里用本地实现代替 memset/memcpy */
static void pv_memset(void *dst, int c, int n)
{
	unsigned char *p = (unsigned char *)dst;
	int i;
	for (i = 0; i < n; i++) p[i] = (unsigned char)c;
}

/* ===== gfx.c 中的全局参数 ===== */
int g_font_width = 8;
int g_font_height = 16;

/* ===== 帧缓冲 ===== */
static unsigned char *g_fb;
static int g_w, g_h;

/* ===== 8x16 字体 ===== */
static unsigned char g_font[95 * 16];   /* ASCII 32..126 */

/* 待加载的页面文件 (模拟 FAT 里的 INDEX.HTM) */
static const char *g_page_path;

/* ===== 字符网格: 把渲染结果以文本形式打印出来核对排版 ===== */
#define GRID_ROWS 68
#define GRID_COLS 240
static char g_grid[GRID_ROWS][GRID_COLS + 1];

static void grid_dump(int x0, int y0, int x1, int y1)
{
	int r, c, last;
	int c0 = x0 / g_font_width, c1 = x1 / g_font_width;
	int r0 = y0 / g_font_height, r1 = y1 / g_font_height;

	if (c0 < 0) c0 = 0;
	if (r0 < 0) r0 = 0;
	if (c1 > GRID_COLS - 1) c1 = GRID_COLS - 1;
	if (r1 > GRID_ROWS - 1) r1 = GRID_ROWS - 1;

	printf("+");
	for (c = c0; c <= c1; c++) printf("-");
	printf("+\n");
	for (r = r0; r <= r1; r++) {
		last = c1;
		while (last >= c0 && g_grid[r][last] == ' ') last--;
		printf("|");
		for (c = c0; c <= last; c++) printf("%c", g_grid[r][c]);
		printf("\n");
	}
	printf("+");
	for (c = c0; c <= c1; c++) printf("-");
	printf("+\n");
}

/*======================================================================
  调色板: 与 kernel/gfx.c: gfx_set_palette 完全一致
    0~15   CGA/EGA 基本色
    16~31  16 级灰度
    32~247 6x6x6 颜色立方体
    248~255 黑
======================================================================*/
static void palette_rgb(int idx, int *r, int *g, int *b)
{
	static const unsigned char cga[16][3] = {
		{0x00,0x00,0x00}, {0x00,0x00,0x2A}, {0x00,0x2A,0x00}, {0x00,0x2A,0x2A},
		{0x2A,0x00,0x00}, {0x2A,0x00,0x2A}, {0x2A,0x15,0x00}, {0x2A,0x2A,0x2A},
		{0x15,0x15,0x15}, {0x15,0x15,0x3F}, {0x15,0x3F,0x15}, {0x15,0x3F,0x3F},
		{0x3F,0x15,0x15}, {0x3F,0x15,0x3F}, {0x3F,0x3F,0x15}, {0x3F,0x3F,0x3F},
	};

	if (idx < 0) idx = 0;
	if (idx < 16) {
		*r = cga[idx][0] * 255 / 63;
		*g = cga[idx][1] * 255 / 63;
		*b = cga[idx][2] * 255 / 63;
	} else if (idx < 32) {
		int v = (idx - 16) * 63 / 15;
		*r = *g = *b = v * 255 / 63;
	} else if (idx < 248) {
		int i = idx - 32;
		*r = (i / 36) * 63 / 5 * 255 / 63;
		*g = ((i / 6) % 6) * 63 / 5 * 255 / 63;
		*b = (i % 6) * 63 / 5 * 255 / 63;
	} else {
		*r = *g = *b = 0;
	}
}

/*======================================================================
  绘制原语 (仅实现 browser.c 用到的部分)
======================================================================*/
void put_pixel(int x, int y, t_8 color)
{
	if (!g_fb) return;
	if (x < 0 || x >= g_w || y < 0 || y >= g_h) return;
	g_fb[y * g_w + x] = color;
}

void fill_rect(int x, int y, int w, int h, t_8 color)
{
	int i, j;
	if (w <= 0 || h <= 0) return;
	for (j = 0; j < h; j++)
		for (i = 0; i < w; i++)
			put_pixel(x + i, y + j, color);
}

void draw_hline(int x1, int x2, int y, t_8 color)
{
	int x;
	if (x2 < x1) { int t = x1; x1 = x2; x2 = t; }
	for (x = x1; x <= x2; x++) put_pixel(x, y, color);
}

void draw_vline(int x, int y1, int y2, t_8 color)
{
	int y;
	if (y2 < y1) { int t = y1; y1 = y2; y2 = t; }
	for (y = y1; y <= y2; y++) put_pixel(x, y, color);
}

void draw_char(int x, int y, char ch, t_8 fg, t_8 bg)
{
	int row, col, sx, sy;
	int scale_x = g_font_width / 8;
	int scale_y = g_font_height / 16;
	int idx;

	if (ch < 32 || ch > 126) ch = '?';
	if (scale_x < 1) scale_x = 1;
	if (scale_y < 1) scale_y = 1;
	idx = (ch - 32) * 16;

	/* 记录字符网格 (只记非空白, 用于文本形式核对排版) */
	if (ch != ' ') {
		int gr = y / g_font_height;
		int gc = x / g_font_width;
		if (gr >= 0 && gr < GRID_ROWS && gc >= 0 && gc < GRID_COLS) {
			g_grid[gr][gc] = ch;
		}
	}

	for (row = 0; row < 16; row++) {
		unsigned char bitmap = g_font[idx + row];
		for (col = 0; col < 8; col++) {
			int on = (bitmap & (0x80 >> col)) ? 1 : 0;
			if (!on && bg < 0) continue;
			for (sy = 0; sy < scale_y; sy++) {
				for (sx = 0; sx < scale_x; sx++) {
					put_pixel(x + col * scale_x + sx,
					          y + row * scale_y + sy,
					          on ? fg : bg);
				}
			}
		}
	}
}

void draw_char_bold(int x, int y, char ch, t_8 fg, t_8 bg)
{
	int row, col, sx, sy;
	int scale_x = g_font_width / 8;
	int scale_y = g_font_height / 16;
	int idx;

	if (ch < 32 || ch > 126) ch = '?';
	if (scale_x < 1) scale_x = 1;
	if (scale_y < 1) scale_y = 1;
	idx = (ch - 32) * 16;

	if (ch != ' ') {
		int gr = y / g_font_height;
		int gc = x / g_font_width;
		if (gr >= 0 && gr < GRID_ROWS && gc >= 0 && gc < GRID_COLS) {
			g_grid[gr][gc] = ch;
		}
	}

	for (row = 0; row < 16; row++) {
		unsigned char bmp = g_font[idx + row];
		unsigned char bold = (unsigned char)(bmp | (bmp >> 1));
		for (col = 0; col < 8; col++) {
			int on = (bold & (0x80 >> col)) ? 1 : 0;
			if (!on && bg < 0) continue;
			for (sy = 0; sy < scale_y; sy++) {
				for (sx = 0; sx < scale_x; sx++) {
					put_pixel(x + col * scale_x + sx,
					          y + row * scale_y + sy,
					          on ? fg : bg);
				}
			}
		}
	}
}

void draw_string(int x, int y, const char *str, t_8 fg, t_8 bg)
{
	int cx = x;
	while (*str) {
		draw_char(cx, y, *str, fg, bg);
		cx += g_font_width;
		str++;
	}
}

/*======================================================================
  FAT 接口 (模拟): 直接读取宿主机上的示例文件
======================================================================*/
int fat_init(void)
{
	return 0;
}

int fat_read_file_in(t_32 dir_cluster, const char *name, void *buf, int bufsize)
{
	FILE *f;
	int n;

	(void)dir_cluster;
	(void)name;
	if (!g_page_path) return -1;
	f = fopen(g_page_path, "rb");
	if (!f) return -1;
	n = (int)fread(buf, 1, (size_t)bufsize, f);
	fclose(f);
	return n;
}

/*======================================================================
  BMP 输出 (24 位真彩色)
======================================================================*/
static void write_bmp(const char *path)
{
	FILE *f;
	int row_bytes = (g_w * 3 + 3) & ~3;
	int data_size = row_bytes * g_h;
	int file_size = 54 + data_size;
	unsigned char hdr[54];
	int x, y;

	pv_memset(hdr, 0, sizeof(hdr));
	hdr[0] = 'B'; hdr[1] = 'M';
	hdr[2] = (unsigned char)(file_size);
	hdr[3] = (unsigned char)(file_size >> 8);
	hdr[4] = (unsigned char)(file_size >> 16);
	hdr[5] = (unsigned char)(file_size >> 24);
	hdr[10] = 54;
	hdr[14] = 40;
	hdr[18] = (unsigned char)(g_w);
	hdr[19] = (unsigned char)(g_w >> 8);
	hdr[20] = (unsigned char)(g_w >> 16);
	hdr[21] = (unsigned char)(g_w >> 24);
	hdr[22] = (unsigned char)(g_h);
	hdr[23] = (unsigned char)(g_h >> 8);
	hdr[24] = (unsigned char)(g_h >> 16);
	hdr[25] = (unsigned char)(g_h >> 24);
	hdr[26] = 1;
	hdr[28] = 24;
	hdr[34] = (unsigned char)(data_size);
	hdr[35] = (unsigned char)(data_size >> 8);
	hdr[36] = (unsigned char)(data_size >> 16);
	hdr[37] = (unsigned char)(data_size >> 24);

	f = fopen(path, "wb");
	if (!f) { printf("cannot write %s\n", path); return; }
	fwrite(hdr, 1, 54, f);

	for (y = g_h - 1; y >= 0; y--) {
		for (x = 0; x < g_w; x++) {
			int r, g, b;
			palette_rgb(g_fb[y * g_w + x], &r, &g, &b);
			fputc(b, f); fputc(g, f); fputc(r, f);
		}
		for (x = g_w * 3; x < row_bytes; x++) fputc(0, f);
	}
	fclose(f);
	printf("preview written: %s (%dx%d)\n", path, g_w, g_h);
}

/*======================================================================
  主程序
======================================================================*/
int main(int argc, char **argv)
{
	FILE *f;
	int win_x, win_y, win_w, win_h, title_h, border;
	int cx, cy, cw, ch;
	int pagedowns = 0;
	int i;

	/* 字符网格初始化为空格 */
	for (i = 0; i < GRID_ROWS; i++) {
		int c;
		for (c = 0; c < GRID_COLS; c++) g_grid[i][c] = ' ';
		g_grid[i][GRID_COLS] = 0;
	}

	if (argc < 6) {
		printf("usage: %s <font.bin> <page.html> <out.bmp> <W> <H> [pagedowns]\n", argv[0]);
		return 1;
	}

	f = fopen(argv[1], "rb");
	if (!f) { printf("cannot open font %s\n", argv[1]); return 1; }
	if (fread(g_font, 1, sizeof(g_font), f) != sizeof(g_font)) {
		printf("font file too small (need %d bytes)\n", (int)sizeof(g_font));
		fclose(f);
		return 1;
	}
	fclose(f);

	g_page_path = argv[2];
	g_w = atoi(argv[4]);
	g_h = atoi(argv[5]);
	if (argc > 6) pagedowns = atoi(argv[6]);
	if (g_w < 200 || g_h < 150 || g_w > 1920 || g_h > 1080) {
		printf("bad screen size\n");
		return 1;
	}

	/* 与 gfx_init 相同的字体缩放规则 */
	if (g_w >= 1024 || g_h >= 768) {
		g_font_width = 16;
		g_font_height = 32;
	} else {
		g_font_width = 8;
		g_font_height = 16;
	}

	g_fb = (unsigned char *)malloc((size_t)g_w * g_h);
	if (!g_fb) { printf("out of memory\n"); return 1; }
	pv_memset(g_fb, 0, g_w * g_h);

	/* 桌面背景 (WM_COL_DESKTOP = 0x01) */
	fill_rect(0, 0, g_w, g_h, 0x01);

	/* 浏览器窗口几何: 与 wm.c: wm_create_browser 一致 */
	win_x = g_w / 10;
	win_y = g_h / 10;
	win_w = g_w * 4 / 5;
	win_h = g_h * 3 / 4;
	title_h = g_font_height + 6;
	border = 3;

	/* 阴影 */
	fill_rect(win_x + 3, win_y + 3, win_w, win_h, 0x08);
	/* 窗口底板 */
	fill_rect(win_x, win_y, win_w, win_h, 0x0F);
	/* 标题栏 (活动窗口: 亮青) */
	fill_rect(win_x, win_y, win_w, title_h, 0x09);
	fill_rect(win_x, win_y, win_w, title_h / 2, 0x0B);
	draw_string(win_x + 6, win_y + (title_h - g_font_height) / 2,
	            "Browser - INDEX.HTM", 0x0F, 0x0B);
	/* 标题栏三个按钮 (装饰) */
	{
		int bw = g_font_height - 4;
		int bx = win_x + win_w - bw - 4;
		int by = win_y + (title_h - bw) / 2;
		int k;
		for (k = 0; k < 3; k++) {
			fill_rect(bx - k * (bw + 2), by, bw, bw, 0x07);
		}
	}

	/* 客户区 */
	cx = win_x + border;
	cy = win_y + title_h;
	cw = win_w - 2 * border;
	ch = win_h - title_h - border;

	if (br_open(0, "INDEX.HTM") != 0) {
		printf("note: br_open failed (page still shows the error message)\n");
	}
	for (i = 0; i < pagedowns; i++) br_handle_key(0, PAGEDOWN);

	br_draw_client(0, cx, cy, cw, ch);

	/* 以文本形式打印窗口内容, 便于在纯文本环境核对排版 */
	printf("\n=== text render: window %dx%d at (%d,%d), client %dx%d ===\n",
	       win_w, win_h, win_x, win_y, cw, ch);
	grid_dump(win_x, win_y, win_x + win_w - 1, win_y + win_h - 1);

	write_bmp(argv[3]);
	free(g_fb);
	return 0;
}

/*======================================================================
  WM 接口桩 / 目录列表桩 (供 about:files 页面使用)
======================================================================*/
void wm_set_window_title(int idx, const char *title)
{
	(void)idx;
	(void)title;
}

void fat_list_dir(t_32 dir_cluster, void (*callback)(FAT_DIR_ENTRY *))
{
	FAT_DIR_ENTRY de;
	int i;

	(void)dir_cluster;
	if (!callback) return;
	for (i = 0; i < 8; i++) de.name[i] = ' ';
	for (i = 0; i < 3; i++) de.ext[i] = ' ';
	de.name[0] = 'I'; de.name[1] = 'N'; de.name[2] = 'D';
	de.name[3] = 'E'; de.name[4] = 'X';
	de.ext[0] = 'H'; de.ext[1] = 'T'; de.ext[2] = 'M';
	de.attr = FAT_ATTR_ARCHIVE;
	de.file_size = 1567;
	de.start_cluster = 3;
	callback(&de);
}