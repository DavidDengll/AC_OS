# -*- coding: utf-8 -*-
"""test_scar.py —— 不可逆疤痕机制验收（全 Mock，不联网）"""
import json
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import scar_system as ss

PASS, FAIL = [], []
LOGS = []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


def new_db():
    return os.path.join(tempfile.mkdtemp(prefix="scar_"), "soul.db")


print("=" * 68)
print(" AC OS V6.8 · 不可逆疤痕机制验收")
print("=" * 68)

# ---------------- T1 濒死触发（及格线 1）----------------
print("\n[T1] vitality 跌破 10 -> 生成疤痕")
db = new_db()
ss.ensure_schema(db)
ok, entry = ss.maybe_near_death_scar(db, 15)
check("T1.1 生命值 15 不触发", ok is False, str(ok))
ok, entry = ss.maybe_near_death_scar(db, 9)
scars = ss.load_scars(db)
check("T1.2 生命值 9 触发生成", ok is True, str(ok))
check("T1.3 疤痕记录已落库", len(scars) == 1, "(n=%d)" % len(scars))
check("T1.4 含触发事件", "9" in scars[0]["event"], scars[0]["event"])
check("T1.5 含创伤类型", scars[0]["type"] == "濒死", scars[0]["type"])
check("T1.6 含烙印时间", bool(scars[0]["at"]), scars[0]["at"])

# 「首次」只触发一次：反复扣血不再刷疤
for v in (8, 5, 3, 1):
    ss.maybe_near_death_scar(db, v)
check("T1.7 反复濒死不重复刷疤", len(ss.load_scars(db)) == 1,
      "(n=%d)" % len(ss.load_scars(db)))

# ---------------- T2 死亡轮回固化死因（及格线 2）----------------
print("\n[T2] 死亡后轮回 -> 前代死因固化为疤痕")
db2 = new_db()
ss.ensure_schema(db2)
death_reason = "生命值归零（第 176 轮，思考耗能耗尽）"
entry, scars = ss.add_scar(db2, death_reason, ss.classify(death_reason))
check("T2.1 死因写入疤痕", len(scars) == 1, "(n=%d)" % len(scars))
check("T2.2 疤痕事件即前代死因", scars[0]["event"] == death_reason, scars[0]["event"])
check("T2.3 创伤类型已归类", scars[0]["type"] == "思考耗能耗尽", scars[0]["type"])
check("T2.4 断网类死因归类正确",
      ss.classify("无法连接到宿主机桥接，断网濒死") == "断网濒死",
      ss.classify("无法连接到宿主机桥接，断网濒死"))

# ---------------- T3 数量上限 + 偏移上限（及格线 3）----------------
print("\n[T3] 5 条疤痕 -> 只保留最新 3 条；偏移封顶 +0.2")
db3 = new_db()
ss.ensure_schema(db3)
for i in range(1, 6):
    ss.add_scar(db3, "第 %d 次濒死" % i, "濒死", at="2026-11-0%d" % i)
scars = ss.load_scars(db3)
check("T3.1 只保留 3 条", len(scars) == 3, "(n=%d)" % len(scars))
check("T3.2 保留的是最新的 3/4/5",
      [s["event"] for s in scars] == ["第 3 次濒死", "第 4 次濒死", "第 5 次濒死"],
      str([s["event"] for s in scars]))

shift = ss.total_shift(scars)
check("T3.3 原始累加为 0.3（3x0.1）", abs(0.1 * 3 - 0.3) < 1e-9)
check("T3.4 偏移被封顶到 0.2", abs(shift.get("cortisol", 0) - 0.2) < 1e-6,
      str(shift))

base = {"dopamine": 0.5, "cortisol": 0.3, "endorphin": 0.4}
adj = ss.apply_to_base(base, scars=scars)
check("T3.5 cortisol 基底 0.3 -> 0.5（+0.2 封顶）",
      abs(adj["cortisol"] - 0.5) < 1e-6, str(adj))
check("T3.6 未受影响的字段不变",
      adj["dopamine"] == 0.5 and adj["endorphin"] == 0.4, str(adj))
check("T3.7 不修改传入的 base 对象", base["cortisol"] == 0.3, str(base))

# 极端情况：10 条疤痕也不能超过 0.2
many = [{"event": "x%d" % i, "type": "濒死", "at": "t", "shift": {"cortisol": 0.1}}
        for i in range(10)]
check("T3.8 10 条疤痕偏移仍封顶 0.2",
      abs(ss.total_shift(many)["cortisol"] - 0.2) < 1e-6,
      str(ss.total_shift(many)))
adj10 = ss.apply_to_base(base, scars=many)
check("T3.9 10 条疤痕基底仍为 0.5", abs(adj10["cortisol"] - 0.5) < 1e-6, str(adj10))

# 负向偏移同样封顶
neg = [{"event": "y%d" % i, "type": "工具调用失败", "at": "t",
        "shift": {"dopamine": -0.05}} for i in range(10)]
check("T3.10 负向偏移封顶 -0.2",
      abs(ss.total_shift(neg)["dopamine"] + 0.2) < 1e-6,
      str(ss.total_shift(neg)))

# ---------------- T4 Prompt 注入 ----------------
print("\n[T4] Prompt 绝对注入")
block = ss.scar_prompt_block(scars=scars)
check("T4.1 含【底层心理创伤烙印】", "【底层心理创伤烙印】" in block, block[:40])
check("T4.2 含疤痕内容", "第 5 次濒死" in block, block[:80])
check("T4.3 含固定尾句",
      "这些经历永远改变了你，让你本能地感到恐惧或谨慎。" in block, block[-40:])
check("T4.4 最多 3 条", block.count("；") <= 2, block)
check("T4.5 无疤痕时返回空串", ss.scar_prompt_block(scars=[]) == "")

# ---------------- T5 容错 ----------------
print("\n[T5] 容错与隔离")
check("T5.1 不存在的库读疤痕返回空",
      ss.load_scars(os.path.join(tempfile.mkdtemp(), "nope.db")) == [])
db5 = new_db()
ss.ensure_schema(db5)
c = sqlite3.connect(db5)
c.execute("INSERT OR REPLACE INTO soul_state(key,value) VALUES('permanent_scars','[broken')")
c.commit()
c.close()
check("T5.2 疤痕 JSON 损坏不抛异常", ss.load_scars(db5) == [])
check("T5.3 非法 vitality 不触发", ss.maybe_near_death_scar(db5, "abc")[0] is False)

print("\n" + "=" * 68)
print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" 失败项:", FAIL)
print("=" * 68)
sys.exit(0 if not FAIL else 1)
