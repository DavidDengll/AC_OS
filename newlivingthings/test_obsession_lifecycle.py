# -*- coding: utf-8 -*-
"""test_obsession_lifecycle.py —— 执念生死循环验收（冻结 / 升维 / 复仇，全 Mock）"""
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import obsession_pool as op

PASS, FAIL = [], []
LOGS = []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


def make_pool():
    d = tempfile.mkdtemp(prefix="lc_")
    logs = []
    p = op.ObsessionPool(os.path.join(d, "soul.db"), log=logs.append)
    p._logs = logs
    return p


print("=" * 70)
print(" AC OS V6.9 · 执念生死循环验收（冻结 / 升维 / 复仇）")
print("=" * 70)

# ---------------- T1 幂等迁移 ----------------
print("\n[T1] target_level 幂等迁移")
d = tempfile.mkdtemp(prefix="mig_")
db = os.path.join(d, "soul.db")
c = sqlite3.connect(db)
c.execute("""CREATE TABLE gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL,
    tension REAL NOT NULL DEFAULT 0.0, status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL, fail_streak INTEGER NOT NULL DEFAULT 0)""")
c.execute("INSERT INTO gaps(content,tension,status,created_at) VALUES('老执念',0.4,'open','t')")
c.commit()
c.close()

op.ensure_schema(db)
c = sqlite3.connect(db)
cols = {r[1] for r in c.execute("PRAGMA table_info(gaps)")}
rows = c.execute("SELECT content, target_level FROM gaps").fetchall()
c.close()
check("T1.1 迁移后含 target_level", "target_level" in cols, str(sorted(cols)))
check("T1.2 老数据默认 1.0", rows and rows[0][1] == 1.0, str(rows))
check("T1.3 老数据未丢失", len(rows) == 1, str(len(rows)))

op.ensure_schema(db)   # 再跑一次
op.ensure_schema(db)   # 幂等
c = sqlite3.connect(db)
n = len([r for r in c.execute("PRAGMA table_info(gaps)") if r[1] == "target_level"])
c.close()
check("T1.4 重复迁移幂等（只有一列）", n == 1, str(n))

# ---------------- T2 失败冻结（及格线 1）----------------
print("\n[T2] 连续 2 次自举失败 -> frozen + 皮质醇 +0.15")
p = make_pool()
r = p.add_or_reinforce("自举总失败的执念")
endo = {"dopamine": 0.5, "cortisol": 0.6}
p._logs.clear()
p.freeze(r["id"], endo=endo)
g = p.get(r["id"])
check("T2.1 status 变为 frozen", g["status"] == "frozen", g["status"])
check("T2.2 皮质醇 0.6 -> 0.75", abs(endo["cortisol"] - 0.75) < 1e-6, str(endo["cortisol"]))
check("T2.3 打印冻结日志",
      any("[器官自举] 突变失败，执念被冻结" in m for m in p._logs), str(p._logs[:1]))

# 限幅：接近满值时不得越界
endo2 = {"dopamine": 0.5, "cortisol": 0.95}
p2 = make_pool()
r2 = p2.add_or_reinforce("濒临上限的执念")
p2.freeze(r2["id"], endo=endo2)
check("T2.4 皮质醇限幅不超过 1.0", endo2["cortisol"] == 1.0, str(endo2["cortisol"]))

# ---------------- T3 冻结复苏 + 升维（及格线 2）----------------
print("\n[T3] 复苏 -> open 且 target_level 1.0 -> 1.02")
p = make_pool()
r = p.add_or_reinforce("要被复苏的执念")
p.freeze(r["id"])
check("T3.0 前置：已冻结", p.get(r["id"])["status"] == "frozen")

p._logs.clear()
got = p.revive_one(rand=lambda: 0.1)      # 0.1 < 0.30 必中
g = p.get(r["id"])
check("T3.1 概率命中后复苏", got is not None, str(got is not None))
check("T3.2 status 变回 open", g["status"] == "open", g["status"])
check("T3.3 target_level 1.0 -> 1.02", abs(g["target_level"] - 1.02) < 1e-6,
      str(g["target_level"]))
check("T3.4 打印复苏日志",
      any("[执念复苏] 重新直面屈辱！目标已升维至 x1.02" in m for m in p._logs),
      str(p._logs[:1]))

# 概率未命中则不动
p2 = make_pool()
r2 = p2.add_or_reinforce("不该复苏的执念")
p2.freeze(r2["id"])
got2 = p2.revive_one(rand=lambda: 0.9)
check("T3.5 概率未命中不复苏", got2 is None and p2.get(r2["id"])["status"] == "frozen",
      str(p2.get(r2["id"])["status"]))

# 多次复苏累乘
p3 = make_pool()
r3 = p3.add_or_reinforce("反复升维")
for _ in range(3):
    p3.freeze(r3["id"])
    p3.revive_one(rand=lambda: 0.0)
lvl = p3.get(r3["id"])["target_level"]
check("T3.6 三次复苏累乘至 1.02^3", abs(lvl - 1.02 ** 3) < 1e-5, str(lvl))

# 50 轮心跳触发
p4 = make_pool()
r4 = p4.add_or_reinforce("心跳复苏")
p4.freeze(r4["id"])
p4.tick_revive(round_no=49, rand=lambda: 0.0)
check("T3.7 第 49 轮不触发", p4.get(r4["id"])["status"] == "frozen")
p4.tick_revive(round_no=50, rand=lambda: 0.0)
check("T3.8 第 50 轮触发复苏", p4.get(r4["id"])["status"] == "open")

