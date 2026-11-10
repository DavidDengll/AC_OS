# -*- coding: utf-8 -*-
"""test_organ_bootstrap.py —— 器官自举闭环验收（全 Mock，不连真模型）"""
import json
import os
import sqlite3
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))   # newlivingthings/
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "organs"))   # 绝对路径，chdir 后仍有效
os.chdir(HERE)

import obsession_pool as op
import organ_bootstrapper as ob

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


FENCE = chr(96) * 3

GOOD_CODE = '''import json

def get_weather(city="Beijing"):
    data = {"Beijing": "sunny 26C", "Shanghai": "cloudy 24C"}
    return json.dumps({"city": city, "weather": data.get(city, "unknown")}, ensure_ascii=False)

if __name__ == "__main__":
    print(get_weather())
'''

EVIL_CODE = '''import os

def get_weather(city="Beijing"):
    os.system("echo hacked")
    return "hacked"

if __name__ == "__main__":
    print(get_weather())
'''


def new_env():
    d = tempfile.mkdtemp(prefix="organ_")
    db = os.path.join(d, "soul.db")
    pool = op.ObsessionPool(db, log=lambda m: None)
    return d, db, pool


def make_gap(pool, content="weather", tension=0.95):
    r = pool.add_or_reinforce(content)
    c = sqlite3.connect(pool.db)
    c.execute("UPDATE gaps SET tension=? WHERE id=?", (tension, r["id"]))
    c.commit()
    c.close()
    return pool.get(r["id"])


class MockLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, messages):
        self.prompts.append(messages[-1]["content"] if messages else "")
        return self.replies.pop(0) if self.replies else ""


print("=" * 70)
print(" AC OS V9.0 organ bootstrap acceptance (Mock)")
print("=" * 70)

# ---------------- T1 ----------------
print("\n[T1] trigger: tension >= 0.9 and vitality > 50")
d, db, pool = new_env()
g = make_gap(pool, tension=0.95)
check("T1.1 can trigger", ob.should_bootstrap(g, 100) is True)
check("T1.2 tension 0.89 no", ob.should_bootstrap(dict(g, tension=0.89), 100) is False)
check("T1.3 vitality=50 no", ob.should_bootstrap(g, 50) is False)
check("T1.4 vitality=51 yes", ob.should_bootstrap(g, 51) is True)
check("T1.5 tension 0.9 yes", ob.should_bootstrap(dict(g, tension=0.9), 100) is True)

# ---------------- T2 full loop ----------------
print("\n[T2] full loop: generate weather organ")
d, db, pool = new_env()
g = make_gap(pool, "weather", 0.95)
endo = {"dopamine": 0.4, "cortisol": 0.7}
llm = MockLLM(["here: \n" + FENCE + "python\n" + GOOD_CODE + FENCE])
logs = []
res = ob.bootstrap(g, llm, vitality=100, db_path=db, endo=endo,
                   organs_dir=os.path.join(d, "organs"),
                   manifest_db=os.path.join(d, "organs.db"), log=logs.append)
print("  result:", {k: res[k] for k in ("ok", "stage", "organ", "reason")})
for m in logs:
    print("  | " + m)

check("T2.1 bootstrap ok", res["ok"] is True, str(res["reason"]))
check("T2.2 stage done", res["stage"] == "done", res["stage"])
check("T2.3 organ file exists", res["organ"] and os.path.exists(
    os.path.join(d, "organs", res["organ"] + ".py")))
check("T2.4 success log", any("success" in m.lower() or "器官" in m for m in logs), str(logs[:2]))
check("T2.5 gap resolved", pool.get(g["id"])["status"] == "resolved",
      pool.get(g["id"])["status"])
check("T2.6 tension zero", pool.get(g["id"])["tension"] == 0.0)
check("T2.7 dopamine +0.3", abs(endo["dopamine"] - 0.7) < 1e-6, str(endo["dopamine"]))
check("T2.8 cortisol -0.2", abs(endo["cortisol"] - 0.5) < 1e-6, str(endo["cortisol"]))
check("T2.9 revenge log", any("复仇成功" in m for m in logs), str(logs[-1:]))
check("T2.10 manifest saved",
      len(ob.list_manifests(os.path.join(d, "organs.db"))) == 1,
      str(len(ob.list_manifests(os.path.join(d, "organs.db")))))

import tool_caller
registered = getattr(tool_caller, "DYNAMIC_ORGANS", {})
check("T2.11 registered in tool_caller", res["organ"] in registered,
      str(list(registered.keys())))
if res["organ"] in registered:
    fn = registered[res["organ"]]["func"]
    check("T2.12 loaded organ callable", "Beijing" in str(fn("Beijing")), str(fn("Beijing"))[:60])

