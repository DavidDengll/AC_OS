#!/usr/bin/env python3
"""AC-Script 客户端 — 给 AI / 人类测试用. 也可作为 Agent SDK 雏形."""
import json, socket, sys, base64

SOCK = "/tmp/ac.sock"


def ac(script):
    """script: list[dict] 或 str(文本DSL) → 结果 dict"""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    s.sendall((json.dumps(script) + "\n").encode())
    resp = b""
    while not resp.endswith(b"\n"):
        resp += s.recv(65536)
    s.close()
    return json.loads(resp)


# 文本 DSL → JSON 编译器 (AC-Script 文本模式)
def compile_dsl(text):
    out = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        parts = line.split(None, 1)
        op = parts[0].upper()
        args = parts[1] if len(parts) > 1 else ""
        m = {"AC_VISION_CAPTURE": "VISION_CAPTURE", "AC_INPUT_MOVE": "INPUT_MOVE",
             "AC_INPUT_CLICK": "INPUT_CLICK", "AC_INPUT_KEY": "INPUT_KEY",
             "AC_INPUT_TYPE": "INPUT_TYPE", "AC_WAIT": "WAIT"}[op]
        d = {"op": m}
        if m in ("INPUT_MOVE", "INPUT_CLICK"):
            toks = args.split()
            d["x"], d["y"] = int(toks[0]), int(toks[1])
            if len(toks) > 2:
                d["btn"] = toks[2]
        elif m == "INPUT_KEY":
            d["key"] = args
        elif m == "INPUT_TYPE":
            d["text"] = args.strip('"')
        elif m == "VISION_CAPTURE":
            d["mode"] = args or "full"
        elif m == "WAIT":
            d["ms"] = int(args)
        out.append(d)
    return out


if __name__ == "__main__":
    # 演示: AI 接管桌面 — 移到中心 → 画圈 → 截屏验证
    import math
    script = compile_dsl("""
    AC_WAIT 500
    AC_INPUT_MOVE 5000 5000
    AC_WAIT 200
    AC_INPUT_CLICK 5000 5000
    """)
    for a in range(0, 360, 15):  # 鼠标画圆, 肉眼可见 AI 在动
        x = 5000 + int(1500 * math.cos(math.radians(a)))
        y = 5000 + int(1500 * math.sin(math.radians(a)))
        script.append({"op": "INPUT_MOVE", "x": x, "y": y})
        script.append({"op": "WAIT", "ms": 30})
    script.append({"op": "VISION_CAPTURE", "mode": "full"})
    r = ac(script)
    for res in r["results"]:
        if "jpeg_b64" in res:
            img = base64.b64decode(res["jpeg_b64"])
            open("ac_screen.jpg", "wb").write(img)
            print(f"[{res['seq']}] VISION ok size={res['size']} hash={res['pixel_hash']} -> ac_screen.jpg")
        else:
            print(f"[{res['seq']}] {res}")
