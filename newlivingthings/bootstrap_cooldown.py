# -*- coding: utf-8 -*-
"""
bootstrap_cooldown.py —— 器官自举的全局冷却锁（V9.0 防自杀补丁）

背景：若无冷却，遇到高张力执念时每轮心跳都会触发自举并扣 15 点血，
几轮之内就会把生命值扣穿 —— 等于系统自杀。

规则：距离上次自举不足 COOLDOWN_ROUNDS 轮时，直接拦截。
存储：soul_state 表的 last_bootstrap_round 键（与灵魂状态同库，同一事实源）。
"""

import sqlite3

COOLDOWN_ROUNDS = 30
STATE_KEY = "last_bootstrap_round"


def _conn(db_path):
    c = sqlite3.connect(db_path, timeout=10)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS soul_state (key TEXT PRIMARY KEY, value TEXT)")
        c.commit()
    except Exception:
        pass
    return c


def get_last_round(db_path):
    """读取上次自举轮次；从未自举过返回 None。"""
    try:
        c = _conn(db_path)
        try:
            row = c.execute("SELECT value FROM soul_state WHERE key=?",
                            (STATE_KEY,)).fetchone()
        finally:
            c.close()
        if not row or row[0] is None:
            return None
        return int(float(row[0]))
    except Exception:
        return None


def set_last_round(db_path, round_no):
    """记录本次自举轮次。"""
    try:
        c = _conn(db_path)
        try:
            c.execute("INSERT OR REPLACE INTO soul_state(key,value) VALUES(?,?)",
                      (STATE_KEY, str(int(round_no))))
            c.commit()
        finally:
            c.close()
        return True
    except Exception:
        return False


def in_cooldown(db_path, current_round, cooldown=COOLDOWN_ROUNDS):
    """是否处于冷却期。返回 (是否冷却, 剩余轮数)。

    从未自举过 -> 不冷却。
    轮次回退（如转世后 round 归零）-> 视为不冷却，避免永久卡死。
    """
    last = get_last_round(db_path)
    if last is None:
        return False, 0
    try:
        cur = int(current_round)
    except (TypeError, ValueError):
        return False, 0
    if cur < last:
        return False, 0
    gap = cur - last
    if gap < cooldown:
        return True, cooldown - gap
    return False, 0
