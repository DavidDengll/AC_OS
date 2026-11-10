# -*- coding: utf-8 -*-
"""test_bootstrap_cooldown.py -- V9.0 全局冷却锁验收（Mock，不联网）"""
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "organs"))

TMP = tempfile.mkdtemp(prefix="cd_")
os.environ["AC_DB_PATH"] = os.path.join(TMP, "soul.db")
os.environ["AC_DEAD_LOCK"] = os.path.join(TMP, "dead.lock")

import obsession_pool as op
import bootstrap_cooldown as bc
import main as M

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)

FENCE = chr(96) * 3
GOOD = '''import json

def main():
    return json.dumps({"ok": True}, ensure_ascii=False)

if __name__ == "__main__":
    print(main())
'''


class _Provider:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0
    def chat(self, messages, temperature=0.7, max_tokens=600, **kw):
        self.calls += 1
        return self.reply


class _LM:
    def __init__(self, p):
        self.provider = p


class _Sys:
    def __init__(self, p):
        self.language_model = _LM(p)


def make_life(vitality=100, tension=0.95, round_no=100):
    d = tempfile.mkdtemp(prefix="case_")
    db = os.path.join(d, "soul.db")
    pool = op.ObsessionPool(db, log=lambda m: None)
    r = pool.add_or_reinforce("weather")
    c = sqlite3.connect(db)
    c.execute("UPDATE gaps SET tension=? WHERE id=?", (tension, r["id"]))
    c.commit()
    c.close()

    life = M.EntropyLife.__new__(M.EntropyLife)
    life.obsessions = pool
    life.endo = {"dopamine": 0.4, "cortisol": 0.7}

    class _S:
        def __init__(self):
            self.vitality = vitality
            self.round = round_no
        def spend(self, amount, reason=""):
            self.vitality = max(0, self.vitality - int(amount))
            return self.vitality
    life.soul = _S()
    life.system = _Sys(_Provider("x\n" + FENCE + "python\n" + GOOD + FENCE))
    return life, db, pool, r


print("=" * 70)
print(" V9.0 global bootstrap cooldown acceptance (Mock)")
print("=" * 70)

# T1 cooldown module basics
print("\n[T1] cooldown module")
d = tempfile.mkdtemp(prefix="cdm_")
db1 = os.path.join(d, "soul.db")
bc._conn(db1).close()
check("T1.1 never bootstrapped -> not cooling", bc.in_cooldown(db1, 100)[0] is False)
check("T1.2 default cooldown is 30", bc.COOLDOWN_ROUNDS == 30)

bc.set_last_round(db1, 100)
check("T1.3 same round -> cooling", bc.in_cooldown(db1, 100)[0] is True)
cool, remain = bc.in_cooldown(db1, 105)
check("T1.4 round 105 -> cooling, remain 25", cool is True and remain == 25,
      "cool=%s remain=%s" % (cool, remain))
check("T1.5 round 129 -> still cooling", bc.in_cooldown(db1, 129)[0] is True)
check("T1.6 round 130 -> released", bc.in_cooldown(db1, 130)[0] is False)
check("T1.7 round 131 -> released", bc.in_cooldown(db1, 131)[0] is False)
check("T1.8 round went backwards -> treated as released",
      bc.in_cooldown(db1, 5)[0] is False)
check("T1.9 persisted value readable", bc.get_last_round(db1) == 100)

# T2 lifecycle: first bootstrap works
print("\n[T2] first bootstrap allowed")
life, db, pool, r = make_life(vitality=100, round_no=100)
res = life._try_bootstrap_organ()
check("T2.1 first bootstrap ran", res is not None and res.get("ok") is True,
      str(res and res.get("reason")))
check("T2.2 vitality spent 15", life.soul.vitality == 85, str(life.soul.vitality))
check("T2.3 last_bootstrap_round recorded",
      bc.get_last_round(db) == 100, str(bc.get_last_round(db)))

# T3 same round -> blocked
print("\n[T3] immediately blocked by cooldown (anti-suicide)")
life2, db2, pool2, r2 = make_life(vitality=200, round_no=100)
life2._try_bootstrap_organ()
check("T3.0 baseline bootstrap done", bc.get_last_round(db2) == 100)
# 重新造一条高张力执念，模拟仍有执念未解
c = sqlite3.connect(db2)
c.execute("UPDATE gaps SET status='open', tension=0.95")
c.commit()
c.close()
v_before = life2.soul.vitality
import io
from contextlib import redirect_stdout
buf = io.StringIO()
with redirect_stdout(buf):
    res2 = life2._try_bootstrap_organ()
out = buf.getvalue()
check("T3.1 blocked in same round", res2 is None, str(res2))
check("T3.2 no vitality spent", life2.soul.vitality == v_before,
      "%d vs %d" % (v_before, life2.soul.vitality))
check("T3.3 prints cooldown message",
      "处于基因冷却期，拒绝突变" in out, out.strip()[:80])

# T4 multi-round: not drained
print("\n[T4] heartbeat across many rounds does NOT drain vitality")
life3, db3, pool3, r3 = make_life(vitality=100, round_no=0)
for rnd in range(0, 60):
    life3.soul.round = rnd
    c = sqlite3.connect(db3)
    c.execute("UPDATE gaps SET status='open', tension=0.95")
    c.commit()
    c.close()
    with redirect_stdout(io.StringIO()):
        life3._try_bootstrap_organ()

check("T4.1 survived 60 rounds", life3.soul.vitality > 0,
      "vitality=%d" % life3.soul.vitality)
check("T4.2 roughly 2 bootstraps in 60 rounds (30-round cooldown)",
      life3.soul.vitality in (70, 85), "vitality=%d" % life3.soul.vitality)
check("T4.3 not drained to death", life3.soul.vitality >= 70,
      "vitality=%d" % life3.soul.vitality)

# T5 cooldown released after 30 rounds
print("\n[T5] released after 30 rounds")
life4, db4, pool4, r4 = make_life(vitality=200, round_no=10)
life4._try_bootstrap_organ()
v0 = life4.soul.vitality
c = sqlite3.connect(db4)
c.execute("UPDATE gaps SET status='open', tension=0.95")
c.commit()
c.close()
life4.soul.round = 39
with redirect_stdout(io.StringIO()):
    res39 = life4._try_bootstrap_organ()
check("T5.1 round 39 (gap 29) still cooling", life4.soul.vitality == v0,
      "%d vs %d" % (v0, life4.soul.vitality))
life4.soul.round = 40
c = sqlite3.connect(db4)
c.execute("UPDATE gaps SET status='open', tension=0.95")
c.commit()
c.close()
with redirect_stdout(io.StringIO()):
    res40 = life4._try_bootstrap_organ()
check("T5.2 round 40 (gap 30) allowed again", life4.soul.vitality == v0 - 15,
      "%d -> %d" % (v0, life4.soul.vitality))

# T6 main loop intact
print("\n[T6] main loop intact")
src = open(os.path.join(HERE, "main.py"), encoding="utf-8").read()
check("T6.1 cooldown hooked", "bootstrap_cooldown" in src)
check("T6.2 _on_idle intact", "def _on_idle(self):" in src)
check("T6.3 scar system intact", "_check_near_death_scar" in src)
check("T6.4 temperature hijack intact", "生理劫持" in src)
check("T6.5 obsession pool intact", "self.obsessions" in src)

print("\n" + "=" * 70)
print(" RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" FAILED:", FAIL)
print("=" * 70)
sys.exit(0 if not FAIL else 1)
