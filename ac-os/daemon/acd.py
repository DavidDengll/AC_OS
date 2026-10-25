#!/usr/bin/env python3
"""
AC OS v0.1 — acd (AI Computer Daemon)
特权守护进程: 视觉捕获 + 输入注入, 经 Unix Socket 接收 AC-Script JSON 批指令.
运行: sudo python3 acd.py            (X11 环境)
测试: python3 ac_client.py
依赖: pip install mss python-xlib pillow
"""
import json, os, socket, threading, time, base64, io

import mss
from PIL import Image
from Xlib import display, X
from Xlib.ext import xtest

SOCK = "/tmp/ac.sock"
NORM = 10000  # 归一化坐标系上限

_d = display.Display()
_lock = threading.Lock()


def screen_size():
    r = _d.screen().root_in_pixels if hasattr(_d.screen(), "root_in_pixels") else _d.screen().width_in_pixels
    s = _d.screen()
    return s.width_in_pixels, s.height_in_pixels


def norm2px(x, y):
    w, h = screen_size()
    return int(x * w / NORM), int(y * h / NORM)


def op_vision(args):
    mode = args.get("mode", "full")
    with mss.mss() as s:
        if mode == "region":
            x, y = norm2px(args["x"], args["y"])
            w, h = norm2px(args.get("w", NORM), args.get("h", NORM))
            mon = {"left": x, "top": y, "width": w, "height": h}
        else:
            mon = s.monitors[1]
        shot = s.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    # 输出: 尺寸 + JPEG(VLM用, q60) + 像素hash(生效校验)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=60)
    px = img.tobytes()
    phash = hash(px) & 0xFFFFFFFF
    return {"size": list(img.size), "jpeg_b64": base64.b64encode(buf.getvalue()).decode(),
            "pixel_hash": phash}


def op_move(args):
    x, y = norm2px(args["x"], args["y"])
    with _lock:
        xtest.fake_input(_d, X.MotionNotify, x=x, y=y)
        _d.sync()
    return {"moved": [x, y]}


def op_click(args):
    x, y = norm2px(args["x"], args["y"])
    btn = {"left": 1, "middle": 2, "right": 3}.get(args.get("btn", "left"), 1)
    dbl = args.get("dbl", False)
    with _lock:
        xtest.fake_input(_d, X.MotionNotify, x=x, y=y)
        for _ in range(2 if dbl else 1):
            xtest.fake_input(_d, X.ButtonPress, btn)
            xtest.fake_input(_d, X.ButtonRelease, btn)
        _d.sync()
    return {"clicked": [x, y], "btn": btn, "dbl": dbl}


_KEYMAP = {  # X11 keysym 常用子集
    "enter": 0xff0d, "tab": 0xff09, "esc": 0xff1b, "space": 0x20,
    "backspace": 0xff08, "delete": 0xffff, "up": 0xff52, "down": 0xff53,
    "left": 0xff51, "right": 0xff53, "ctrl": 0xffe3, "alt": 0xffe9,
    "shift": 0xffe1, "super": 0xffeb,
}


def op_key(args):
    combo = args["key"].lower().replace(" ", "").split("+")
    mods, main = [], None
    for k in combo:
        if k in ("ctrl", "alt", "shift", "super"):
            mods.append(_KEYMAP[k])
        else:
            main = _KEYMAP.get(k)
    with _lock:
        for m in mods:
            xtest.fake_input(_d, X.KeyPress, _d.keysym_to_keycode(m))
        if main is not None:
            kc = _d.keysym_to_keycode(main)
            xtest.fake_input(_d, X.KeyPress, kc)
            xtest.fake_input(_d, X.KeyRelease, kc)
        else:
            # 普通字符
            ch = combo[-1]
            kc = _d.keysym_to_keycode(ord(ch))
            xtest.fake_input(_d, X.KeyPress, kc)
            xtest.fake_input(_d, X.KeyRelease, kc)
        for m in reversed(mods):
            xtest.fake_input(_d, X.KeyRelease, _d.keysym_to_keycode(m))
        _d.sync()
    return {"key": args["key"]}


def op_type(args):
    with _lock:
        for ch in args["text"]:
            kc = _d.keysym_to_keycode(ord(ch) if len(ch) == 1 else ord(ch[0]))
            xtest.fake_input(_d, X.KeyPress, kc)
            xtest.fake_input(_d, X.KeyRelease, kc)
        _d.sync()
    return {"typed": len(args["text"])}


def op_wait(args):
    time.sleep(args.get("ms", 100) / 1000)
    return {"waited": args.get("ms", 100)}


OPS = {"VISION_CAPTURE": op_vision, "INPUT_MOVE": op_move, "INPUT_CLICK": op_click,
       "INPUT_KEY": op_key, "INPUT_TYPE": op_type, "WAIT": op_wait}

RATE = {"n": 0, "t": time.time()}  # 简单配额: 200 ops/s


def handle_batch(raw):
    global RATE
    now = time.time()
    if now - RATE["t"] > 1:
        RATE = {"n": 0, "t": now}
    batch = json.loads(raw)
    if not isinstance(batch, list):
        batch = [batch]
    if RATE["n"] + len(batch) > 200:
        return {"err": "rate_limit"}
    RATE["n"] += len(batch)
    out = []
    for i, cmd in enumerate(batch):
        op = cmd.get("op")
        try:
            res = OPS[op](cmd) if op in OPS else {"err": f"unknown_op:{op}"}
        except Exception as e:
            res = {"err": str(e)}
        res["seq"] = i
        out.append(res)
    return {"results": out, "screen_state": "ok"}


def client_loop(conn):
    try:
        with conn:
            f = conn.makefile("r")
            for line in f:
                line = line.strip()
                if not line:
                    continue
                conn.sendall((json.dumps(handle_batch(line)) + "\n").encode())
    except Exception:
        pass


def main():
    if os.path.exists(SOCK):
        os.unlink(SOCK)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    os.chmod(SOCK, 0o660)
    srv.listen(8)
    print(f"[acd] AC OS daemon up @ {SOCK} | screen={screen_size()}")
    while True:
        c, _ = srv.accept()
        threading.Thread(target=client_loop, args=(c,), daemon=True).start()


if __name__ == "__main__":
    main()
