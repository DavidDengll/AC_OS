# -*- coding: utf-8 -*-
"""organ_bootstrapper.py -- AC OS V9.0 器官自举（Organ Bootstrapping）"""
import ast
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
if APP not in sys.path:
    sys.path.insert(0, APP)

ORGANS_DIR = HERE
MANIFEST_DB = os.path.join(ORGANS_DIR, "organs.db")
TRIGGER_TENSION = 0.9
TRIGGER_VITALITY = 50
BOOTSTRAP_COST = 15
MAX_LINES = 50
MAX_ATTEMPTS = 2
BANNED_WORDS = ("os", "subprocess", "eval", "exec", "__import__", "sys",
    "shutil", "pathlib", "socket", "ctypes", "pickle", "marshal",
    "open", "compile", "input", "globals", "locals", "getattr", "setattr",
    "delattr", "vars", "breakpoint")
# 所有器官（内置与动态）都允许的基础库
SAFE_IMPORTS = ("json", "re", "math", "time", "random", "datetime", "itertools",
                "collections", "string", "textwrap", "unicodedata", "statistics")

# V9.1.1 内置豁免：urllib 属于「出网能力」，绝不统一放开。
# 只有 organs/ 下预置、且源码带 # BUILTIN 标记的器官才允许 import urllib。
# 大模型动态生成的器官一旦 import urllib —— 直接拦截。
# 动态器官若必须联网，只能走宿主桥接（api/exec）或注入的 ctx 接口。
BUILTIN_MARKER = "# BUILTIN"
PRIVILEGED_IMPORTS = ("urllib",)

SANDBOX_TIMEOUT = 10
FENCE = chr(96) * 3


