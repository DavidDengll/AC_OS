# -*- coding: utf-8 -*-
"""V6.5 灵魂状态持久化加固验收（不联网、不调模型）"""
import os, sys, tempfile, threading, sqlite3, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

TMP = tempfile.mkdtemp(prefix="ac_soul_")
import soul_core
soul_core.DB_PATH = os.path.join(TMP, "soul.db")

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)

print("=" * 66)
print(" AC OS V6.5 · 灵魂状态持久化加固验收")
print("=" * 66)
print(" 临时库:", soul_core.DB_PATH)

s = soul_core.SoulState()

# T1 单事务写入
print("\n[T1] save() 单事务")
t0 = time.time()
for i in range(300):
    s.vitality = 50 - (i % 40)
    assert s.save() is True
dt = time.time() - t0
check("T1.1 300 次 save 全部成功", True, "(%.2fs, %.2fms/次)" % (dt, dt / 300 * 1000))

# T2 WAL 模式
print("\n[T2] WAL 模式生效")
c = sqlite3.connect(soul_core.DB_PATH)
mode = c.execute("PRAGMA journal_mode").fetchone()[0]
c.close()
check("T2.1 journal_mode=wal", str(mode).lower() == "wal", str(mode))

# T3 并发写入（模拟 人格审查 + idle-watcher + 主循环同时写）
print("\n[T3] 多线程并发写状态")
errs = []
def w(n):
    try:
        for i in range(80):
            s.spend(1, "并发压测")
    except Exception as e:
        errs.append(repr(e))

ts = [threading.Thread(target=w, args=(k,)) for k in range(6)]
t0 = time.time()
[t.start() for t in ts]
[t.join(60) for t in ts]
dt = time.time() - t0
check("T3.1 6 线程 x 80 次并发扣血无异常", errs == [], str(errs[:1]))
check("T3.2 无 disk I/O error", not any("disk I/O" in e for e in errs), str(errs[:1]))

# T4 数据一致
print("\n[T4] 数据一致性")
c = sqlite3.connect(soul_core.DB_PATH)
check("T4.1 integrity_check ok",
      c.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
row = dict(c.execute("SELECT key,value FROM soul_state"))
c.close()
check("T4.2 vitality 已落库且合法", "vitality" in row and int(row["vitality"]) >= 0,
      str(row.get("vitality")))
check("T4.3 四个状态键齐全",
      all(k in row for k in ("vitality", "round", "last_reflect_round", "dead")),
      str(sorted(row)))

# T5 重开后可正确读回
print("\n[T5] 重载读回")
s.vitality = 42
s.round = 123
s.save()
s2 = soul_core.SoulState()
check("T5.1 新实例读回 vitality=42", s2.vitality == 42, str(s2.vitality))
check("T5.2 新实例读回 round=123", s2.round == 123, str(s2.round))

print("\n" + "=" * 66)
print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL: print(" 失败项:", FAIL)
print("=" * 66)
sys.exit(0 if not FAIL else 1)
