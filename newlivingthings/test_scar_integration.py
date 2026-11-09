# -*- coding: utf-8 -*-
"""test_scar_integration.py —— 疤痕接入验收（Mock，不联网、不跑真模型）"""
import json
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)   # rebirth_engine.py 在仓库根目录

TMP = tempfile.mkdtemp(prefix="scar_int_")
os.environ["AC_DB_PATH"] = os.path.join(TMP, "soul.db")
os.environ["AC_DEAD_LOCK"] = os.path.join(TMP, "dead.lock")

import scar_system as ss
import soul_core
import main as M

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


def make_life(vitality=100):
    life = M.EntropyLife.__new__(M.EntropyLife)
    class _S:
        pass
    s = _S()
    s.vitality = vitality
    life.soul = s
    return life


print("=" * 68)
print(" AC OS V6.8 · 疤痕接入验收（Mock）")
print("=" * 68)

# ---------------- T1 濒死触发（接入主循环）----------------
print("\n[T1] 主循环 vitality 跌破 10 -> 自动生成疤痕")
db = os.environ["AC_DB_PATH"]
ss.ensure_schema(db)
life = make_life(50)
life._check_near_death_scar()
check("T1.1 生命值 50 不生成", len(ss.load_scars(db)) == 0, str(len(ss.load_scars(db))))

life.soul.vitality = 9
entry = life._check_near_death_scar()
scars = ss.load_scars(db)
check("T1.2 生命值 9 生成疤痕", entry is not None and len(scars) == 1, str(len(scars)))
check("T1.3 疤痕含事件/类型/时间",
      all(k in scars[0] for k in ("event", "type", "at")), str(scars[0].keys()))

life.soul.vitality = 3
life._check_near_death_scar()
check("T1.4 继续掉血不重复刷疤", len(ss.load_scars(db)) == 1, str(len(ss.load_scars(db))))

# ---------------- T2 内分泌基底调整 ----------------
print("\n[T2] _init_endocrine 读取疤痕调整基底")
db2 = os.path.join(tempfile.mkdtemp(prefix="scar_base_"), "soul.db")
ss.ensure_schema(db2)
for i in range(3):
    ss.add_scar(db2, "第 %d 次濒死" % i, "濒死")
orig_db = soul_core.DB_PATH
soul_core.DB_PATH = db2
try:
    life2 = M.EntropyLife.__new__(M.EntropyLife)
    life2.ENDO_STATE_FILE = os.path.join(TMP, "no_such_emotion.json")
    life2._init_endocrine()
    check("T2.1 基底 cortisol 0.3 -> 0.5（+0.2 封顶）",
          abs(life2.endo_base["cortisol"] - 0.5) < 1e-6, str(life2.endo_base))
    check("T2.2 endo 同步为调整后的基底",
          abs(life2.endo["cortisol"] - 0.5) < 1e-6, str(life2.endo))
    check("T2.3 偏移未超过 0.2",
          abs(life2.endo_base["cortisol"] - 0.3) <= 0.2 + 1e-9,
          "%.3f" % (life2.endo_base["cortisol"] - 0.3))
finally:
    soul_core.DB_PATH = orig_db

# 无疤痕时基底不变
db3 = os.path.join(tempfile.mkdtemp(prefix="scar_none_"), "soul.db")
ss.ensure_schema(db3)
soul_core.DB_PATH = db3
try:
    life3 = M.EntropyLife.__new__(M.EntropyLife)
    life3.ENDO_STATE_FILE = os.path.join(TMP, "no_such_emotion.json")
    life3._init_endocrine()
    check("T2.4 无疤痕时基底保持默认",
          abs(life3.endo_base["cortisol"] - 0.3) < 1e-9, str(life3.endo_base))
finally:
    soul_core.DB_PATH = orig_db

# ---------------- T3 Prompt 绝对注入 ----------------
print("\n[T3] build_panorama_prompt 顶端注入")
beats = [{"event": "第 1 次濒死", "type": "濒死", "at": "t", "shift": {"cortisol": 0.1}}]
class _Soul:
    vitality = 80
    scars = beats
p = soul_core.build_panorama_prompt({"dopamine": 0.5, "cortisol": 0.3}, _Soul(),
                                    dying=False, event_description="测试")
