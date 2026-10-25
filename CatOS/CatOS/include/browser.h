/*++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
                              browser.h
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
              CatOS Browser — 极简离线网页查看器 (接口)

  说明:
    - 浏览器是图形桌面 (wm.c) 的一个内置应用, 窗口类型 WM_WT_BROWSER
    - 窗口由 wm.c 创建, browser.c 只负责读取文件 / 解析 / 绘制 / 翻页
    - 全部使用静态缓冲区, 无动态分配, 可在内核态安全运行
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++*/

#ifndef _CATOS_BROWSER_H_
#define _CATOS_BROWSER_H_

#include "type.h"

/* 在指定窗口中打开文件 (只在 FAT 根目录查找, 如 "INDEX.HTM")
 * 返回 0=成功, -1=失败 (失败原因保存在内部状态, 绘制时显示) */
PUBLIC int  br_open(int win_idx, const char *name);

/* 绘制浏览器客户区 (由窗口管理器调用)
 * cx,cy,cw,ch: 客户区矩形 (屏幕像素坐标) */
PUBLIC void br_draw_client(int win_idx, int cx, int cy, int cw, int ch);

/* 鼠标左键点击 (屏幕像素坐标). 返回 1=已处理
 * 第一版没有可点击元素, 恒返回 0 */
PUBLIC int  br_handle_click(int win_idx, int mx, int my);

/* 键盘按键 (keyboard_read_simple 编码). 返回 1=已消费
 * 支持: PgUp/PgDn/Up/Down/Home/End/F5(刷新) */
PUBLIC int  br_handle_key(int win_idx, t_32 key);

/* 关闭窗口 / 退出桌面时清理内部状态 */
PUBLIC void br_reset(void);

/* 判断指定窗口是否为浏览器窗口 (窗口管理器内部使用) */
PUBLIC int  br_is_window(int win_idx);

#endif /* _CATOS_BROWSER_H_ */
