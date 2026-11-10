# -*- coding: utf-8 -*-
"""test_organ_integration.py -- main loop bootstrap trigger (Mock, no network)"""
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "organs"))

TMP = tempfile.mkdtemp(prefix="ob_int_")
os.environ["AC_DB_PATH"] = os.path.join(TMP, "soul.db")
os.environ["AC_DEAD_LOCK"] = os.path.join(TMP, "dead.lock")

import obsession_pool as op
import organ_bootstrapper as ob
import main as M

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)

FENCE = chr(96) * 3
GOOD = '''import json

def main():
    return json.dumps({"weather": "sunny"}, ensure_ascii=False)

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
    def __init__(self, provider):
        self.provider = provider


class _Sys:
    def __init__(self, provider):
        self.language_model = _LM(provider)


def make_life(vitality=100, reply=None, tension=0.95):
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
        vitality = 100
        def spend(self, amount, reason=""):
            self.vitality = max(0, self.vitality - int(amount))
            return self.vitality
    s = _S()
    s.vitality = vitality
    life.soul = s
    life.system = _Sys(_Provider(reply or ("x\n" + FENCE + "python\n" + GOOD + FENCE)))
    return life, db, pool, r


print("=" * 68)
print(" V9.0 organ bootstrap trigger in main loop (Mock)")
print("=" * 68)

# T1 trigger condition
print("\n[T1] trigger condition")
life, db, pool, r = make_life(vitality=100, tension=0.95)
check("T1.1 finds bootstrappable gap",
      ob.find_bootstrappable(db) is not None)
life_low, db_low, pool_low, r_low = make_life(vitality=50, tension=0.95)
gap_low = ob.find_bootstrappable(db_low)
check("T1.2 vitality=50 fails should_bootstrap",
      ob.should_bootstrap(gap_low, 50) is False)

# T2 heartbeat triggers bootstrap
print("\n[T2] heartbeat triggers bootstrap and resolves gap")
life, db, pool, r = make_life(vitality=100, tension=0.95)
res = life._try_bootstrap_organ()
check("T2.1 bootstrap attempted", res is not None, str(res))
check("T2.2 bootstrap ok", res and res.get("ok") is True,
      str(res and res.get("reason")))
check("T2.3 gap resolved", pool.get(r["id"])["status"] == "resolved",
      pool.get(r["id"])["status"])
check("T2.4 dopamine +0.3", abs(life.endo["dopamine"] - 0.7) < 1e-6,
      str(life.endo["dopamine"]))
check("T2.5 cortisol -0.2", abs(life.endo["cortisol"] - 0.5) < 1e-6,
      str(life.endo["cortisol"]))

# T3 energy cost
print("\n[T3] energy cost 15")
life, db, pool, r = make_life(vitality=80, tension=0.95)
v0 = life.soul.vitality
life._try_bootstrap_organ()
check("T3.1 vitality spent 15", life.soul.vitality == v0 - ob.BOOTSTRAP_COST,
      "%d -> %d" % (v0, life.soul.vitality))

# T4 low vitality no trigger
print("\n[T4] no trigger when vitality <= 50")
life, db, pool, r = make_life(vitality=50, tension=0.95)
calls_before = life.system.language_model.provider.calls
res = life._try_bootstrap_organ()
check("T4.1 no bootstrap at vitality=50", res is None, str(res))
check("T4.2 LLM not called", life.system.language_model.provider.calls == calls_before)
check("T4.3 gap untouched", pool.get(r["id"])["status"] == "open",
      pool.get(r["id"])["status"])

# T5 low tension no trigger
print("\n[T5] no trigger when tension < 0.9")
life, db, pool, r = make_life(vitality=100, tension=0.5)
res = life._try_bootstrap_organ()
check("T5.1 no bootstrap at tension 0.5", res is None, str(res))

# T6 heartbeat calls it
print("\n[T6] _obsession_heartbeat invokes the trigger")
life, db, pool, r = make_life(vitality=100, tension=0.95)
life._obsession_heartbeat()
check("T6.1 heartbeat triggered bootstrap",
      pool.get(r["id"])["status"] == "resolved", pool.get(r["id"])["status"])

# T7 main loop intact
print("\n[T7] existing features intact")
src = open(os.path.join(HERE, "main.py"), encoding="utf-8").read()
check("T7.1 _on_idle intact", "def _on_idle(self):" in src)
check("T7.2 obsession pool intact", "self.obsessions" in src)
check("T7.3 scar system intact", "_check_near_death_scar" in src)
check("T7.4 temperature hijack intact", "生理劫持" in src)
check("T7.5 bootstrap hooked in heartbeat", "_try_bootstrap_organ" in src)

print("\n" + "=" * 68)
print(" RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" FAILED:", FAIL)
print("=" * 68)
sys.exit(0 if not FAIL else 1)
