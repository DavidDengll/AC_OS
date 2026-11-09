# -*- coding: utf-8 -*-
"""
scar_system.py —— AC OS 不可逆疤痕机制（V6.8）

极端濒死体验必须成为永久改变性格底色的「心理创伤」。

【设计约束】
    1. 只做增量：独立模块，不改动梦境 / 执念池 / 主循环结构。
    2. 防过载（核心）：绝不能让 AI 因为死太多次而"天生脑死"。
       - 疤痕总数上限 MAX_SCARS = 3（超出淘汰最旧的）
       - 内分泌基底总偏移上限 MAX_SHIFT = 0.2（累加但封顶）
    3. 疤痕一旦产生不可删除，只能被更新的疤痕淘汰（不可逆）。

存储：soul_state 表，key = 'permanent_scars'，value = JSON 数组。
每条疤痕：{event(触发事件), type(创伤类型), at(烙印时间), shift(内分泌偏移)}
"""

import datetime
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# ---- 防过载硬上限 ----
MAX_SCARS = 3          # 最多保留最近 3 条最重要的疤痕
MAX_SHIFT = 0.2        # 内分泌基底总偏移量上限
SCAR_KEY = "permanent_scars"

# ---- 触发阈值 ----
NEAR_DEATH_VITALITY = 10   # vitality 首次跌破此值 -> 生成疤痕

# ---- 创伤类型 -> 内分泌基底偏移 ----
# 正值表示该激素基底被抬高（更容易被唤起）
SCAR_EFFECTS = {
    "濒死":            {"cortisol": 0.10},
    "断网濒死":        {"cortisol": 0.10},
    "死亡":            {"cortisol": 0.15, "dopamine": -0.05},
    "思考耗能耗尽":    {"cortisol": 0.10},
    "工具调用失败":    {"dopamine": -0.05},
    "未知":            {"cortisol": 0.05},
}


