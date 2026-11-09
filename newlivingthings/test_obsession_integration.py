# -*- coding: utf-8 -*-
"""test_obsession_integration.py —— 执念接入主循环验收（Mock，不联网、不跑真模型）"""
import os
import sys
import tempfile
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TMP = tempfile.mkdtemp(prefix="ob_int_")
os.environ["AC_DB_PATH"] = os.path.join(TMP, "soul.db")
os.environ["AC_DEAD_LOCK"] = os.path.join(TMP, "dead.lock")

import obsession_pool as op
import soul_core
import search_utils
import main as M

PASS, FAIL = [], []
LOGS = []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)

_sink = []
_orig_add = op.ObsessionPool.add_or_reinforce
def _spy_add(self, content, **kw):
    r = _orig_add(self, content, **kw)
    if r:
        LOGS.append("[执念] 生成/加固执念：%s | 当前张力：%.1f" % (r["content"], r["tension"]))
    return r
op.ObsessionPool.add_or_reinforce = _spy_add

def make_life(vitality=100, reuse_pool=None):
    """构造一个只带执念能力的轻量 EntropyLife（不初始化真实系统）。

    默认每个 life 用独立临时库，避免跨用例脏数据互相污染。
    """
    life = M.EntropyLife.__new__(M.EntropyLife)
    if reuse_pool is not None:
        life.obsessions = reuse_pool
    else:
        d = tempfile.mkdtemp(prefix="ob_case_")
        life.obsessions = op.ObsessionPool(os.path.join(d, "soul.db"))
    class _S:
        pass
    soul = _S()
    soul.vitality = vitality
    life.soul = soul
    life.engine = None
    life._init_resource_kernel = lambda: None
    return life


print("=" * 68)
print(" AC OS V6.7 · 执念接入主循环验收（Mock）")
print("=" * 68)

# ---------------- T1 工具失败沉淀 ----------------
print("\n[T1] 工具调用失败 -> 沉淀为执念（去重）")
life = make_life(100)
for i in range(5):
    life._obsess("工具调用失败：搜索 GitHub 超时")
check("T1.1 5 次相同失败只有 1 条执念", life.obsessions.count() == 1,
      "(rows=%d)" % life.obsessions.count())
g = life.obsessions.open_gaps()[0]
check("T1.2 张力叠加到 0.7", abs(g["tension"] - 0.7) < 1e-6, "%.2f" % g["tension"])
check("T1.3 打印执念日志", any("生成/加固执念" in m for m in LOGS), str(LOGS[:1]))

# ---------------- T2 认输信号 ----------------
print("\n[T2] 大模型输出「不知道 / 无法解决」")
life2 = make_life(100)
life2._obsess_from_output("这个问题我不知道答案")
check("T2.1 认输输出生成执念", life2.obsessions.count() == 1, str(life2.obsessions.count()))
life2._obsess_from_output("我明白了，答案是 42")
check("T2.2 正常输出不生成执念", life2.obsessions.count() == 1, str(life2.obsessions.count()))

# ---------------- T3 心跳 ----------------
print("\n[T3] 心跳发酵")
life3 = make_life(100)
life3._obsess("未解决：量子引力")
start = life3.obsessions.open_gaps()[0]["tension"]
for _ in range(20):
    life3._obsession_heartbeat()
end = life3.obsessions.open_gaps()[0]["tension"]
check("T3.1 20 轮心跳张力上涨", end > start, "%.2f -> %.2f" % (start, end))
check("T3.2 涨幅 +0.02/轮", abs(end - (start + 0.4)) < 1e-6, "%.2f" % end)

# ---------------- T4 生存红线：强制休眠 ----------------
print("\n[T4] vitality=20 + 张力0.9 -> 不唤醒（保命）")
life4 = make_life(20)
r = life4._obsess("濒死执念")
c = sqlite3.connect(life4.obsessions.db)
c.execute("UPDATE gaps SET tension=0.9 WHERE id=?", (r["id"],))
c.commit()
c.close()
gap = life4._check_obsession_wake()
check("T4.1 生命值 20 时不唤醒", gap is None, str(gap))
check("T4.2 张力仍是 0.9 未被消化", abs(life4.obsessions.get(r["id"])["tension"] - 0.9) < 1e-6)

# 生命值充足才唤醒（复用同一个池，验证同一执念在满血时能唤醒）
life5 = make_life(100, reuse_pool=life4.obsessions)
gap = life5._check_obsession_wake()
check("T4.3 生命值 100 时唤醒", gap is not None and gap["id"] == r["id"],
      str(gap and gap.get("id")))

# ---------------- T5 探索与解结 ----------------
print("\n[T5] 执念探索：成功解结 / 失败计次")
life6 = make_life(100)
r6 = life6._obsess("未解决：某问题")
c = sqlite3.connect(life6.obsessions.db)
c.execute("UPDATE gaps SET tension=0.9 WHERE id=?", (r6["id"],))
c.commit()
c.close()

_orig_search = search_utils.web_search
search_utils.web_search = lambda q, bridge=None: "这是一段足够长的搜索结果，提供了有价值的线索内容。"
try:
    life6._pursue_obsession(life6.obsessions.get(r6["id"]))
finally:
    search_utils.web_search = _orig_search
g6 = life6.obsessions.get(r6["id"])
check("T5.1 探索成功 -> resolved", g6["status"] == "resolved", g6["status"])
check("T5.2 张力清零", g6["tension"] == 0.0, str(g6["tension"]))

# 失败累积 -> 压制
life7 = make_life(100)
r7 = life7._obsess("无法解决的怪题")
c = sqlite3.connect(life7.obsessions.db)
c.execute("UPDATE gaps SET tension=0.9 WHERE id=?", (r7["id"],))
c.commit()
c.close()
search_utils.web_search = lambda q, bridge=None: ""
try:
    for _ in range(3):
        life7._pursue_obsession(life7.obsessions.get(r7["id"]))
finally:
    search_utils.web_search = _orig_search
g7 = life7.obsessions.get(r7["id"])
check("T5.3 连续 3 次失败 -> 张力压到 0.5", abs(g7["tension"] - 0.5) < 1e-6,
      "%.2f" % g7["tension"])
check("T5.4 仍未解结", g7["status"] == "open", g7["status"])

# ---------------- T6 主循环未被破坏 ----------------
print("\n[T6] 主循环完整性")
src = open(os.path.join(HERE, "main.py"), encoding="utf-8").read()
check("T6.1 _on_idle 仍存在", "def _on_idle(self):" in src)
check("T6.2 执念唤醒在 idle 流程内", "_check_obsession_wake()" in src)
check("T6.3 原进化流水线逻辑保留", "sf.run_evolution_cycle" in src)
check("T6.4 梦境与睡眠代谢保留", "self.sleep_metabolism()" in src)

print("\n" + "=" * 68)
print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" 失败项:", FAIL)
print("=" * 68)
sys.exit(0 if not FAIL else 1)
