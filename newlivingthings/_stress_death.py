# -*- coding: utf-8 -*-
"""压力验证：用真实的 spend() 把生命值打到 0，检查 dead.lock 与进程退出。"""
import os, sys, tempfile
# 允许外部指定（verify_soul_v45.py 需要知道锁写在哪），否则自建临时目录
if not os.environ.get("AC_DEAD_LOCK"):
    tmp = tempfile.mkdtemp(prefix="ac_stress_")
    os.environ["AC_DB_PATH"] = os.path.join(tmp, "stress.db")
    os.environ["AC_DEAD_LOCK"] = os.path.join(tmp, "dead.lock")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); os.chdir(HERE)
import soul_core

soul = soul_core.SoulState()
soul.vitality = 25
soul.round = 3
soul.save()
print("[压力] 初始生命值=%d，锁存在=%s" % (soul.vitality, soul_core.dead_lock_exists()), flush=True)

# 真实扣血路径：连续工具失败
for i in range(3):
    print("[压力] 第 %d 次工具失败.." % (i + 1), flush=True)
    soul.spend(soul_core.COST_TOOL_ERROR, "ZeptoClaw 调用失败")
    if soul.vitality <= 0:
        break
print("[压力] 扣血后生命值=%d" % soul.vitality, flush=True)

# 真实死亡链
soul_core.terminate(soul, "压力测试：工具连续失败致生命值归零", exit_code=1)
print("[压力] !!! 不应走到这里 !!!", flush=True)
