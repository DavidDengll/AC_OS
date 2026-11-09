# -*- coding: utf-8 -*-
"""test_obsession.py —— 内在驱动力（执念池）验收（全 Mock，不联网）"""
import json
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


def quiet_log(msg):
    LOGS.append(msg)


def make_pool():
    d = tempfile.mkdtemp(prefix="ob_")
    return op.ObsessionPool(os.path.join(d, "soul.db"), log=quiet_log)


print("=" * 68)
print(" AC OS V6.7 · 内在驱动力（执念池）验收")
print("=" * 68)

# ---------------- T1 表结构 ----------------
print("\n[T1] gaps 表结构")
p = make_pool()
c = sqlite3.connect(p.db)
cols = {r[1]: r[2] for r in c.execute("PRAGMA table_info(gaps)")}
c.close()
for f in ("id", "content", "tension", "status", "created_at"):
    check("T1.1 含字段 %s" % f, f in cols, str(cols))

# ---------------- T2 去重防爆（验收及格线 1）----------------
print("\n[T2] 5 次相同工具失败 -> 只有 1 条记录，张力叠加")
p = make_pool()
LOGS.clear()
for i in range(5):
    p.add_or_reinforce("工具调用失败：搜索 GitHub 超时")
n = p.count()
g = p.open_gaps()[0]
check("T2.1 gaps 表只有 1 条记录", n == 1, "(rows=%d)" % n)
# 首次 0.3，之后每次 +0.1，共 4 次 -> 0.7
check("T2.2 张力正确叠加为 0.7", abs(g["tension"] - 0.7) < 1e-6,
      "(tension=%.2f)" % g["tension"])
check("T2.3 打印生成/加固日志", any("生成/加固执念" in m for m in LOGS),
      str(LOGS[:1]))
check("T2.4 日志含当前张力", any("当前张力" in m for m in LOGS))

# 相似判定：措辞略变也应命中
p2 = make_pool()
p2.add_or_reinforce("工具调用失败：搜索 GitHub 超时")
p2.add_or_reinforce("工具调用失败：搜索 GitHub 超时了")
check("T2.5 轻微措辞变化仍去重", p2.count() == 1, str(p2.count()))

# 不同内容不合并
p3 = make_pool()
p3.add_or_reinforce("工具调用失败：搜索 GitHub 超时")
p3.add_or_reinforce("无法理解用户关于量子引力的追问")
check("T2.6 不同内容生成 2 条", p3.count() == 2, str(p3.count()))

# ---------------- T3 心跳发酵（验收及格线 2）----------------
print("\n[T3] 20 轮心跳 -> 张力上涨")
p = make_pool()
p.add_or_reinforce("未解决：为什么猫总在夜里叫")   # 0.3
start = p.open_gaps()[0]["tension"]
for _ in range(20):
    p.heartbeat()
end = p.open_gaps()[0]["tension"]
expect = start + 20 * op.TENSION_HEARTBEAT
check("T3.1 20 轮后张力上涨", end > start, "%.2f -> %.2f" % (start, end))
check("T3.2 涨幅正确 (+0.02/轮)", abs(end - expect) < 1e-6,
      "实际 %.3f 期望 %.3f" % (end, expect))
check("T3.3 未超过上限 1.0", end <= 1.0, str(end))

for _ in range(100):
    p.heartbeat()
check("T3.4 大量心跳后仍被限制在 1.0", abs(p.open_gaps()[0]["tension"] - 1.0) < 1e-6,
      str(p.open_gaps()[0]["tension"]))

# resolved 的不再发酵
p.add_or_reinforce("已解决的执念")
gid = p.open_gaps()[0]["id"]
p.resolve(gid)
before = p.get(gid)["tension"]
p.heartbeat()
check("T3.5 resolved 执念不发酵", p.get(gid)["tension"] == before, str(before))

