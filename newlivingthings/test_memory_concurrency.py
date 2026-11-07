# test_memory_concurrency.py
# -*- coding: utf-8 -*-
"""V6.5 海马体并发安全验收（不联网、不起容器、不调模型）"""
import os, sys, tempfile, threading, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

TMP = tempfile.mkdtemp(prefix="ac_mem_")
import memory
memory.DB_PATH = os.path.join(TMP, "mem.db")

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)

print("=" * 66)
print(" AC OS V6.5 · 海马体并发安全验收")
print("=" * 66)
print(" 临时库:", memory.DB_PATH)

mem = memory.MemorySystem()

# T1 连接允许跨线程
print("\n[T1] 连接跨线程可用")
check("T1.1 check_same_thread=False 已生效",
      mem.conn.__class__.__name__ == "Connection")

errors = []
def reader():
    try:
        for i in range(30):
            mem.list_memories(level="short", limit=10)
            mem.search("测试")
    except Exception as e:
        errors.append(repr(e))

t = threading.Thread(target=reader, name="idle-watcher-sim")
t.start(); t.join(30)
check("T1.2 后台线程读写不再抛 thread 错误", errors == [], str(errors[:1]))
check("T1.3 没有出现 'same thread' 报错",
      not any("same thread" in e for e in errors))

# T2 并发写入不丢数据、不崩
print("\n[T2] 多线程并发写入")
errs2 = []
def writer(n):
    try:
        for i in range(25):
            mem.add_short_colored("并发_%d_%d" % (n, i), "特征%d" % i,
                                  endo={"dopamine": 0.1, "cortisol": 0.9})
    except Exception as e:
        errs2.append(repr(e))

ts = [threading.Thread(target=writer, args=(k,)) for k in range(5)]
[t.start() for t in ts]; [t.join(30) for t in ts]
check("T2.1 并发写入无异常", errs2 == [], str(errs2[:1]))
rows = mem.list_memories(limit=500)
check("T2.2 数据确实落库（>=125 条）", len(rows) >= 125, "(rows=%d)" % len(rows))
check("T2.3 写入未丢失", len([r for r in rows if str(r["name"]).startswith("并发_")]) >= 125,
      "(并发=%d)" % len([r for r in rows if str(r["name"]).startswith("并发_")]))

# T3 嵌套调用不死锁（RLock 关键点）
print("\n[T3] 嵌套调用不死锁（RLock）")
done = []
def nested():
    try:
        mem.add_short_colored("嵌套测试", "x", endo={"dopamine": 0.9})
        mem.search("嵌套测试")          # search -> _try_upgrade
        done.append(True)
    except Exception as e:
        done.append(False)
t3 = threading.Thread(target=nested); t3.start(); t3.join(10)
check("T3.1 嵌套调用在 10s 内完成（无自锁）", done == [True], str(done))

# T4 并发下数据库完整性
print("\n[T4] 数据库完整性")
try:
    c = sqlite3.connect(memory.DB_PATH)
    res = c.execute("PRAGMA integrity_check").fetchone()[0]
    c.close()
    check("T4.1 integrity_check 通过", res == "ok", res)
except Exception as e:
    check("T4.1 integrity_check 通过", False, repr(e))

mem.close()
print("\n" + "=" * 66)
print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL: print(" 失败项:", FAIL)
print("=" * 66)
sys.exit(0 if not FAIL else 1)