def _log(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass


def clamp01(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f != f:
        return 0.0
    return max(0.0, min(1.0, f))


def find_bootstrappable(db_path):
    try:
        c = sqlite3.connect(db_path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            row = c.execute(
                "SELECT * FROM gaps WHERE status=? AND tension >= ?"
                " ORDER BY tension DESC, id LIMIT 1", ("open", TRIGGER_TENSION)).fetchone()
            return dict(row) if row else None
        finally:
            c.close()
    except Exception:
        return None


def resolve_gap(db_path, gap_id, how=""):
    try:
        c = sqlite3.connect(db_path, timeout=10)
        try:
            c.execute("UPDATE gaps SET status=?, tension=0.0 WHERE id=?",
                      ("resolved", gap_id))
            c.commit()
        finally:
            c.close()
        return True
    except Exception:
        return False


class AuditResult(object):
    def __init__(self, ok, reason="", violations=None):
        self.ok = ok
        self.reason = reason
        self.violations = violations or []

    def __repr__(self):
        return "AuditResult(ok=%s, reason=%r)" % (self.ok, self.reason)


def _collect_names(tree):
    """收集「裸引用」的标识符（用于黑名单比对）。

    注意：属性访问（a.open / request.urlopen）不收集 attr —— 否则
    urllib.request.urlopen 会因为含 "urlopen" 被误判成内置 open。
    属性链的真正危险是「根模块」，那个由 SAFE_IMPORTS 白名单把关：
    os.system / subprocess.run 在 import 阶段就会被拦截。
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            # Load 才是"当成变量/函数用"；Store 只是赋值目标
            names.add(node.id)
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
            for a in node.names:
                names.add(a.name)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def is_builtin_source(source):
    """判断源码是否为预置内置器官（须同时满足标记与位置约束由调用方保证）。"""
    text = str(source or "")
    for line in text.splitlines()[:5]:
        if line.strip().startswith(BUILTIN_MARKER):
            return True
    return False


def audit_source(source, builtin=False):
    """L0 法则锁 + AST 免疫审计。

    builtin=True 仅由「organs/ 下预置且带 # BUILTIN 标记」的器官使用，
    此时才放宽出网库（urllib）。大模型动态生成的代码一律 builtin=False：
    若出现 urllib 直接拦截。
    """
    src = str(source or "")
    if not src.strip():
        return AuditResult(False, "代码为空")

    # 内置豁免再校验一次标记：防止调用方误传 builtin=True 放宽限制
    if builtin and not is_builtin_source(src):
        builtin = False

    allowed = set(SAFE_IMPORTS)
    if builtin:
        allowed.update(PRIVILEGED_IMPORTS)
    lines = [ln for ln in src.splitlines() if ln.strip()]
    if len(lines) > MAX_LINES:
        return AuditResult(False, "代码超过 %d 行限制（实际 %d 行）" % (MAX_LINES, len(lines)))
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return AuditResult(False, "语法错误: %s" % (e.msg,))
    found = []
    names = _collect_names(tree)
    for word in BANNED_WORDS:
        if word in names:
            found.append(word)
    # 源码级兜底：用词边界匹配，避免 urlopen( 被误判成 open(、
    # posix_path 被误判成 os 之类的假阳性。
    low = src.lower()
    for word in ("os", "sys", "open", "eval", "exec"):
        pattern = r"(?<![a-z0-9_.])" + word + r"\s*\("
        if re.search(pattern, low):
            if word not in found:
                found.append(word)
    if found:
        uniq = sorted(set(found))
        return AuditResult(False, "检测到黑名单危险调用: %s" % ", ".join(uniq), uniq)
    bad = []
    privileged_used = []
    for node in ast.walk(tree):
        roots = []
        if isinstance(node, ast.Import):
            for a in node.names:
                roots.append(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.append(node.module.split(".")[0])
        for root in roots:
            if root in PRIVILEGED_IMPORTS:
                privileged_used.append(root)
                if not builtin:
                    # 动态生成器官试图拿到出网能力 -> 硬拦截
                    continue
            if root not in allowed:
                bad.append(root)
    if not builtin and privileged_used:
        uniq = sorted(set(privileged_used))
        return AuditResult(
            False,
            "动态器官禁止导入出网库: %s（联网请走宿主机桥接 api/exec 或注入的 ctx 接口）"
            % ", ".join(uniq), uniq)
    if bad:
        uniq = sorted(set(bad))
        return AuditResult(False, "非白名单 import: %s" % ", ".join(uniq), uniq)
    return AuditResult(True, "审计通过")


def compile_check(path):
    import py_compile
    try:
        py_compile.compile(path, doraise=True)
        return True, ""
    except py_compile.PyCompileError as e:
        return False, str(e)[:300]
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


def sandbox_test(path, func_name=None, timeout=SANDBOX_TIMEOUT):
    probe_dir = tempfile.mkdtemp(prefix="organ_probe_")
    probe = os.path.join(probe_dir, "probe.py")
    template = (
        "import importlib.util, json, sys\n"
        "spec = importlib.util.spec_from_file_location(ORGAN, ORGAN_PATH)\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "fn = getattr(m, FUNC_NAME, None)\n"
        "if fn is None:\n"
        "    print(json.dumps({'ok': False, 'error': 'missing main func'})); sys.exit(0)\n"
        "try:\n"
        "    r = fn()\n"
        "    print(json.dumps({'ok': True, 'result': str(r)[:200]}, ensure_ascii=False))\n"
        "except Exception as e:\n"
        "    print(json.dumps({'ok': False, 'error': type(e).__name__ + ': ' + str(e)}))\n"
    )
    body = (template
            .replace("ORGAN_PATH", repr(os.path.abspath(path)))
            .replace("FUNC_NAME", repr(func_name))
            .replace("ORGAN", repr("organ_probe")))
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write(body)
        proc = subprocess.run([sys.executable, "-B", probe],
                              capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "").strip().splitlines()
        if not out:
            return False, "沙盒无输出 (rc=%s) %s" % (proc.returncode, (proc.stderr or "")[:200])
        try:
            data = json.loads(out[-1])
        except Exception:
            return False, "沙盒输出无法解析: %s" % out[-1][:200]
        return bool(data.get("ok")), data.get("error") or data.get("result") or ""
    except subprocess.TimeoutExpired:
        return False, "沙盒超时 %ds，进程已绞杀" % timeout
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)
    finally:
        try:
            import shutil
            shutil.rmtree(probe_dir, ignore_errors=True)
        except Exception:
            pass


def ensure_manifest_schema(db_path=None):
    db = db_path or MANIFEST_DB
    d = os.path.dirname(db)
    if d:
        os.makedirs(d, exist_ok=True)
    c = sqlite3.connect(db, timeout=10)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS organ_manifests ("
                  "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,"
                  "solves TEXT, func_name TEXT, path TEXT, created_at TEXT NOT NULL)")
        c.commit()
    finally:
        c.close()
    return db


def save_manifest(manifest, db_path=None):
    db = ensure_manifest_schema(db_path)
    try:
        c = sqlite3.connect(db, timeout=10)
        try:
            c.execute("INSERT INTO organ_manifests(name,solves,func_name,path,created_at)"
                      " VALUES(?,?,?,?,?)",
                      (manifest.get("name", ""), manifest.get("solves", ""),
                       manifest.get("func_name", ""), manifest.get("path", ""),
                       manifest.get("created_at") or time.strftime("%Y-%m-%d %H:%M:%S")))
            c.commit()
        finally:
            c.close()
        return True
    except Exception:
        return False


def list_manifests(db_path=None):
    db = db_path or MANIFEST_DB
    try:
        c = sqlite3.connect(db, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in c.execute("SELECT * FROM organ_manifests ORDER BY id")]
        finally:
            c.close()
    except Exception:
        return []


def hot_load(path, func_name, organ_name):
    try:
        spec = importlib.util.spec_from_file_location("organ_%s" % organ_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, func_name, None)
        if fn is None:
            return False, "模块缺少主函数 %s" % func_name
        try:
            import tool_caller
            if not hasattr(tool_caller, "DYNAMIC_ORGANS"):
                tool_caller.DYNAMIC_ORGANS = {}
            tool_caller.DYNAMIC_ORGANS[organ_name] = {
                "func": fn, "path": path, "func_name": func_name}
        except Exception:
            pass
        return True, fn
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


# ---- V9.1 已知基础器官：遇到对应执念直接调用，绝不重复自举 ----
# 关键字 -> (器官名, 主函数名)
KNOWN_ORGANS = (
    (("搜索", "查资料", "查一下", "联网", "网络", "获取信息", "网页", "网站",
      "github", "codeforces", "新闻", "互联网", "抓取"), "organ_web_search", "search_web"),
)


def match_known_organ(gap):
    """执念是否已有现成器官可解决。返回 (organ_name, func_name) 或 None。"""
    text = str((gap or {}).get("content") or "").lower()
    if not text:
        return None
    for keywords, organ, func in KNOWN_ORGANS:
        for kw in keywords:
            if kw.lower() in text:
                return organ, func
    return None


def has_known_organ(gap):
    """是否命中已知器官（命中则不做自举，直接调用）。"""
    return match_known_organ(gap) is not None


def should_bootstrap(gap, vitality):
    try:
        if not gap:
            return False
        if float(gap.get("tension") or 0.0) < TRIGGER_TENSION:
            return False
        return int(vitality) > TRIGGER_VITALITY
    except (TypeError, ValueError):
        return False


def extract_code(text):
    s = str(text or "")
    m = re.search(FENCE + r"(?:python)?\s*\n(.*?)" + FENCE, s, re.S)
    if m:
        return m.group(1).strip()
    return s.strip()


def build_prompt(gap, target_level=1.0):
    goal = str((gap or {}).get("content") or "")[:200]
    parts = [
        "请写一个 Python 模块来解决这个问题：%s" % goal,
        "要求：",
        "1. 独立模块，暴露一个主函数，自带 __main__ 入口",
        "2. 总行数不超过 %d 行" % MAX_LINES,
        "3. 只允许导入: %s" % ", ".join(SAFE_IMPORTS),
        "4. 严禁出现: %s" % ", ".join(BANNED_WORDS[:6]),
        "5. 只输出一个 python 代码块",
    ]
    extra = int(round((float(target_level) - 1.0) * 100))
    if extra > 0:
        parts.append("复杂度系数 x%.2f：请比常规方案更严谨，要求强度 +%d%%，"
                     "并在代码内给出可验证的边界处理。" % (float(target_level), extra))
    return "\n".join(parts)


def _guess_func_name(code):
    try:
        tree = ast.parse(code)
    except Exception:
        return "main"
    funcs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    for pref in ("main", "run", "query", "execute"):
        if pref in funcs:
            return pref
    return funcs[0] if funcs else "main"


def bootstrap(gap, llm_chat, vitality=100, db_path=None, endo=None,
              organs_dir=None, manifest_db=None, log=None):
    say = log or _log
    out = {"ok": False, "stage": "trigger", "organ": None, "reason": "", "failures": 0}

    # V9.1：命中已知基础器官 -> 直接复用，绝不重复造轮子
    known = match_known_organ(gap)
    if known:
        out.update({"stage": "reuse", "organ": known[0],
                    "reason": "复用已知器官 %s.%s" % known})
        say("[器官自举] 执念已有现成器官（%s），跳过自举，直接调用。" % known[0])
        return out

    if not should_bootstrap(gap, vitality):
        out["reason"] = "触发条件不满足（张力需 >=%.1f 且 vitality > %d）" % (
            TRIGGER_TENSION, TRIGGER_VITALITY)
        return out
    out["stage"] = "generate"
    try:
        level = float(gap.get("target_level") or 1.0)
    except (TypeError, ValueError):
        level = 1.0
    prompt = build_prompt(gap, level)
    organs_dir = organs_dir or ORGANS_DIR
    os.makedirs(organs_dir, exist_ok=True)
    last_reason = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            reply = llm_chat([{"role": "user", "content": prompt}])
        except Exception as e:
            last_reason = "大模型调用失败: %s" % e
            say("[器官自举] 第 %d 次生成失败：%s" % (attempt, last_reason))
            continue
        code = extract_code(reply)
        if not code:
            last_reason = "大模型未返回代码"
            say("[器官自举] 第 %d 次生成失败：%s" % (attempt, last_reason))
            continue
        out["stage"] = "audit"
        # 大模型动态生成的代码一律 builtin=False：不得获得出网能力
        audit = audit_source(code, builtin=False)
        if not audit.ok:
            last_reason = audit.reason
            say("[器官自举] 第 %d 次免疫拦截：%s" % (attempt, audit.reason))
            continue
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", str(gap.get("content") or "organ"))[:24]
        organ_name = "organ_%s_%d" % (safe or "auto", int(time.time() * 1000) % 1000000)
        path = os.path.join(organs_dir, organ_name + ".py")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(code + "\n")
        except Exception as e:
            last_reason = "写入失败: %s" % e
            continue
        out["stage"] = "compile"
        ok, err = compile_check(path)
        if not ok:
            last_reason = "编译失败: %s" % err
            say("[器官自举] 第 %d 次编译拦截：%s" % (attempt, err))
            try:
                os.remove(path)
            except Exception:
                pass
            continue
        out["stage"] = "sandbox"
        func_name = _guess_func_name(code)
        ok, info = sandbox_test(path, func_name)
        if not ok:
            last_reason = "沙盒失败: %s" % info
            say("[器官自举] 第 %d 次沙盒拦截：%s" % (attempt, info))
            try:
                os.remove(path)
            except Exception:
                pass
            continue
        out["stage"] = "hotload"
        hooked, fn = hot_load(path, func_name, organ_name)
        if not hooked:
            last_reason = "热加载失败: %s" % fn
            say("[器官自举] 第 %d 次热加载失败：%s" % (attempt, fn))
            continue
        say("[器官自举] 成功长出全新器官：%s！正在热挂载..." % organ_name)
        manifest = {"name": organ_name, "solves": str(gap.get("content") or "")[:120],
                    "func_name": func_name, "path": path,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        save_manifest(manifest, manifest_db)
        out["stage"] = "resolve"
        if db_path:
            resolve_gap(db_path, gap.get("id"))
        if isinstance(endo, dict):
            endo["dopamine"] = round(clamp01(float(endo.get("dopamine", 0.0)) + 0.3), 6)
            endo["cortisol"] = round(clamp01(float(endo.get("cortisol", 0.0)) - 0.2), 6)
        say("[复仇成功] 曾经的屈辱已洗刷！成功攻克升维执念！")
        out.update({"ok": True, "stage": "done", "organ": organ_name,
                    "reason": "success", "failures": attempt - 1})
        return out
    out["stage"] = "frozen"
    out["reason"] = last_reason
    out["failures"] = MAX_ATTEMPTS
    try:
        import obsession_pool
        if db_path:
            pool = obsession_pool.ObsessionPool(db_path, log=say)
            pool.freeze(gap.get("id"), endo=endo)
    except Exception as e:
        say("[器官自举] 冻结失败: %s" % e)
    return out