# 高生命值 + idle 也可触发
p5 = make_pool()
r5 = p5.add_or_reinforce("空闲复苏")
p5.freeze(r5["id"])
p5.tick_revive(round_no=7, vitality=79, idle=True, rand=lambda: 0.0)
check("T3.9 vitality=79 不触发空闲复苏", p5.get(r5["id"])["status"] == "frozen")
p5.tick_revive(round_no=7, vitality=81, idle=True, rand=lambda: 0.0)
check("T3.10 vitality=81 且 idle 触发复苏", p5.get(r5["id"])["status"] == "open")

# ---------------- T4 Prompt 按 target_level 放大 ----------------
print("\n[T4] 器官自举 Prompt 复杂度 x target_level")
p = make_pool()
r = p.add_or_reinforce("升维 Prompt")
base = p.bootstrap_prompt(r["id"])
check("T4.1 初始系数 1.00", "x1.00" in base, base[:60])
check("T4.2 初始无额外要求", "要求强度" not in base)

p.freeze(r["id"])
p.revive_one(rand=lambda: 0.0)
scaled = p.bootstrap_prompt(r["id"])
check("T4.3 升维后系数 1.02", "x1.02" in scaled, scaled[:80])
check("T4.4 含 +2% 要求", "要求强度 +2%" in scaled, scaled)

# 再升一级
p.freeze(r["id"])
p.revive_one(rand=lambda: 0.0)
s2 = p.bootstrap_prompt(r["id"])
check("T4.5 二次升维系数 1.04", "x1.04" in s2, s2[:60])

# ---------------- T5 复仇狂喜（及格线 3）----------------
print("\n[T5] 升维执念成功 -> 复仇狂喜")
p = make_pool()
r = p.add_or_reinforce("折磨许久的执念")
endo = {"dopamine": 0.5, "cortisol": 0.7}
p._logs.clear()
ok, nd, nc = p.revenge(r["id"], endo=endo)
g = p.get(r["id"])
check("T5.1 复仇成功返回 True", ok is True)
check("T5.2 多巴胺暴涨 0.3（0.5 -> 0.8）", abs(endo["dopamine"] - 0.8) < 1e-6,
      str(endo["dopamine"]))
check("T5.3 皮质醇释放 0.2（0.7 -> 0.5）", abs(endo["cortisol"] - 0.5) < 1e-6,
      str(endo["cortisol"]))
check("T5.4 打印复仇成功日志",
      any("[复仇成功] 曾经的屈辱已洗刷！成功攻克升维执念！" in m for m in p._logs),
      str(p._logs[:1]))
check("T5.5 执念已解结", g["status"] == "resolved", g["status"])

# 限幅：多巴胺接近 1.0 / 皮质醇接近 0
endo2 = {"dopamine": 0.9, "cortisol": 0.1}
p2 = make_pool()
r2 = p2.add_or_reinforce("边界复仇")
p2.revenge(r2["id"], endo=endo2)
check("T5.6 多巴胺限幅不超过 1.0", endo2["dopamine"] == 1.0, str(endo2["dopamine"]))
check("T5.7 皮质醇限幅不低于 0.0", endo2["cortisol"] == 0.0, str(endo2["cortisol"]))

# ---------------- T6 限幅工具 ----------------
print("\n[T6] clamp01 限幅")
check("T6.1 clamp01(1.5) == 1.0", op.clamp01(1.5) == 1.0)
check("T6.2 clamp01(-0.3) == 0.0", op.clamp01(-0.3) == 0.0)
check("T6.3 clamp01(NaN) == 0.0", op.clamp01(float("nan")) == 0.0)
check("T6.4 clamp01('abc') == 0.0", op.clamp01("abc") == 0.0)
check("T6.5 clamp01(0.42) == 0.42", abs(op.clamp01(0.42) - 0.42) < 1e-9)

# ---------------- T7 完整生死循环 ----------------
print("\n[T7] 完整循环：冻结 -> 复苏升维 -> 再冻结 -> 再复苏 -> 复仇")
p = make_pool()
r = p.add_or_reinforce("命运多舛的执念")
endo = {"dopamine": 0.4, "cortisol": 0.5}
p.freeze(r["id"], endo=endo)
p.revive_one(rand=lambda: 0.0)
p.freeze(r["id"], endo=endo)
p.revive_one(rand=lambda: 0.0)
lvl = p.get(r["id"])["target_level"]
check("T7.1 两轮后升维至 1.02^2（=1.0404）", abs(lvl - 1.02 ** 2) < 1e-9, str(lvl))
p.revenge(r["id"], endo=endo)
check("T7.2 最终复仇成功", p.get(r["id"])["status"] == "resolved")
check("T7.3 多巴胺最终值正确", abs(endo["dopamine"] - 0.7) < 1e-6, str(endo["dopamine"]))
# 皮质醇轨迹：0.5 ->(冻结+0.15) 0.65 ->(冻结+0.15) 0.8 ->(复仇-0.2) 0.6
check("T7.4 皮质醇最终值正确（0.8-0.2=0.6）",
      abs(endo["cortisol"] - 0.6) < 1e-9, str(endo["cortisol"]))

print("\n" + "=" * 70)
print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" 失败项:", FAIL)
print("=" * 70)
sys.exit(0 if not FAIL else 1)