first_line = p.splitlines()[0]
check("T3.1 疤痕块位于 Prompt 第一行", "【底层心理创伤烙印】" in first_line, first_line[:60])
check("T3.2 含疤痕内容", "第 1 次濒死" in first_line)
check("T3.3 含固定尾句", "这些经历永远改变了你" in p)
check("T3.4 疤痕在生理指标之前",
      p.index("【底层心理创伤烙印】") < p.index("你的当前生理指标"))

class _NoScar:
    vitality = 80
    scars = []
p2 = soul_core.build_panorama_prompt({"dopamine": 0.5, "cortisol": 0.3}, _NoScar(),
                                     dying=False, event_description="测试")
check("T3.5 无疤痕时不注入", "【底层心理创伤烙印】" not in p2)
check("T3.6 无疤痕时首行仍是生理指标",
      p2.splitlines()[0].startswith("你的当前生理指标"), p2.splitlines()[0][:30])

# 最多 3 条
five = [{"event": "第 %d 次" % i, "type": "濒死", "at": "t", "shift": {"cortisol": 0.1}}
        for i in range(5)]
class _FiveSoul:
    vitality = 80
    scars = five
p3 = soul_core.build_panorama_prompt({"dopamine": 0.5, "cortisol": 0.3}, _FiveSoul(),
                                     dying=False, event_description="测试")
check("T3.7 最多注入 3 条", p3.splitlines()[0].count("；") <= 2, p3.splitlines()[0][:80])

# ---------------- T4 转世固化死因 ----------------
print("\n[T4] 转世复活 -> 前代死因固化为疤痕")
import rebirth_engine as rb

root = tempfile.mkdtemp(prefix="scar_rb_")
app = os.path.join(root, "newlivingthings")
state = os.path.join(root, "data", "state")
os.makedirs(app); os.makedirs(state)
for base in (app, state):
    ss.ensure_schema(os.path.join(base, "entropy_memory.db"))
    json.dump({"dopamine": 0.5}, open(os.path.join(base, "emotion_state.json"), "w"))
with open(os.path.join(app, "dead.lock"), "w", encoding="utf-8") as f:
    json.dump({"dead": True, "reason": "无法连接到宿主机桥接，断网濒死",
               "time": "t", "pid": 1}, f, ensure_ascii=False)

buf = []
orig_out = rb._out
rb._out = lambda m="": buf.append(m)
try:
    res = rb.rebirth(app_dir=app, state_dir=state,
                     archive_root=os.path.join(root, "_archive"))
finally:
    rb._out = orig_out

check("T4.1 转世成功", res["reason"] == "rebirth", res["reason"])
new_scars = ss.load_scars(os.path.join(app, "entropy_memory.db"))
check("T4.2 新实体带有疤痕", len(new_scars) == 1, str(len(new_scars)))
check("T4.3 疤痕事件即前代死因",
      new_scars and "断网濒死" in new_scars[0]["event"],
      str(new_scars[0]["event"]) if new_scars else "")
check("T4.4 创伤类型归类为断网濒死",
      new_scars and new_scars[0]["type"] == "断网濒死",
      str(new_scars[0]["type"]) if new_scars else "")
check("T4.5 打印疤痕固化日志", any("[疤痕]" in b for b in buf), str(buf[-2:]))
# 新肉体本身仍满血
c = sqlite3.connect(os.path.join(app, "entropy_memory.db"))
st = dict(c.execute("SELECT key,value FROM soul_state"))
c.close()
check("T4.6 新肉体仍满血 100", st.get("vitality") == "100", st.get("vitality"))

# ---------------- T5 不破坏既有功能 ----------------
print("\n[T5] 既有功能完整性")
src_main = open(os.path.join(HERE, "main.py"), encoding="utf-8").read()
check("T5.1 执念池挂载仍在", "self.obsessions" in src_main)
check("T5.2 梦境逻辑仍在", "self._should_dream()" in src_main)
check("T5.3 温度劫持仍在", "生理劫持" in src_main)
check("T5.4 主循环 _on_idle 仍在", "def _on_idle(self):" in src_main)

print("\n" + "=" * 68)
print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" 失败项:", FAIL)
print("=" * 68)
sys.exit(0 if not FAIL else 1)
