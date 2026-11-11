# -*- coding: utf-8 -*-
"""test_web_organ.py -- V9.1 内置联网器官验收（Mock 桥接，不联网）"""
import io
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "organs"))

TMP = tempfile.mkdtemp(prefix="web_")
os.environ["AC_DB_PATH"] = os.path.join(TMP, "soul.db")
os.environ["AC_DEAD_LOCK"] = os.path.join(TMP, "dead.lock")

import tool_caller
import obsession_pool as op
import organ_bootstrapper as ob
import main as M

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


class MockResponse:
    def __init__(self, payload):
        self._b = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    def read(self):
        return self._b
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def patch_urlopen(handler):
    """替换器官模块内的 urlopen。"""
    mod = tool_caller.DYNAMIC_ORGANS.get("organ_web_search", {}).get("_module")
    import organ_web_search as ws
    orig = ws.urllib.request.urlopen
    ws.urllib.request.urlopen = handler
    return lambda: setattr(ws.urllib.request, "urlopen", orig)


print("=" * 70)
print(" V9.1 built-in web organ acceptance (Mock bridge)")
print("=" * 70)

# ---------------- T1 启动挂载 ----------------
print("\n[T1] startup mounting into whitelist")
tool_caller.DYNAMIC_ORGANS.clear()
with redirect_stdout(io.StringIO()) as buf:
    loaded = tool_caller.load_builtin_organs()
check("T1.1 organ loaded at startup", "organ_web_search" in loaded, str(loaded))
check("T1.2 registered in DYNAMIC_ORGANS",
      "organ_web_search" in tool_caller.DYNAMIC_ORGANS)
check("T1.3 marked as builtin",
      tool_caller.DYNAMIC_ORGANS["organ_web_search"].get("builtin") is True)
check("T1.4 get_organ returns callable",
      callable(tool_caller.get_organ("organ_web_search")))
check("T1.5 idempotent reload", tool_caller.load_builtin_organs() == loaded)

# ---------------- T2 请求与截断 ----------------
print("\n[T2] request payload and truncation")
import organ_web_search as ws
captured = {}

def ok_handler(req, timeout=None):
    captured["url"] = req.full_url
    captured["data"] = json.loads(req.data.decode("utf-8"))
    captured["timeout"] = timeout
    return MockResponse({"ok": True, "result": "A" * 2000 + "TAIL"})

restore = patch_urlopen(ok_handler)
try:
    fn = tool_caller.get_organ("organ_web_search")
    out = fn("今天的新闻")
finally:
    restore()

check("T2.1 posts to bridge endpoint",
      captured.get("url") == "http://host.docker.internal:5555/api/exec",
      str(captured.get("url")))
check("T2.2 json body task = 搜索+query",
      captured.get("data", {}).get("task") == "搜索今天的新闻",
      str(captured.get("data")))
check("T2.3 timeout is 10s", captured.get("timeout") == 10, str(captured.get("timeout")))
check("T2.4 truncated to 500 chars", len(out) == 500, "len=%d" % len(out))
check("T2.5 tail dropped", "TAIL" not in out)

# ---------------- T3 失败处理 ----------------
print("\n[T3] failure handling")
def net_fail(req, timeout=None):
    raise TimeoutError("timed out")

restore = patch_urlopen(net_fail)
try:
    out_fail = tool_caller.get_organ("organ_web_search")("x")
finally:
    restore()
check("T3.1 returns 网络搜索失败 prefix",
      out_fail.startswith("网络搜索失败"), out_fail[:80])

def bad_ok(req, timeout=None):
    return MockResponse({"ok": False, "error": "bridge down"})

restore = patch_urlopen(bad_ok)
try:
    out_bad = tool_caller.get_organ("organ_web_search")("x")
finally:
    restore()
check("T3.2 bridge ok=False also fails", out_bad.startswith("网络搜索失败"),
      out_bad[:80])

def empty_ok(req, timeout=None):
    return MockResponse({"ok": True, "result": ""})

restore = patch_urlopen(empty_ok)
try:
    out_empty = tool_caller.get_organ("organ_web_search")("x")
finally:
    restore()
check("T3.3 empty result treated as failure",
      out_empty.startswith("网络搜索失败"), out_empty[:80])

# ---------------- T4 已知器官复用（不重复自举）----------------
print("\n[T4] known organ reuse, no re-bootstrap")
d = tempfile.mkdtemp(prefix="reuse_")
db = os.path.join(d, "soul.db")
pool = op.ObsessionPool(db, log=lambda m: None)
r = pool.add_or_reinforce("查一下今天的新闻")
c = sqlite3.connect(db)
c.execute("UPDATE gaps SET tension=0.95 WHERE id=?", (r["id"],))
c.commit()
c.close()
gap = pool.get(r["id"])

check("T4.1 match_known_organ hits web organ",
      ob.match_known_organ(gap) == ("organ_web_search", "search_web"),
      str(ob.match_known_organ(gap)))