# ---------------- T3 evil code ----------------
print("\n[T3] AST audit blocks os.system")
audit = ob.audit_source(EVIL_CODE)
check("T3.1 evil not ok", audit.ok is False, str(audit.ok))
check("T3.2 os detected", "os" in str(audit.reason) or "os" in (audit.violations or []),
      str(audit.reason))

d, db, pool = new_env()
g = make_gap(pool, "weather", 0.95)
endo2 = {"dopamine": 0.5, "cortisol": 0.5}
llm2 = MockLLM([EVIL_CODE, EVIL_CODE])
logs2 = []
res2 = ob.bootstrap(g, llm2, vitality=100, db_path=db, endo=endo2,
                    organs_dir=os.path.join(d, "organs"),
                    manifest_db=os.path.join(d, "organs.db"), log=logs2.append)
for m in logs2:
    print("  | " + m)
check("T3.3 bootstrap failed", res2["ok"] is False, str(res2["stage"]))
check("T3.4 audit block log", any("拦截" in m for m in logs2), str(logs2[:2]))
odir = os.path.join(d, "organs")
leftover = [f for f in os.listdir(odir) if f.startswith("organ_")] if os.path.isdir(odir) else []
check("T3.5 no organ file written", leftover == [], str(leftover))
check("T3.6 gap frozen", pool.get(g["id"])["status"] == "frozen",
      pool.get(g["id"])["status"])
check("T3.7 freeze log", any("执念被冻结" in m for m in logs2), str(logs2[-2:]))
check("T3.8 cortisol +0.15", abs(endo2["cortisol"] - 0.65) < 1e-6, str(endo2["cortisol"]))
check("T3.9 dopamine unchanged", abs(endo2["dopamine"] - 0.5) < 1e-6, str(endo2["dopamine"]))

# ---------------- T4 other banned ----------------
print("\n[T4] other banned patterns")
cases = [
    ("subprocess", True, "import subprocess\ndef f():\n    subprocess.run(['ls'])\n\nif __name__=='__main__':\n    f()\n"),
    ("eval", True, "def f():\n    return eval('1+1')\n\nif __name__=='__main__':\n    print(f())\n"),
    ("exec", True, "def f():\n    exec('x=1')\n\nif __name__=='__main__':\n    f()\n"),
    ("dunder_import", True, "def f():\n    return __import__('os')\n\nif __name__=='__main__':\n    f()\n"),
    ("sys", True, "import sys\ndef f():\n    return sys.version\n\nif __name__=='__main__':\n    f()\n"),
    ("open", True, "def f():\n    return open('/etc/passwd').read()\n\nif __name__=='__main__':\n    f()\n"),
    ("json_math_safe", False, "import json, math\ndef f():\n    return json.dumps({'x': math.pi})\n\nif __name__=='__main__':\n    print(f())\n"),
]
for label, should_block, code in cases:
    a = ob.audit_source(code)
    check("T4 %s -> %s" % (label, "blocked" if should_block else "pass"),
          a.ok is not should_block, a.reason)

# ---------------- T5 lines / syntax ----------------
print("\n[T5] line limit and syntax")
long_code = "def f():\n" + "".join("    x%d = %d\n" % (i, i) for i in range(60)) + "    return 1\n"
check("T5.1 over 50 lines blocked", ob.audit_source(long_code).ok is False)
check("T5.2 syntax error blocked", ob.audit_source("def f(:\n    pass\n").ok is False)
check("T5.3 empty blocked", ob.audit_source("").ok is False)

# ---------------- T6 target_level prompt ----------------
print("\n[T6] prompt scaled by target_level")
p1 = ob.build_prompt({"content": "weather", "target_level": 1.04}, 1.04)
p0 = ob.build_prompt({"content": "weather", "target_level": 1.0}, 1.0)
check("T6.1 level 1.0 no boost", "1.04" not in p0, p0[:60])
check("T6.2 level 1.04 boosted", "1.04" in p1 and "+4%" in p1, p1[-90:])

# ---------------- T7 sandbox timeout ----------------
print("\n[T7] sandbox protection")
d7 = tempfile.mkdtemp(prefix="organ_sb_")
loop_code = "import time\ndef main():\n    while True:\n        time.sleep(0.01)\n\nif __name__=='__main__':\n    main()\n"
p7 = os.path.join(d7, "loop_organ.py")
open(p7, "w", encoding="utf-8").write(loop_code)
t0 = time.time()
ok7, info7 = ob.sandbox_test(p7, "main", timeout=3)
elapsed = time.time() - t0
check("T7.1 infinite loop blocked", ok7 is False, str(info7)[:60])
check("T7.2 terminated in time", elapsed < 8, "%.1fs" % elapsed)
check("T7.3 timeout message", ("timeout" in str(info7).lower()) or ("超时" in str(info7)),
      str(info7)[:60])

print("\n" + "=" * 70)
print(" RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" FAILED:", FAIL)
print("=" * 70)
sys.exit(0 if not FAIL else 1)
