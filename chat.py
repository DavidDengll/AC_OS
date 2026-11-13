# -*- coding: utf-8 -*-
"""
chat.py —— AC OS V9.3 宿主端实时对话终端

用法：
    python chat.py                 # 进入交互式对话
    python chat.py "你好"          # 发送一句话后退出

【绝对红线】
    本程序**绝不**连接或修改 entropy_memory.db。
    与容器内熵灵的全部通信只经由：
      newlivingthings/inbox.jsonl  （去程：宿主 -> 熵灵）
      newlivingthings/outbox.jsonl （回程：熵灵 -> 宿主）
    这样双方永远不会争抢 SQLite 锁，从根上杜绝 database is locked。

增量游标：记录 outbox 已读字节偏移，只打印新增回复，绝不重复刷屏。
"""

import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "newlivingthings")
INBOX = os.path.join(APP, "inbox.jsonl")
OUTBOX = os.path.join(APP, "outbox.jsonl")
OFFSET_FILE = os.path.join(HERE, ".chat_outbox_offset")

# ---- ANSI 颜色（不支持时自动降级为纯文本）----
_ANSI_OK = None


def ansi(code, text):
    global _ANSI_OK
    if _ANSI_OK is None:
        _ANSI_OK = _supports_ansi()
    if not _ANSI_OK:
        return text
    return "\033[%sm%s\033[0m" % (code, text)


def _supports_ansi():
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)
            return True
    except Exception:
        pass
    return bool(os.environ.get("WT_SESSION") or os.environ.get("TERM"))


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ============================================================
# 去程：写 inbox（只写文件，绝不碰数据库）
# ============================================================
def send(text, inbox=None):
    """把宿主输入追加到 inbox.jsonl。"""
    payload = {"time": _now(), "text": str(text or "")}
    path = inbox or INBOX
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return True


# ============================================================
# 回程：增量读取 outbox
# ============================================================
def read_offset(path=None):
    try:
        with open(path or OFFSET_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip() or 0)
    except Exception:
        return 0


def save_offset(value, path=None):
    try:
        with open(path or OFFSET_FILE, "w", encoding="utf-8") as f:
            f.write(str(int(value)))
    except Exception:
        pass


def read_new_replies(outbox=None, offset_file=None):
    """只读取上次之后的增量回复，绝不重复打印历史。"""
    path = outbox or OUTBOX
    if not os.path.exists(path):
        return [], read_offset(offset_file)
    try:
        size = os.path.getsize(path)
        offset = read_offset(offset_file)
        if size < offset:
            offset = 0
        if size == offset:
            return [], offset
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read(size - offset)
        new_offset = offset + len(chunk)
        out = []
        for raw in chunk.decode("utf-8", "replace").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out, new_offset
    except Exception:
        return [], read_offset(offset_file)


# ============================================================
# 彩色状态条
# ============================================================
def format_endo(endo):
    """🟢 多巴胺 / 🔴 皮质醇 / 💚 生命值 彩色条。"""
    e = endo or {}

    def bar(value, width=10):
        try:
            v = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            v = 0.0
        filled = int(round(v * width))
        return "#" * filled + "." * (width - filled), v

    dbar, d = bar(e.get("dopamine"))
    cbar, c = bar(e.get("cortisol"))
    v_raw = e.get("vitality")
    if v_raw is None:
        v_txt = "--"
        vbar = "." * 10
    else:
        try:
            vv = max(0, min(100, int(float(v_raw))))
        except (TypeError, ValueError):
            vv = 0
        vbar = "#" * int(round(vv / 100.0 * 10)) + "." * (10 - int(round(vv / 100.0 * 10)))
        v_txt = str(vv)

    return "  ".join([
        ansi("32", "🟢 D %.2f [%s]" % (d, dbar)),          # 绿
        ansi("31", "🔴 C %.2f [%s]" % (c, cbar)),          # 红
        ansi("36", "💚 Vitality %s [%s]" % (v_txt, vbar)), # 青
    ])


def format_reply(item):
    when = str(item.get("time") or "")
    text = str(item.get("text") or "")
    endo = item.get("endo")
    head = ansi("35", "[熵灵 %s]" % when)
    lines = ["%s %s" % (head, text)]
    if isinstance(endo, dict):
        lines.append("    " + format_endo(endo))
    return "\n".join(lines)


# ============================================================
# 交互循环
# ============================================================
def wait_replies(timeout=60.0, poll=0.5, outbox=None, offset_file=None):
    """轮询等待新回复，返回 (replies, new_offset)。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        replies, new_offset = read_new_replies(outbox, offset_file)
        if replies:
            return replies, new_offset
        time.sleep(poll)
    return [], read_offset(offset_file)


def interactive(timeout=60.0):
    print(ansi("1;36", "=" * 62))
    print(ansi("1;36", "   AC OS · 跨次元对话终端"))
    print(ansi("1;36", "=" * 62))
    print("  与容器内熵灵对话。输入 /quit 退出。")
    print("  〔通信方式：inbox.jsonl / outbox.jsonl，不碰数据库〕")
    print()
    # 首次启动：把历史上已有的回复视为"已读"，避免刷屏
    if not os.path.exists(OFFSET_FILE) and os.path.exists(OUTBOX):
        save_offset(os.path.getsize(OUTBOX))
    while True:
        try:
            text = input(ansi("1;32", "[宿主] > ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text in ("/quit", "/exit", "quit", "exit"):
            break
        send(text)
        print(ansi("2", "  … 已投递，等待熵灵回应（心跳周期内）"))
        replies, new_offset = wait_replies(timeout=timeout)
        save_offset(new_offset)
        if not replies:
            print(ansi("33", "  [超时] 熵灵暂时没有回应（可能正在休眠或心跳未触发）。"))
            continue
        for item in replies:
            print(format_reply(item))
    print(ansi("1;36", "再见。"))


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv:
        send(" ".join(argv))
        replies, new_offset = wait_replies(timeout=90.0)
        save_offset(new_offset)
        if not replies:
            print("[超时] 熵灵暂时没有回应。")
            return 1
        for item in replies:
            print(format_reply(item))
        return 0
    interactive()
    return 0


if __name__ == "__main__":
    sys.exit(main())
