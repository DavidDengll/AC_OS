# -*- coding: utf-8 -*-
"""
obsession_pool.py —— AC OS 内在驱动力：执念池（V6.7）

设计哲学：
    系统不再只依赖用户输入。未解决的问题会沉淀为「执念」，
    在空闲时持续发酵，张力足够高时主动唤醒系统去探索。

【绝对红线】
    1. 只做增量：本模块独立于主循环，只暴露函数/类，绝不改写主循环结构。
    2. 理智保护：
       - 同类执念绝不重复插入，只累加张力（防撑爆 gaps 表）
       - 连续失败 3 次强制压制张力到 0.5（防走火入魔）
       - vitality < 30 时无条件放弃 awakened，保命第一

表结构 gaps:
    id INTEGER PK, content TEXT, tension REAL, status TEXT, created_at TEXT
"""

import datetime
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# ---- 张力常量 ----
TENSION_INIT = 0.3       # 新执念初始张力
TENSION_STEP_DEDUP = 0.1 # 去重时累加值
TENSION_HEARTBEAT = 0.02 # 每轮心跳发酵
TENSION_MAX = 1.0        # 上限
TENSION_WAKE = 0.8       # 唤醒阈值（> 0.8）
TENSION_SUPPRESS = 0.5   # 压制后的张力

# ---- 生存常量 ----
VITALITY_SAFE = 30       # 低于此值：保命优先，强制休眠
MAX_FAIL_STREAK = 3      # 连续失败次数 -> 强制压制
SUPPRESS_NOTE = '这个执念让你痛苦不堪，你决定暂时放下它，免得疯掉。'

# 「解决不了」的信号词
UNRESOLVED_MARKERS = ('不知道', '无法解决', '不知道怎么办', '想不出来', '无从下手')