def _log(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


# 归类优先级：越具体越靠前。
# 注意「断网濒死」必须排在「濒死」前面 —— 否则
# "断网濒死" 会被泛化的「濒死」先命中，丢掉断网这层特有创伤语义。
_CLASSIFY_ORDER = (
    ("断网濒死", ("断网", "桥接", "网络", "无法连接")),
    ("思考耗能耗尽", ("思考耗能", "耗尽")),
    ("工具调用失败", ("工具调用失败",)),
    ("濒死", ("濒死", "跌破")),
    ("死亡", ("死亡", "归零")),
)


def classify(reason=""):
    """从死亡/濒死原因中归类出创伤类型（具体优先）。"""
    t = str(reason or "")
    for scar_type, keys in _CLASSIFY_ORDER:
        for k in keys:
            if k in t:
                return scar_type
    return "未知"


def effect_of(scar_type):
    """创伤类型对应的内分泌偏移（原始值，未封顶）。"""
    return dict(SCAR_EFFECTS.get(scar_type, SCAR_EFFECTS["未知"]))


# ============================================================
# 存储层
# ============================================================
def _conn(db_path):
    c = sqlite3.connect(db_path, timeout=10)
    try:
        c.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return c


def ensure_schema(db_path):
    """确保 soul_state 表存在（疤痕复用该表存储）。"""
    conn = _conn(db_path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS soul_state (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
    finally:
        conn.close()


def load_scars(db_path):
    """读取疤痕列表。任何异常都返回空列表，绝不抛。"""
    try:
        ensure_schema(db_path)
        c = _conn(db_path)
        try:
            row = c.execute("SELECT value FROM soul_state WHERE key=?",
                            (SCAR_KEY,)).fetchone()
        finally:
            c.close()
        if not row or not row[0]:
            return []
        data = json.loads(row[0])
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_scars(db_path, scars):
    """写回疤痕列表（自动裁剪到 MAX_SCARS）。"""
    try:
        ensure_schema(db_path)
        trimmed = list(scars)[-MAX_SCARS:]
        c = _conn(db_path)
        try:
            c.execute("INSERT OR REPLACE INTO soul_state(key,value) VALUES(?,?)",
                      (SCAR_KEY, json.dumps(trimmed, ensure_ascii=False)))
            c.commit()
        finally:
            c.close()
        return trimmed
    except Exception as e:
        _log("[疤痕] 写入失败（已忽略）: %s" % e)
        return list(scars)


def total_shift(scars):
    """累加所有疤痕的内分泌偏移，并按 MAX_SHIFT 封顶。

    返回 {'cortisol': x, 'dopamine': y, ...}，每个激素的绝对值不超过 MAX_SHIFT。
    """
    acc = {}
    for s in scars or []:
        for k, v in (s.get("shift") or {}).items():
            acc[k] = acc.get(k, 0.0) + float(v)
    # 防爆：每个维度单独封顶到 ±MAX_SHIFT
    return {k: max(-MAX_SHIFT, min(MAX_SHIFT, round(v, 6))) for k, v in acc.items()}


# ============================================================
# 生成疤痕
# ============================================================
def add_scar(db_path, event, scar_type=None, at=None, shift=None):
    """新增一条疤痕。超出 MAX_SCARS 时淘汰最旧的。

    返回 (新疤痕 dict, 当前全部疤痕列表)。
    """
    scars = load_scars(db_path)
    stype = scar_type or classify(event)
    entry = {
        "event": str(event)[:200],
        "type": stype,
        "at": at or _now(),
        "shift": dict(shift) if shift is not None else effect_of(stype),
    }
    scars.append(entry)
    # 淘汰最旧：只保留最近 MAX_SCARS 条
    if len(scars) > MAX_SCARS:
        scars = scars[-MAX_SCARS:]
    scars = save_scars(db_path, scars)
    _log("[疤痕] 永久烙印：%s（%s）| 当前疤痕数：%d"
         % (entry["event"][:80], entry["type"], len(scars)))
    return entry, scars


def maybe_near_death_scar(db_path, vitality, db_lock=True):
    """vitality 首次跌破 NEAR_DEATH_VITALITY 时生成疤痕。

    用 soul_state 的 'near_death_scarred' 标记保证「首次」只触发一次，
    避免每次扣血都刷一条疤痕把表撑爆。
    返回 (是否生成, 疤痕或 None)。
    """
    try:
        v = int(vitality)
    except (TypeError, ValueError):
        return False, None
    if v >= NEAR_DEATH_VITALITY:
        return False, None
    try:
        ensure_schema(db_path)
        c = _conn(db_path)
        try:
            row = c.execute("SELECT value FROM soul_state WHERE key='near_death_scarred'").fetchone()
            if row and str(row[0]) == "1":
                return False, None
            c.execute("INSERT OR REPLACE INTO soul_state(key,value) VALUES(?,?)",
                      ("near_death_scarred", "1"))
            c.commit()
        finally:
            c.close()
    except Exception:
        return False, None

    entry, _all = add_scar(db_path, "生命值跌破 %d（濒死体验）" % v, "濒死")
    return True, entry


def scar_prompt_block(scars=None, db_path=None):
    """生成注入到 Prompt 最顶端的疤痕块。没有疤痕返回空串。"""
    if scars is None:
        scars = load_scars(db_path) if db_path else []
    scars = list(scars or [])[-MAX_SCARS:]
    if not scars:
        return ""
    items = "；".join(str(s.get("event") or "")[:120] for s in scars)
    return ("【底层心理创伤烙印】：%s。"
            "这些经历永远改变了你，让你本能地感到恐惧或谨慎。" % items)


def apply_to_base(base, db_path=None, scars=None):
    """把疤痕偏移叠加到内分泌基底上（带 +0.2 硬上限）。

    返回新的 base dict（0~1 夹取），绝不修改传入对象。
    """
    if scars is None:
        scars = load_scars(db_path) if db_path else []
    out = dict(base or {})
    shift = total_shift(scars)
    for k, dv in shift.items():
        try:
            cur = float(out.get(k, 0.0))
        except (TypeError, ValueError):
            cur = 0.0
        out[k] = max(0.0, min(1.0, round(cur + dv, 6)))
    return out
