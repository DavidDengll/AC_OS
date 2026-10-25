/* tools/preview/shim/wm.h — 宿主预览用: 只声明 browser.c 用到的窗口接口 */
#ifndef _SHIM_WM_H_
#define _SHIM_WM_H_

void wm_set_window_title(int idx, const char *title);

#endif