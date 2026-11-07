# -*- coding: utf-8 -*-
"""test_rebirth.py —— 自动化转世协议验收（全 Mock，不拉容器、不碰真实数据）"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import rebirth_engine as rb

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


def capture(fn, *a, **k):
    """捕获 rb._out 输出。"""
    buf = []
    orig = rb._out
    rb._out = lambda msg="": buf.append(msg)
    try:
        res = fn(*a, **k)
    finally:
        rb._out = orig
    return res, "\n".join(buf)


def make_epoch(root, dead=True, bad_lock=False):
    """造一个含旧数据的纪元目录结构。"""
    app = os.path.join(root, "newlivingthings")
    state = os.path.join(root, "data", "state")
    os.makedirs(app, exist_ok=True)
    os.makedirs(state, exist_ok=True)

    # 旧库：vitality=7, round=176, dead=0（模拟真实历史）
    for base in (app, state):
        db = os.path.join(base, "entropy_memory.db")
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE IF NOT EXISTS soul_state (key TEXT PRIMARY KEY, value TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, name TEXT)")
        c.executemany("INSERT OR REPLACE INTO soul_state VALUES(?,?)",
                      [("vitality", "7"), ("round", "176"), ("dead", "0")])
        c.execute("INSERT INTO memories(name) VALUES('旧记忆')")
        c.commit()
        c.close()
        with open(os.path.join(base, "emotion_state.json"), "w", encoding="utf-8") as f:
            json.dump({"dopamine": 0.9, "cortisol": 0.95}, f)

    # 走马灯
    log = os.path.join(app, "evolution_log.jsonl")
    with open(log, "w", encoding="utf-8") as f:
        for i in range(1, 9):
            f.write(json.dumps({"seq": i, "event": "e%d" % i}, ensure_ascii=False) + "\n")

    if dead:
        content = ("{ this is not json" if bad_lock else
                   json.dumps({"dead": True, "reason": "生命值归零（第 176 轮）",
                               "time": "2026-11-07 13:05:42", "pid": 1},
                              ensure_ascii=False))
        with open(os.path.join(app, "dead.lock"), "w", encoding="utf-8") as f:
            f.write(content)
    return app, state


print("=" * 66)
print(" AC OS · 自动化转世协议验收（Mock，不启动容器）")
print("=" * 66)

# ---------------- T1 无死亡时跳过 ----------------
print("\n[T1] 未检测到 dead.lock -> 直接跳过，不动任何文件")
root = tempfile.mkdtemp(prefix="rb1_")
app, state = make_epoch(root, dead=False)
before = os.path.getmtime(os.path.join(app, "entropy_memory.db"))
res, out = capture(rb.rebirth, app_dir=app, state_dir=state,
                   archive_root=os.path.join(root, "_archive"))
check("T1.1 reason=alive", res["reason"] == "alive", res["reason"])
check("T1.2 未创建归档目录", not os.path.isdir(os.path.join(root, "_archive")))
check("T1.3 旧库未被改动", os.path.getmtime(os.path.join(app, "entropy_memory.db")) == before)
check("T1.4 打印跳过提示", "跳过转世" in out)

# ---------------- T2 正常转世 ----------------
print("\n[T2] 检测到 dead.lock -> 完整转世")
root = tempfile.mkdtemp(prefix="rb2_")
app, state = make_epoch(root, dead=True)
arc_root = os.path.join(root, "_archive")
res, out = capture(rb.rebirth, app_dir=app, state_dir=state, archive_root=arc_root)
print("  ---- 终端输出 ----")
for ln in out.splitlines():
    print("  | " + ln)

check("T2.1 reason=rebirth", res["reason"] == "rebirth", res["reason"])
check("T2.2 打印 🚨 [轮回指令] 检测到前代熵灵已死亡", "🚨 [轮回指令]" in out and "正在读取遗言" in out)
check("T2.3 打印遗言原因", "第 176 轮" in out)
check("T2.4 打印死亡时间", "2026-11-07 13:05:42" in out)
check("T2.5 打印走马灯", "走马灯" in out)
check("T2.6 走马灯是最后 5 行（含 seq=8）", '"seq": 8' in out and '"seq": 3' not in out)
check("T2.7 打印 [轮回] 旧纪元数据已封存", "[轮回] 旧纪元数据已封存，全新肉体已就绪" in out)
check("T2.8 归档目录存在且带 epoch 前缀",
      res["archive_dir"] and os.path.isdir(res["archive_dir"])
      and "epoch_" in os.path.basename(res["archive_dir"]))

# 旧文件已移入归档
# 注意：dead.lock 由 soul_core 写入工作目录（DEAD_LOCK = HERE/dead.lock），
# 真实环境里 data/state 下不会有它，所以只断言 workspace 侧。
arc = res["archive_dir"]
for sub, names in (("workspace", ("entropy_memory.db", "emotion_state.json", "dead.lock")),
                   ("persist", ("entropy_memory.db", "emotion_state.json"))):
    for name in names:
        p = os.path.join(arc, sub, name)
        check("T2.9 归档 %s/%s" % (sub, name), os.path.exists(p))

# 旧数据未丢失（归档库仍可读出 vitality=7）
c = sqlite3.connect(os.path.join(arc, "workspace", "entropy_memory.db"))
old = dict(c.execute("SELECT key,value FROM soul_state"))
old_mem = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
c.close()
check("T2.10 归档库保留旧生命值 7", old.get("vitality") == "7", str(old))
check("T2.11 归档库保留旧记忆", old_mem == 1, str(old_mem))

# 新肉体
for base, label in ((app, "工作目录"), (state, "持久卷")):
    c = sqlite3.connect(os.path.join(base, "entropy_memory.db"))
    st = dict(c.execute("SELECT key,value FROM soul_state"))
    nm = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    c.close()
    with open(os.path.join(base, "emotion_state.json"), encoding="utf-8") as f:
        emo = json.load(f)
    check("T2.12 %s 新库 vitality=100" % label, st.get("vitality") == "100", st.get("vitality"))
    check("T2.13 %s 新库 round=0 dead=0" % label,
          st.get("round") == "0" and st.get("dead") == "0", str(st))
    check("T2.14 %s 新库记忆为空（干净）" % label, nm == 0, str(nm))
    check("T2.15 %s 新内分泌 D=C=E=0.5" % label,
          emo.get("dopamine") == 0.5 and emo.get("cortisol") == 0.5
          and emo.get("endorphin") == 0.5, str(emo))

check("T2.16 dead.lock 已从工作目录移走",
      not os.path.exists(os.path.join(app, "dead.lock")))
check("T2.17 归档元数据已生成",
      os.path.exists(os.path.join(arc, "REBIRTH_META.json")))

# ---------------- T3 遗言模糊 ----------------
print("\n[T3] dead.lock 损坏 -> 打印「遗言已模糊」")
root = tempfile.mkdtemp(prefix="rb3_")
app, state = make_epoch(root, dead=True, bad_lock=True)
res, out = capture(rb.rebirth, app_dir=app, state_dir=state,
                   archive_root=os.path.join(root, "_archive"))
check("T3.1 仍能完成转世", res["reason"] == "rebirth", res["reason"])
check("T3.2 打印遗言已模糊", "遗言已模糊" in out)
check("T3.3 走马灯仍然打印", "走马灯" in out)

# ---------------- T3b 带 BOM 的 dead.lock ----------------
print("\n[T3b] dead.lock 带 UTF-8 BOM（PowerShell 写文件的常见形态）")
root = tempfile.mkdtemp(prefix="rb3b_")
app, state = make_epoch(root, dead=False)
lock = os.path.join(app, "dead.lock")
with open(lock, "w", encoding="utf-8-sig") as f:   # utf-8-sig 会写 BOM
    json.dump({"dead": True, "reason": "BOM 赐死", "time": "T", "pid": 9}, f)
raw = open(lock, "rb").read()
check("T3b.1 测试锁确实带 BOM", raw[:3] == b"\xef\xbb\xbf", str(raw[:3]))
res, out = capture(rb.rebirth, app_dir=app, state_dir=state,
                   archive_root=os.path.join(root, "_archive"), dry_run=True)
check("T3b.2 带 BOM 仍能读出遗言", "BOM 赐死" in out, out[:120])
check("T3b.3 不误判为遗言已模糊", "遗言已模糊" not in out)

# ---------------- T4 dry-run ----------------
print("\n[T4] --dry-run 不改动任何文件")
root = tempfile.mkdtemp(prefix="rb4_")
app, state = make_epoch(root, dead=True)
arc_root = os.path.join(root, "_archive")
res, out = capture(rb.rebirth, app_dir=app, state_dir=state,
                   archive_root=arc_root, dry_run=True)
check("T4.1 打印 DRY-RUN", "DRY-RUN" in out)
check("T4.2 未创建归档目录", not os.path.isdir(arc_root))
check("T4.3 dead.lock 仍在", os.path.exists(os.path.join(app, "dead.lock")))
c = sqlite3.connect(os.path.join(app, "entropy_memory.db"))
v = dict(c.execute("SELECT key,value FROM soul_state")).get("vitality")
c.close()
check("T4.4 旧库未被重置", v == "7", str(v))

# ---------------- T5 归档不覆盖 ----------------
print("\n[T5] 同秒多次转世不覆盖归档")
root = tempfile.mkdtemp(prefix="rb5_")
app, state = make_epoch(root, dead=True)
arc_root = os.path.join(root, "_archive")
r1, _ = capture(rb.rebirth, app_dir=app, state_dir=state, archive_root=arc_root)
# 再制造一次死亡
with open(os.path.join(app, "dead.lock"), "w", encoding="utf-8") as f:
    f.write(json.dumps({"dead": True, "reason": "第二世", "time": "t", "pid": 2}))
r2, _ = capture(rb.rebirth, app_dir=app, state_dir=state, archive_root=arc_root)
arcs = [d for d in os.listdir(arc_root) if d.startswith("epoch_")]
check("T5.1 生成两个独立归档目录", len(arcs) == 2, str(arcs))
check("T5.2 两次归档目录不同", r1["archive_dir"] != r2["archive_dir"])

# ---------------- T6 必须运行在宿主机 ----------------
print("\n[T6] 运行环境红线")
src = open(os.path.join(HERE, "rebirth_engine.py"), encoding="utf-8").read()
check("T6.1 未被挂进容器启动命令",
      "rebirth_engine" not in open(os.path.join(HERE, "docker-compose.yml"),
                                   encoding="utf-8").read())
check("T6.2 只在宿主机端调用（start_ac_os.bat 中存在）",
      "rebirth_engine.py" in open(os.path.join(HERE, "start_ac_os.bat"),
                                  encoding="utf-8", errors="replace").read())

print("\n" + "=" * 66)
print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" 失败项:", FAIL)
print("=" * 66)
sys.exit(0 if not FAIL else 1)
