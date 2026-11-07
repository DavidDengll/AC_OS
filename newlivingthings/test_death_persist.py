# -*- coding: utf-8 -*-
"""V6.5 死亡落库验收：dead.lock 写出时，soul_state 必须同步为 vitality=0/dead=1/round=实际轮次"""
import os, sys, tempfile, sqlite3, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TMP = tempfile.mkdtemp(prefix="ac_death_")
os.environ["AC_DB_PATH"] = os.path.join(TMP, "soul.db")
os.environ["AC_DEAD_LOCK"] = os.path.join(TMP, "dead.lock")
import soul_core

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)

def read_state():
    c = sqlite3.connect(soul_core.DB_PATH)
    try:
        return {k: v for k, v in c.execute("SELECT key,value FROM soul_state")}
    finally:
        c.close()

print("=" * 66)
print(" AC OS V6.5 · 死亡落库验收")
print("=" * 66)
print(" 临时库:", soul_core.DB_PATH)

# T1 真实死亡链：扣血到 0 -> terminate -> 库里必须是死亡态
print("\n[T1] 真实扣血到 0 -> terminate")
s = soul_core.SoulState()
s.round = 176
s.vitality = 3
s.last_reflect_round = 145
s.save()
check("T1.0 死亡前 vitality=3 round=176",
      read_state()["vitality"] == "3" and read_state()["round"] == "176")

s.spend(5, "思考耗能")                       # 真实扣血，归零
ok = soul_core.terminate(s, "生命值归零（第 %d 轮，思考耗能耗尽）" % s.round,
                         exit_code=1, do_exit=False)
st = read_state()
check("T1.1 dead.lock 已写出", ok is True and os.path.exists(soul_core.DEAD_LOCK))
check("T1.2 dead 落库为 1", st.get("dead") == "1", st.get("dead"))
check("T1.3 vitality 落库为 0", st.get("vitality") == "0", st.get("vitality"))
check("T1.4 round 为实际死亡轮次 176", st.get("round") == "176", st.get("round"))
check("T1.5 dead.lock 与 DB 轮次一致",
      str(soul_core.read_dead_lock().get("reason", "")).find("176") >= 0)

# T2 save() 抛异常时，强制落库仍能写入死亡态
print("\n[T2] 常规 save() 失败 -> 强制落库兜底")
os.environ["AC_DEAD_LOCK"] = os.path.join(TMP, "dead2.lock")
s2 = soul_core.SoulState()
s2.round = 200
s2.vitality = 1
s2.save()
orig_save = soul_core.SoulState.save
soul_core.SoulState.save = lambda self: (_ for _ in ()).throw(
    sqlite3.OperationalError("unable to open database file"))
try:
    soul_core.terminate(s2, "生命值归零（第 200 轮，模拟写库失败）",
                        exit_code=1, do_exit=False)
finally:
    soul_core.SoulState.save = orig_save
st2 = read_state()
check("T2.1 save 失败仍写出 dead.lock", os.path.exists(soul_core.DEAD_LOCK))
check("T2.2 save 失败仍强制落库 dead=1", st2.get("dead") == "1", st2.get("dead"))
check("T2.3 save 失败仍强制落库 vitality=0", st2.get("vitality") == "0", st2.get("vitality"))
check("T2.4 save 失败仍写入正确 round=200", st2.get("round") == "200", st2.get("round"))

# T3 强制落库有回读校验
print("\n[T3] _force_death_state 回读校验")
s3 = soul_core.SoulState()
s3.round = 321
s3.vitality = 44
s3.save()
res = soul_core._force_death_state(s3, "测试")
st3 = read_state()
check("T3.1 返回 True", res is True, str(res))
check("T3.2 dead=1", st3.get("dead") == "1")
check("T3.3 vitality=0", st3.get("vitality") == "0")
check("T3.4 round=321", st3.get("round") == "321", st3.get("round"))

# T4 幂等：重复终止不破坏数据
print("\n[T4] 重复终止幂等")
soul_core.terminate(s3, "重复终止", exit_code=1, do_exit=False)
st4 = read_state()
check("T4.1 重复终止后 dead 仍为 1", st4.get("dead") == "1")
check("T4.2 重复终止后 round 不变", st4.get("round") == "321")

print("\n" + "=" * 66)
print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL: print(" 失败项:", FAIL)
print("=" * 66)
sys.exit(0 if not FAIL else 1)
