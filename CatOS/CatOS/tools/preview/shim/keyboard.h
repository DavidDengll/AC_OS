/* tools/preview/shim/keyboard.h — 宿主预览用: 只提供按键常量 */
#ifndef _SHIM_KEYBOARD_H_
#define _SHIM_KEYBOARD_H_
#define FLAG_EXT    0x0100
#define ESC         (0x01 + FLAG_EXT)
#define ENTER       (0x03 + FLAG_EXT)
#define BACKSPACE   (0x04 + FLAG_EXT)
#define F5          (0x15 + FLAG_EXT)
#define HOME        (0x21 + FLAG_EXT)
#define END         (0x22 + FLAG_EXT)
#define PAGEUP      (0x23 + FLAG_EXT)
#define PAGEDOWN    (0x24 + FLAG_EXT)
#define UP          (0x25 + FLAG_EXT)
#define DOWN        (0x26 + FLAG_EXT)
#define LEFT        (0x27 + FLAG_EXT)
#define RIGHT       (0x28 + FLAG_EXT)
#endif