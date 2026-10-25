/*======================================================================
  mouselock.c — CatOS Pointer Lock 演示  v2 (带逐步诊断)
  每一步失败都会在控制台打印死因和 code, 再退出。
======================================================================*/

/* ---- SDK (crt0.asm) ---- */
extern int  win_create(int x, int y, int w, int h, char *title);
extern void win_close(int win_id);
extern void win_clear(int win_id, int color);
extern void win_draw_text(int win_id, int x, int y, char *str, int fg, int bg);
extern void win_draw_rect(int win_id, int x, int y, int w, int h, int color);
extern void win_draw_line(int win_id, int x1, int y1, int x2, int y2, int color);
extern int  win_get_event(int win_id, int *type, int *x, int *y);
extern int  win_get_size(int win_id, int *w, int *h);
extern int  win_lock_mouse(int win_id, int on);
extern int  int_to_str(int value, char *buf, int radix);
extern void puts(char *str);
extern void putc(int ch);
extern void exit(int code);

#define EV_LDOWN     1
#define EV_KEY       4
#define EV_CLOSE     5
#define EV_MOUSE_REL 6

#define C_DARKGRY 0x08
#define C_BLUE    0x01
#define C_GREEN   0x02
#define C_RED     0x04
#define C_YELLOW  0x0E
#define C_WHITE   0x0F
#define C_CYAN    0x0B

#define REL_LIMIT 400

static int g_win = -1, g_w = 0, g_h = 0;
static int g_yaw = 0, g_pitch = 0, g_shots = 0;
static int g_locked = 0;

static char *put_str(char *p, char *s) { while (*s) *p++ = *s++; return p; }
static char *put_num(char *p, int v)   { return p + int_to_str(v, p, 10); }

static void die(char *msg, int code)
{
	char b[16];
	int_to_str(code, b, 10);
	puts("\n== mouselock died ==\n");
	puts(msg);
	puts("  code=");
	puts(b);
	putc('\n');
	exit(code);
}

/* 可靠的数字打印: int_to_str 是 crt0 本地实现, 不经过内核 */
static void say_int(int v)
{
	char b[16];
	int_to_str(v, b, 10);
	puts(b);
}

static void render(void)
{
	int cx, cy, hy, k, base, deg, lk;
	char buf[56];
	char *p;

	if (g_win < 0 || g_w <= 0 || g_h <= 0) return;

	cx = g_w / 2;
	cy = g_h / 2;
	hy = cy + g_pitch / 8;
	if (hy < 6)       hy = 6;
	if (hy > g_h - 6) hy = g_h - 6;

	win_clear(g_win, C_DARKGRY);
	win_draw_rect(g_win, 0, hy + 1, g_w, g_h - hy - 1, C_BLUE);
	win_draw_line(g_win, 0, hy, g_w - 1, hy, C_WHITE);

	base = (g_yaw / 2) / 30;
	for (k = -3; k <= 3; k++) {
		int sx;
		deg = (base + k) * 30;
		sx = cx + (deg - g_yaw / 2) * 3;
		if (sx >= 0 && sx < g_w)
			win_draw_line(g_win, sx, hy - 10, sx, hy - 3, C_YELLOW);
	}

	win_draw_line(g_win, cx - 7, cy, cx - 2, cy, C_GREEN);
	win_draw_line(g_win, cx + 2, cy, cx + 7, cy, C_GREEN);
	win_draw_line(g_win, cx, cy - 7, cx, cy - 2, C_GREEN);
	win_draw_line(g_win, cx, cy + 2, cx, cy + 7, C_GREEN);
	win_draw_rect(g_win, cx, cy, 1, 1, C_RED);

	p = buf;
	p = put_str(p, "Yaw:");
	p = put_num(p, g_yaw / 2);
	p = put_str(p, " Pitch:");
	p = put_num(p, g_pitch / 8);
	p = put_str(p, " Shots:");
	p = put_num(p, g_shots);
	*p = 0;
	win_draw_text(g_win, 4, 4, buf, C_WHITE, C_DARKGRY);

	lk = win_lock_mouse(g_win, -1);
	g_locked = lk;
	p = buf;
	if (lk) p = put_str(p, "LOCKED  (ESC=release, L=relock)");
	else    p = put_str(p, "RELEASED (press L to relock)");
	*p = 0;
	win_draw_text(g_win, 4, g_h - 13, buf, lk ? C_CYAN : C_YELLOW, C_DARKGRY);
}

int main(void)
{
	int type = 0, ex = 0, ey = 0;
	int rc, w, h;

	puts("[mouselock] boot\n");

	rc = win_create(40, 40, 200, 140, "Mouse Lock Demo");
	if (rc < 0) die("win_create failed (wm_uw_create returned -1)", 1);
	g_win = rc;
	puts("[1] win_create OK  win_id=");
	say_int(g_win);
	putc('\n');

	w = 0; h = 0;
	rc = win_get_size(g_win, &w, &h);
	if (rc != 0 || w <= 0 || h <= 0) {
		/* win_get_size 在部分构建里不可靠: 失败就用画布上限 200x140
		 * (UW_MAX_W/UW_MAX_H), 绝不让程序卡死在这。 */
		w = 200;
		h = 140;
		puts("[2] win_get_size FAILED -> fallback 200x140\n");
	} else {
		puts("[2] win_get_size OK\n");
	}
	g_w = w;
	g_h = h;

	rc = win_lock_mouse(g_win, 1);
	if (rc != 0) die("win_lock_mouse(win,1) failed (not a user window?)", 3);
	g_locked = 1;
	puts("[3] win_lock_mouse OK  (system cursor should be gone)\n");

	render();

	for (;;) {
		type = 0;
		ex = 0;
		ey = 0;
		/* win_get_event 内核侧无事件时会放弃时间片, 这里不会空转烧 CPU */
		type = win_get_event(g_win, &type, &ex, &ey);

		if (type == EV_CLOSE) break;

		if (type == EV_MOUSE_REL) {
			if (ex >  REL_LIMIT) ex =  REL_LIMIT;
			if (ex < -REL_LIMIT) ex = -REL_LIMIT;
			if (ey >  REL_LIMIT) ey =  REL_LIMIT;
			if (ey < -REL_LIMIT) ey = -REL_LIMIT;
			g_yaw += ex;
			g_pitch += ey;
			if (g_yaw >  100000) g_yaw   -= 200000;
			if (g_yaw < -100000) g_yaw   += 200000;
			if (g_pitch >  3000) g_pitch =  3000;
			if (g_pitch < -3000) g_pitch = -3000;
			render();
		} else if (type == EV_LDOWN) {
			g_shots++;
			render();
		} else if (type == EV_KEY) {
			if (ex == 'L' || ex == 'l') {
				if (win_lock_mouse(g_win, 1) == 0) {
					g_locked = 1;
					render();
				}
			}
		} else {
			puts("[?] unknown event type=");
			say_int(type);
			puts(" x=");
			say_int(ex);
			putc('\n');
		}
	}

	win_lock_mouse(g_win, 0);
	win_close(g_win);
	puts("[mouselock] clean exit\n");
	exit(0);
}