check("T4.2 non-web gap does not match",
      ob.match_known_organ({"content": "修复数据库死锁"}) is None)

called = {"n": 0}
def fake_llm(messages):
    called["n"] += 1
    return "def main():\n    return 1\n"

logs = []
res = ob.bootstrap(gap, fake_llm, vitality=100, db_path=db, endo={"dopamine": 0.5},
                   organs_dir=os.path.join(d, "organs"),
                   manifest_db=os.path.join(d, "organs.db"), log=logs.append)
check("T4.3 bootstrap returns reuse stage", res["stage"] == "reuse", str(res["stage"]))
check("T4.4 LLM never called (no wheel reinvention)", called["n"] == 0,
      "calls=%d" % called["n"])
check("T4.5 organ name reported", res.get("organ") == "organ_web_search")
check("T4.6 prints reuse log",
      any("跳过自举" in m for m in logs), str(logs[:1]))

# ---------------- T5 main loop: failure penalty ----------------
print("\n[T5] main loop: failure generates obsession + cortisol")
class _S:
    def __init__(self, v):
        self.vitality = v
        self.round = 100
    def spend(self, amount, reason=""):
        self.vitality = max(0, self.vitality - int(amount))
        return self.vitality

d2 = tempfile.mkdtemp(prefix="main_")
db2 = os.path.join(d2, "soul.db")
pool2 = op.ObsessionPool(db2, log=lambda m: None)
r2 = pool2.add_or_reinforce("查一下明天的天气")
c = sqlite3.connect(db2)
c.execute("UPDATE gaps SET tension=0.95 WHERE id=?", (r2["id"],))
c.commit()
c.close()

life = M.EntropyLife.__new__(M.EntropyLife)
life.obsessions = pool2
life.endo = {"dopamine": 0.4, "cortisol": 0.5}
life.soul = _S(100)

gap2 = pool2.get(r2["id"])
before_count = pool2.count()
restore = patch_urlopen(net_fail)
try:
    with redirect_stdout(io.StringIO()) as buf5:
        res5 = life._pursue_via_web_organ(gap2, tool_caller.get_organ("organ_web_search"))
finally:
    restore()
out5 = buf5.getvalue()
check("T5.1 pursuit returns failure", res5.get("ok") is False, str(res5.get("stage")))
check("T5.2 generated new obsession", pool2.count() > before_count,
      "%d -> %d" % (before_count, pool2.count()))
news = [g for g in pool2.open_gaps() if "网络信息获取失败" in str(g["content"])]
check("T5.3 high-tension obsession created", bool(news) and news[0]["tension"] >= 0.9,
      str(news[0]["tension"]) if news else "")
check("T5.4 cortisol raised 0.5 -> 0.65", abs(life.endo["cortisol"] - 0.65) < 1e-6,
      str(life.endo["cortisol"]))
check("T5.5 not silently swallowed",
      "无法获取" in out5 or "网络搜索失败" in out5, out5[:100])

# 成功路径
d3 = tempfile.mkdtemp(prefix="ok_")
db3 = os.path.join(d3, "soul.db")
pool3 = op.ObsessionPool(db3, log=lambda m: None)
r3 = pool3.add_or_reinforce("查一下今天的新闻")
life3 = M.EntropyLife.__new__(M.EntropyLife)
life3.obsessions = pool3
life3.endo = {"dopamine": 0.4, "cortisol": 0.6}
life3.soul = _S(100)
restore = patch_urlopen(ok_handler)
try:
    with redirect_stdout(io.StringIO()):
        res6 = life3._pursue_via_web_organ(pool3.get(r3["id"]),
                                           tool_caller.get_organ("organ_web_search"))
finally:
    restore()
check("T5.6 success resolves obsession",
      pool3.get(r3["id"])["status"] == "resolved",
      pool3.get(r3["id"])["status"])
check("T5.7 success gives dopamine reward",
      abs(life3.endo["dopamine"] - 0.7) < 1e-6, str(life3.endo["dopamine"]))

# ---------------- T6 安全规范 ----------------
print("\n[T6] security compliance")
src = open(os.path.join(HERE, "organs", "organ_web_search.py"), encoding="utf-8").read()
audit = ob.audit_source(src)
check("T6.1 organ passes L0 audit", audit.ok is True, audit.reason)
check("T6.2 <= 50 lines", len([l for l in src.splitlines() if l.strip()]) <= 50)
check("T6.3 no requests library", "requests" not in src)
check("T6.4 no direct external URL", "http://" not in src.replace(
    "http://host.docker.internal:5555/api/exec", ""))
check("T6.5 uses bridge endpoint", "host.docker.internal:5555/api/exec" in src)
check("T6.6 no banned words in body",
      not any(w in src for w in ("import os", "import sys", "subprocess")))

print("\n" + "=" * 70)
print(" RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" FAILED:", FAIL)
print("=" * 70)
sys.exit(0 if not FAIL else 1)
