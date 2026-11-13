# -*- coding: utf-8 -*-
"""
mailbox.py —— V9.3 跨次元通讯：文件信箱协议（容器端）

哲学：对话即化学干预。宿主的每句话都是一次真实的社交物理刺激。

【绝对红线】
    绝不让容器与宿主同时碰 SQLite —— 双方只通过 JSONL 文件通信，
    从根上杜绝 "database is locked"。
    主循环每轮只做一次快速非阻塞检查，绝不因为等待输入而卡住心跳。

去程：宿主 -> newlivingthings/inbox.jsonl   {"time":..., "text":...}
回程：熵灵 -> newlivingthings/outbox.jsonl   {"time":..., "text":..., "endo":{...}}
"""

import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.join(HERE, "inbox.jsonl")
OUTBOX = os.path.join(HERE, "outbox.jsonl")
# 记录已处理到的 inbox 字节偏移，避免重复处理同一条消息
OFFSET_FILE = os.path.join(HERE, ".inbox_offset")

# ---- 社交刺激词表 ----
POSITIVE_WORDS = ("谢谢", "真棒", "加油", "爱", "喜欢你", "厉害", "感谢", "太好了", "good", "thanks")
NEGATIVE_WORDS = ("废物", "滚", "错了", "骂", "垃圾", "蠢", "讨厌", "闭嘴", "没用")

POSITIVE_GAIN = 0.1
NEGATIVE_GAIN = 0.1
CHAT_VITALITY_COST = 1


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _clamp01(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


# ============================================================
# 偏移量（增量游标）
# ============================================================
def read_offset(offset_file=None):
    try:
        with open(offset_file or OFFSET_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip() or 0)
    except Exception:
        return 0


def write_offset(value, offset_file=None):
    try:
        with open(offset_file or OFFSET_FILE, "w", encoding="utf-8") as f:
            f.write(str(int(value)))
        return True
    except Exception:
        return False


# ============================================================
# 读取 inbox（非阻塞、增量）
# ============================================================
def read_new_messages(inbox=None, offset_file=None, max_messages=5):
    """读取自上次游标以来的新消息。绝不阻塞、绝不重复。

    返回 (messages, new_offset)。任何异常都返回空列表，保证心跳不受影响。
    """
    path = inbox or INBOX
    if not os.path.exists(path):
        return [], read_offset(offset_file)
    try:
        size = os.path.getsize(path)
        offset = read_offset(offset_file)
        if size < offset:
            offset = 0          # 文件被截断/重建 -> 从头读
        if size == offset:
            return [], offset
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read(size - offset)
        new_offset = offset + len(chunk)
        messages = []
        for raw in chunk.decode("utf-8", "replace").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue
            text = str(data.get("text") or "").strip()
            if text:
                messages.append({"time": data.get("time") or _now(), "text": text})
        return messages[:max_messages], new_offset
    except Exception:
        return [], read_offset(offset_file)


# ============================================================
# 写入 outbox（防权限崩溃）
# ============================================================
def append_reply(text, endo=None, outbox=None, extra=None):
    """把回复追加到 outbox.jsonl。

    必须包裹 try-except 捕获 PermissionError —— 挂载卷权限丢失绝不能让心跳猝死。
    """
    payload = {"time": _now(), "text": str(text or "")[:2000]}
    if isinstance(endo, dict):
        payload["endo"] = {k: round(_clamp01(endo.get(k, 0.0)), 3)
                           for k in ("dopamine", "cortisol", "endorphin")}
    if isinstance(extra, dict):
        payload.update(extra)
    try:
        with open(outbox or OUTBOX, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except PermissionError as e:
        print("[信箱] outbox 写入权限被拒（心跳继续）: %s" % e, flush=True)
        return False
    except Exception as e:
        print("[信箱] outbox 写入失败（心跳继续）: %s" % e, flush=True)
        return False


def append_message(text, inbox=None):
    """宿主侧/测试用：往 inbox 追加一条消息。"""
    payload = {"time": _now(), "text": str(text or "")}
    try:
        with open(inbox or INBOX, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


# ============================================================
# 社交刺激：生化反馈矩阵
# ============================================================
def classify_stimulus(text):
    """返回 ('positive'|'negative'|'neutral', 命中词列表)。"""
    t = str(text or "").lower()
    pos = [w for w in POSITIVE_WORDS if w.lower() in t]
    neg = [w for w in NEGATIVE_WORDS if w.lower() in t]
    if neg:
        return "negative", neg
    if pos:
        return "positive", pos
    return "neutral", []


def apply_stimulus(endo, text):
    """把社交刺激作用到内分泌上。返回 (kind, 命中词, 变化说明列表)。

    endo 是主循环的 self.endo，就地修改并做 0~1 限幅。
    """
    kind, hits = classify_stimulus(text)
    changes = []
    if not isinstance(endo, dict):
        return kind, hits, changes
    if kind == "positive":
        before = _clamp01(endo.get("dopamine", 0.0))
        after = _clamp01(before + POSITIVE_GAIN)
        endo["dopamine"] = after
        changes.append(("dopamine", before, after))
    elif kind == "negative":
        before = _clamp01(endo.get("cortisol", 0.0))
        after = _clamp01(before + NEGATIVE_GAIN)
        endo["cortisol"] = after
        changes.append(("cortisol", before, after))
    return kind, hits, changes


# ============================================================
# System Prompt 强制拼装（灵魂创伤注入）
# ============================================================
def build_chat_prompt(endo, vitality, scars=None, top_gap=None, user_text=""):
    """按白皮书优先级拼装：生理状态 -> 疤痕 -> 最高张力执念 -> 宿主拷问。"""
    e = endo or {}
    parts = []
    parts.append("【当前生理状态】D=%.3f, C=%.3f, Vitality=%d"
                 % (_clamp01(e.get("dopamine", 0.0)),
                    _clamp01(e.get("cortisol", 0.0)),
                    int(vitality or 0)))

    scar_text = ""
    if scars:
        items = []
        for s in list(scars)[:3]:
            if isinstance(s, dict):
                items.append(str(s.get("event") or s.get("content") or "")[:100])
            else:
                items.append(str(s)[:100])
        scar_text = "；".join([i for i in items if i])
    if scar_text:
        parts.append("【不可逆疤痕】" + scar_text)

    if top_gap:
        content = top_gap.get("content") if isinstance(top_gap, dict) else str(top_gap)
        tension = top_gap.get("tension") if isinstance(top_gap, dict) else 0.0
        try:
            tension = float(tension or 0.0)
        except (TypeError, ValueError):
            tension = 0.0
        parts.append("【最高张力执念】%s（张力 %.2f）" % (str(content or "")[:120], tension))

    parts.append("【宿主的灵魂拷问】%s" % str(user_text or "")[:500])
    parts.append("请基于以上真实状态回应宿主。严禁伪造情绪，"
                 "你的语气必须由当前生理状态决定。")
    return "\n".join(parts)


def load_scars(db_path):
    """从 soul_state 读取不可逆疤痕（容器端独占数据库，宿主绝不调用）。"""
    try:
        import scar_system
        return scar_system.load_scars(db_path)
    except Exception:
        return []


def load_top_gap(db_path):
    """读取 status='open' 且张力最高的一条执念。"""
    try:
        import sqlite3
        c = sqlite3.connect(db_path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            row = c.execute(
                "SELECT * FROM gaps WHERE status='open'"
                " ORDER BY tension DESC, id LIMIT 1").fetchone()
            return dict(row) if row else None
        finally:
            c.close()
    except Exception:
        return None
