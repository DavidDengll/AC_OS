/* tools/preview/shim/gfx.h — 宿主预览用: 只声明 browser.c 需要的绘制原语 */
#ifndef _SHIM_GFX_H_
#define _SHIM_GFX_H_
#include "type.h"
extern int g_font_width;
extern int g_font_height;
void put_pixel(int x, int y, t_8 color);
void draw_hline(int x1, int x2, int y, t_8 color);
void draw_vline(int x, int y1, int y2, t_8 color);
void fill_rect(int x, int y, int w, int h, t_8 color);
void draw_char(int x, int y, char ch, t_8 fg, t_8 bg);
void draw_char_bold(int x, int y, char ch, t_8 fg, t_8 bg);
void draw_string(int x, int y, const char *str, t_8 fg, t_8 bg);
#endif