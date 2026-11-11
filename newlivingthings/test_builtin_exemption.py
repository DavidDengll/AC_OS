# -*- coding: utf-8 -*-
"""test_builtin_exemption.py -- V9.1.1 内置豁免机制验收"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "organs"))

import organ_bootstrapper as ob

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


BUILTIN_SRC = (
    "# -*- coding: utf-8 -*-\n"
    "# BUILTIN  (预置内置器官)\n"
    "import json\n"
    "import urllib.request\n"
    "\n"
    "def main():\n"
    "    return 'ok'\n"
)

DYNAMIC_SRC = (
    "import json\n"
    "import urllib.request\n"
    "\n"
    "def main():\n"
    "    return 'ok'\n"
)

DYNAMIC_URLLIB_FROM = (
    "from urllib.request import urlopen\n"
    "\n"
    "def main():\n"
    "    return 'ok'\n"
)

NORMAL_SRC = (
    "import json, math\n"
    "\n"
    "def main():\n"
    "    return json.dumps({'x': math.pi})\n"
)

print("=" * 70)
print(" V9.1.1 builtin exemption acceptance")
print("=" * 70)

# ---------------- T1 白名单拆分 ----------------
print("\n[T1] whitelist split")
check("T1.1 urllib NOT in SAFE_IMPORTS", "urllib" not in ob.SAFE_IMPORTS,
      str(ob.SAFE_IMPORTS))
check("T1.2 urllib IS in PRIVILEGED_IMPORTS", "urllib" in ob.PRIVILEGED_IMPORTS)
check("T1.3 BUILTIN marker defined", ob.BUILTIN_MARKER == "# BUILTIN")
check("T1.4 json still safe", "json" in ob.SAFE_IMPORTS)

# ---------------- T2 标记识别 ----------------
print("\n[T2] builtin marker detection")
check("T2.1 marked source detected", ob.is_builtin_source(BUILTIN_SRC) is True)
check("T2.2 unmarked source not builtin", ob.is_builtin_source(DYNAMIC_SRC) is False)
check("T2.3 empty source not builtin", ob.is_builtin_source("") is False)
check("T2.4 marker only counts in head (first 5 lines)",
      ob.is_builtin_source("\n" * 10 + "# BUILTIN\nimport json\n") is False)

# ---------------- T3 内置器官放行 ----------------
print("\n[T3] builtin organ allowed to use urllib")
a1 = ob.audit_source(BUILTIN_SRC, builtin=True)
check("T3.1 builtin + urllib passes", a1.ok is True, a1.reason)
real = open(os.path.join(HERE, "organs", "organ_web_search.py"), encoding="utf-8").read()
a2 = ob.audit_source(real, builtin=True)
check("T3.2 real web organ passes as builtin", a2.ok is True, a2.reason)
check("T3.3 real web organ carries marker", ob.is_builtin_source(real) is True)

# ---------------- T4 动态器官拦截 ----------------
print("\n[T4] dynamic organ blocked from urllib")
d1 = ob.audit_source(DYNAMIC_SRC, builtin=False)
check("T4.1 dynamic + urllib blocked", d1.ok is False, d1.reason)
check("T4.2 reason mentions outbound ban",
      "禁止导入出网库" in d1.reason, d1.reason)
check("T4.3 reason suggests bridge/ctx",
      "api/exec" in d1.reason or "ctx" in d1.reason, d1.reason)

d2 = ob.audit_source(DYNAMIC_URLLIB_FROM, builtin=False)
check("T4.4 from urllib import also blocked", d2.ok is False, d2.reason)

# 默认参数必须是动态（最严格）
d3 = ob.audit_source(DYNAMIC_SRC)
check("T4.5 default (no arg) treats as dynamic", d3.ok is False, d3.reason)

# 伪造 builtin=True 但无标记 -> 失效，仍按动态拦截
d4 = ob.audit_source(DYNAMIC_SRC, builtin=True)
check("T4.6 forged builtin=True without marker still blocked",
      d4.ok is False, d4.reason)

# 真实内置器官按动态审核也须拦截（证明豁免只认来源）
d5 = ob.audit_source(real, builtin=False)
check("T4.7 real organ blocked when treated as dynamic", d5.ok is False, d5.reason)

# ---------------- T5 正常库不受影响 ----------------
print("\n[T5] normal imports unaffected")
n1 = ob.audit_source(NORMAL_SRC, builtin=False)
check("T5.1 json+math still allowed for dynamic", n1.ok is True, n1.reason)
n2 = ob.audit_source(NORMAL_SRC, builtin=True)
check("T5.2 json+math allowed for builtin", n2.ok is True, n2.reason)

# ---------------- T6 其它危险库仍拦截 ----------------
print("\n[T6] other dangerous libs still blocked")
cases = [
    ("os", "import os\ndef main():\n    return os.getcwd()\n"),
    ("subprocess", "import subprocess\ndef main():\n    return 1\n"),
    ("socket", "import socket\ndef main():\n    return 1\n"),
    ("requests", "import requests\ndef main():\n    return 1\n"),
]
for label, code in cases:
    r1 = ob.audit_source(code, builtin=False)
    r2 = ob.audit_source(code, builtin=True)
    check("T6 %s blocked (dynamic)" % label, r1.ok is False, r1.reason)
    check("T6 %s blocked (builtin too)" % label, r2.ok is False, r2.reason)

# ---------------- T7 自举流程强制动态 ----------------
print("\n[T7] bootstrap forces dynamic audit")
src = open(os.path.join(HERE, "organs", "organ_bootstrapper.py"),
           encoding="utf-8").read()
check("T7.1 bootstrap calls audit with builtin=False",
      "audit_source(code, builtin=False)" in src)
import ast as _ast
_tree = _ast.parse(src)
_boot = [n for n in _tree.body
         if isinstance(n, _ast.FunctionDef) and n.name == "bootstrap"][0]
_params = {a.arg for a in _boot.args.args} | {a.arg for a in _boot.args.kwonlyargs}
check("T7.2 bootstrap() exposes no builtin parameter (cannot be spoofed)",
      "builtin" not in _params, str(sorted(_params)))

print("\n" + "=" * 70)
print(" RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" FAILED:", FAIL)
print("=" * 70)
sys.exit(0 if not FAIL else 1)