def _log(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ============================================================
# 表结构
# ============================================================
def ensure_schema(db_path):
    """建立 gaps 表（幂等）。"""
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                tension REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                fail_streak INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
    finally:
        conn.close()
    return True


def _norm(text):
    """归一化：去空白/标点/大小写，用于相似度判断。"""
    t = str(text or "").strip().lower()
    t = re.sub(r"[\s\W_]+", "", t)
    return t


def _similar(a, b):
    """判断两条执念内容是否「类似」。

    朴素但可解释：归一化后相等，或一方包含另一方（且较短者足够长），
    或字符二元组的 Jaccard 相似度 >= 0.6。
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) >= 6 and short in long_:
        return True
    def bigrams(s):
        return {s[i:i + 2] for i in range(len(s) - 1)} or {s}
    ga, gb = bigrams(na), bigrams(nb)
    inter = len(ga & gb)
    union = len(ga | gb)
    return union > 0 and (inter / float(union)) >= 0.6


class ObsessionPool:
    """执念池。线程安全由调用方串行保证（空闲回调与主循环不同时调用）。"""

    def __init__(self, db_path, log=None):
        self.db = db_path
        self._log = log or _log
        ensure_schema(db_path)

    # ---- 内部 ----
    def _conn(self):
        c = sqlite3.connect(self.db, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    @staticmethod
    def _clamp(v):
        try:
            return max(0.0, min(TENSION_MAX, float(v)))
        except (TypeError, ValueError):
            return 0.0

    # ---- 查询 ----
    def find_open(self, content):
        """找与 content 类似的 open 执念，没有则 None。"""
        try:
            c = self._conn()
            try:
                rows = c.execute(
                    "SELECT * FROM gaps WHERE status='open' ORDER BY id DESC").fetchall()
            finally:
                c.close()
            for r in rows:
                if _similar(content, r["content"]):
                    return dict(r)
            return None
        except Exception:
            return None

    def get(self, gap_id):
        try:
            c = self._conn()
            try:
                r = c.execute("SELECT * FROM gaps WHERE id=?", (gap_id,)).fetchone()
                return dict(r) if r else None
            finally:
                c.close()
        except Exception:
            return None

    def open_gaps(self):
        try:
            c = self._conn()
            try:
                rows = c.execute(
                    "SELECT * FROM gaps WHERE status='open' ORDER BY tension DESC, id").fetchall()
                return [dict(r) for r in rows]
            finally:
                c.close()
        except Exception:
            return []

    def count(self, status=None):
        try:
            c = self._conn()
            try:
                if status:
                    return c.execute("SELECT COUNT(*) FROM gaps WHERE status=?",
                                     (status,)).fetchone()[0]
                return c.execute("SELECT COUNT(*) FROM gaps").fetchone()[0]
            finally:
                c.close()
        except Exception:
            return 0

    # ---- 生成 / 加固（去重防爆）----
    def add_or_reinforce(self, content, amount=None, delta=None):
        """生成或加固执念。

        已存在类似 open 执念 -> 只把张力 +delta（默认 0.1），绝不插入新行。
        返回 dict: {id, content, tension, created: bool}
        """
        content = str(content or "").strip()
        if not content:
            return None
        amount = TENSION_INIT if amount is None else amount
        delta = TENSION_STEP_DEDUP if delta is None else delta

        hit = self.find_open(content)
        if hit:
            new_t = round(self._clamp(hit["tension"] + delta), 6)
            try:
                c = self._conn()
                try:
                    c.execute("UPDATE gaps SET tension=? WHERE id=?", (new_t, hit["id"]))
                    c.commit()
                finally:
                    c.close()
            except Exception:
                pass
            self._log("[执念] 生成/加固执念：%s | 当前张力：%.1f" % (hit["content"], new_t))
            return {"id": hit["id"], "content": hit["content"],
                    "tension": new_t, "created": False}

        try:
            c = self._conn()
            try:
                cur = c.execute(
                    "INSERT INTO gaps(content,tension,status,created_at,fail_streak)"
                    " VALUES(?,?,?,?,0)",
                    (content, self._clamp(amount), "open", _now()))
                c.commit()
                gid = cur.lastrowid
            finally:
                c.close()
        except Exception:
            return None
        self._log("[执念] 生成/加固执念：%s | 当前张力：%.1f"
                  % (content, self._clamp(amount)))
        return {"id": gid, "content": content,
                "tension": self._clamp(amount), "created": True}

    # ---- 心跳发酵 ----
    def heartbeat(self, step=None):
        """每轮循环：所有 open 执念 tension += step（上限 1.0）。返回更新后的列表。

        用 ROUND(..., 6) 收口：逐次 +0.02 的二进制浮点累加会产生
        0.9999999 这类误差，导致永远够不到 1.0，唤醒判定也会抖动。
        """
        step = TENSION_HEARTBEAT if step is None else step
        try:
            c = self._conn()
            try:
                c.execute(
                    "UPDATE gaps SET tension = ROUND(MIN(?, tension + ?), 6)"
                    " WHERE status='open'",
                    (TENSION_MAX, step))
                c.commit()
            finally:
                c.close()
        except Exception:
            pass
        return self.open_gaps()

    # ---- 唤醒判定（含生存红线）----
    def should_wake(self, vitality):
        """返回 (是否唤醒, 目标执念或None, 原因)。

        生存红线：vitality < VITALITY_SAFE 时无条件休眠（哪怕张力 1.0）。
        """
        try:
            v = int(vitality)
        except (TypeError, ValueError):
            v = 0
        if v < VITALITY_SAFE:
            top = self.open_gaps()
            if top:
                self._log("[执念] 生命值 %d < %d，强制休眠回血，执念暂时搁置"
                          % (v, VITALITY_SAFE))
            return False, None, "low_vitality"

        for g in self.open_gaps():
            if float(g["tension"]) > TENSION_WAKE:
                return True, g, "high_tension"
        return False, None, "no_obsession"

    # ---- 失败与压制 ----
    def record_failure(self, gap_id):
        """记录一次因该执念而失败。连续 3 次 -> 强制压制到 0.5。

        返回 (新张力, 是否已被压制)。
        """
        g = self.get(gap_id)
        if not g:
            return None, False
        streak = int(g.get("fail_streak") or 0) + 1
        if streak >= MAX_FAIL_STREAK:
            new_t = TENSION_SUPPRESS
            suppressed = True
            streak = 0      # 压制后重新计数，允许它未来还有一次机会
        else:
            new_t = self._clamp(g["tension"])
            suppressed = False
        try:
            c = self._conn()
            try:
                c.execute("UPDATE gaps SET fail_streak=?, tension=? WHERE id=?",
                          (streak, new_t, gap_id))
                c.commit()
            finally:
                c.close()
        except Exception:
            pass
        if suppressed:
            self._log("[压制] 执念连续 %d 次失败，强制降低张力至 %.1f：%s"
                      % (MAX_FAIL_STREAK, TENSION_SUPPRESS, g["content"][:80]))
        return new_t, suppressed

    def suppress_note(self, gap_id):
        """压制期注入 Prompt 的说明。"""
        g = self.get(gap_id)
        if g and float(g["tension"]) <= TENSION_SUPPRESS:
            return SUPPRESS_NOTE
        return ""

    # ---- 解结 ----
    def resolve(self, gap_id, how=""):
        """成功解决：status=resolved，张力清零。"""
        g = self.get(gap_id)
        if not g:
            return False
        try:
            c = self._conn()
            try:
                c.execute("UPDATE gaps SET status='resolved', tension=0.0, fail_streak=0"
                          " WHERE id=?", (gap_id,))
                c.commit()
            finally:
                c.close()
        except Exception:
            return False
        self._log("[解结] 执念已消解：%s%s"
                  % (g["content"][:100], ("（%s）" % how) if how else ""))
        return True


# ============================================================
# 信号识别：大模型输出是否「解决不了」
# ============================================================
def looks_unresolved(text):
    """输出里是否含有「不知道 / 无法解决」等认输信号。"""
    t = str(text or "")
    return any(m in t for m in UNRESOLVED_MARKERS)