# ---------------- T4 生存红线（验收及格线 3）----------------
print("\n[T4] vitality=20 且张力 0.9 -> 强制休眠（保命红线）")
p = make_pool()
r = p.add_or_reinforce("濒死时的执念")
c = sqlite3.connect(p.db)
c.execute("UPDATE gaps SET tension=0.9 WHERE id=?", (r["id"],))
c.commit()
c.close()
LOGS.clear()
wake, target, why = p.should_wake(vitality=20)
check("T4.1 生命值 20 时不唤醒", wake is False, str(wake))
check("T4.2 原因是 low_vitality", why == "low_vitality", why)
check("T4.3 打印强制休眠日志", any("强制休眠回血" in m for m in LOGS), str(LOGS[:1]))

# 边界：29 休眠，30 唤醒
for v, want in ((29, False), (30, True)):
    w, _t, _y = p.should_wake(vitality=v)
    check("T4.4 vitality=%d -> %s" % (v, "唤醒" if want else "休眠"), w is want)

# 张力不足不唤醒
p2 = make_pool()
p2.add_or_reinforce("普通执念")     # 0.3
w, _t, why = p2.should_wake(vitality=100)
check("T4.5 张力不足不唤醒", w is False and why == "no_obsession", why)

# 张力 > 0.8 才唤醒（0.8 本身不唤醒）
s = make_pool()
r = s.add_or_reinforce("临界执念")
c = sqlite3.connect(s.db)
c.execute("UPDATE gaps SET tension=0.8 WHERE id=?", (r["id"],))
c.commit()
c.close()
w, _t, _y = s.should_wake(vitality=100)
check("T4.6 张力恰为 0.8 时不唤醒（必须 >0.8）", w is False, str(w))
s.heartbeat()
w, target, _y = s.should_wake(vitality=100)
check("T4.7 超过 0.8 后唤醒", w is True and target["id"] == r["id"], str(w))

# ---------------- T5 连续失败强制压制 ----------------
print("\n[T5] 连续 3 次失败 -> 张力降到 0.5 + Prompt 注入")
p = make_pool()
r = p.add_or_reinforce("反复失败的执念")
c = sqlite3.connect(p.db)
c.execute("UPDATE gaps SET tension=0.95 WHERE id=?", (r["id"],))
c.commit()
c.close()
LOGS.clear()
s1, sup1 = p.record_failure(r["id"])
s2, sup2 = p.record_failure(r["id"])
check("T5.1 前两次失败不压制", sup1 is False and sup2 is False, "%s,%s" % (sup1, sup2))
s3, sup3 = p.record_failure(r["id"])
check("T5.2 第 3 次失败触发压制", sup3 is True, str(sup3))
check("T5.3 张力被强制降到 0.5", abs(s3 - 0.5) < 1e-6, str(s3))
check("T5.4 打印压制日志", any("压制" in m for m in LOGS), str(LOGS[:1]))
note = p.suppress_note(r["id"])
check("T5.5 注入放下执念的 Prompt", note == op.SUPPRESS_NOTE, note[:40])
check("T5.6 Prompt 文案正确",
      "痛苦不堪" in note and "免得疯掉" in note, note)

# ---------------- T6 解结 ----------------
print("\n[T6] 成功解决 -> resolved + 张力清零")
p = make_pool()
r = p.add_or_reinforce("能被解决的执念")
LOGS.clear()
ok = p.resolve(r["id"])
g = p.get(r["id"])
check("T6.1 resolve 返回 True", ok is True)
check("T6.2 status=resolved", g["status"] == "resolved", g["status"])
check("T6.3 张力清零", g["tension"] == 0.0, str(g["tension"]))
check("T6.4 打印 [解结] 日志", any("[解结] 执念已消解" in m for m in LOGS),
      str(LOGS[:1]))
check("T6.5 不再出现在 open 列表", all(x["id"] != r["id"] for x in p.open_gaps()))

# ---------------- T7 认输信号识别 ----------------
print("\n[T7] 大模型输出认输信号")
for t in ("我不知道这个问题", "这个我无法解决", "想不出来"):
    check("T7 识别「%s」" % t, op.looks_unresolved(t) is True)
for t in ("我知道答案了", "解决了", "好的"):
    check("T7 不误判「%s」" % t, op.looks_unresolved(t) is False)

print("\n" + "=" * 68)
print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" 失败项:", FAIL)
print("=" * 68)
sys.exit(0 if not FAIL else 1)
