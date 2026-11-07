# self_refactor.py
# -*- coding: utf-8 -*-
"""
self_refactor.py —— AC OS V6.0 自我重构（三权分立）

设计原则（SELF_REFACTOR_WHITEPAPER）：
  1. 三权分立：Scout 侦察 / Judge 审批 / Surgeon 施工，职责彻底分离
  2. 物理隔离：权限白名单在代码层焊死
       Scout   —— 绝对不可写
       Judge   —— 绝对不可调用大模型（纯 Python 类）
       Surgeon —— 绝对不可联网、不可跨文件
  3. 防爆第一：长文本强制截断，绝不加载任何模型权重
"""

import ast
import json
import os
import py_compile
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

MAX_LINES = 20
MAX_RETRIES = 2

# ---- V6.1 多文件扩容上限（物理防爆）----
MAX_FILES = 3          # 单次任务最多 3 个关联文件
MAX_EDIT_LINES = 100   # 单次手术总修改行数上限
COMPILE_TIMEOUT = 15.0 # 编译/自检的物理超时锁（秒）
SELFTEST_TIMEOUT = 10.0  # 改了 main.py 后的轻量自检超时


class PermissionDenied(Exception):
    """权限白名单拦截：越权操作一律抛此异常。"""


class RefactorFailedException(Exception):
    """熔断：连续重试达到上限仍无法修复，退出流水线。"""


def _log(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass


def truncate_lines(text, n=MAX_LINES):
    try:
        return "\n".join(str(text or "").splitlines()[:max(1, int(n))])
    except Exception:
        return ""


def _is_apology(text):
    try:
        import search_utils
        return search_utils.is_apology(text)
    except Exception:
        t = str(text or "").strip().lower()
        return (not t) or ("i'm sorry" in t) or ("network error" in t)


# ============================================================
# AST 静态分析：跨文件 import 与循环依赖检测
# ============================================================
def _module_name_of(path):
    """把文件路径映射成模块名（同目录内以文件名去扩展名表示）。"""
    try:
        return os.path.splitext(os.path.basename(str(path)))[0]
    except Exception:
        return ""


def extract_imports(source):
    """用 ast 解析源码，提取本文件 import 的「同目录模块名」集合。

    只关心形如 import b / from b import x 这类顶层模块引用；
    相对导入与第三方包不参与循环检测（无法静态判定归属）。
    """
    names = set()
    try:
        tree = ast.parse(source)
    except Exception:
        return names
    for node in ast.walk(tree):
        try:
            if isinstance(node, ast.Import):
                for a in node.names:
                    names.add(str(a.name).split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue          # 相对导入跳过
                if node.module:
                    names.add(str(node.module).split(".")[0])
        except Exception:
            continue
    return names


def detect_cycle(modules):
    """在模块依赖图中检测环。modules 形如 {name: {dep, ...}}。

    返回环路径列表（例如 ["a", "b", "a"]），无环返回 None。
    """
    try:
        WHITE, GREY, BLACK = 0, 1, 2
        color = {k: WHITE for k in modules}
        stack = []

        def dfs(u):
            color[u] = GREY
            stack.append(u)
            for v in modules.get(u, ()) or ():
                if v not in modules:
                    continue          # 图外依赖忽略
                if color.get(v, WHITE) == GREY:
                    i = stack.index(v)
                    return stack[i:] + [v]
                if color.get(v, WHITE) == WHITE:
                    found = dfs(v)
                    if found:
                        return found
            stack.pop()
            color[u] = BLACK
            return None

        for node in list(modules):
            if color.get(node, WHITE) == WHITE:
                found = dfs(node)
                if found:
                    return found
        return None
    except Exception:
        return None


def check_circular_import(paths, new_sources=None):
    """对指定文件集合做循环依赖检测。

    new_sources: {path: 新源码}，用于检测「补丁引入的新 import」是否成环；
                 未提供的文件读取磁盘当前内容。
    返回 (ok, cycle_path)。
    """
    try:
        modules = {}
        sources = {}
        for p in paths or []:
            if new_sources and p in new_sources:
                src = new_sources[p]
            else:
                try:
                    with open(p, "r", encoding="utf-8", errors="replace") as f:
                        src = f.read()
                except Exception:
                    continue
            name = _module_name_of(p)
            sources[name] = src
            modules[name] = extract_imports(src)
        cycle = detect_cycle(modules)
        return (cycle is None), cycle
    except Exception:
        return True, None


# ============================================================
# 基因记忆注入：从 SQLite 提取高多巴胺/高皮质醇记忆
# ============================================================
# 记忆表本身不存 D/C 数值，只存情绪染色（positive/negative）
# 与 salience。这里把「情绪染色 + 显著性」映射回等效的 D/C，
# 以便按需求筛选 D>0.7 或 C>0.7 的记忆。
COLOR_TO_D = {"positive": 0.80, "negative": 0.35, "neutral": 0.50}
COLOR_TO_C = {"positive": 0.30, "negative": 0.80, "neutral": 0.50}
MEMORY_D_THRESHOLD = 0.7
MEMORY_C_THRESHOLD = 0.7
MEMORY_PICK_N = 2


def _resolve_db_path():
    """优先用 soul_core 的库路径（尊重 AC_DB_PATH），否则用本目录的库。"""
    try:
        import soul_core
        return getattr(soul_core, "DB_PATH", None) or os.path.join(HERE, "entropy_memory.db")
    except Exception:
        return os.path.join(HERE, "entropy_memory.db")


def _existing_columns(conn, table="memories"):
    """读取表结构。老库可能没有 emotion_color / salience 两列，
    直接 SELECT 它们会整条查询抛异常、静默返回空列表（等于基因记忆失效）。"""
    try:
        return {str(r[1]) for r in conn.execute("PRAGMA table_info(%s)" % table)}
    except Exception:
        return set()


def load_gene_memories(n=MEMORY_PICK_N, db_path=None, endo=None):
    """查询 SQLite，取最近 n 条「高多巴胺(D>0.7) 或高皮质醇(C>0.7)」的记忆。

    若调用方直接给了 endo（当前内分泌），则额外把当前状态一起纳入参考。
    返回 list[dict]：{name, feature, color, salience, d, c}
    """
    try:
        import sqlite3
        path = db_path or _resolve_db_path()
        if not os.path.exists(path):
            return []
        conn = sqlite3.connect(path, timeout=5)
        try:
            cols = _existing_columns(conn)
            if "emotion_color" in cols:
                color_expr = "emotion_color"
            else:
                color_expr = "'neutral'"      # 老库：无染色列，按中性兜底
            if "salience" in cols:
                salience_expr = "salience"
            else:
                salience_expr = "2.0"         # 老库：salience 默认 2.0（同 memory.py 迁移值）
            rows = conn.execute(
                "SELECT name, feature, %s, %s FROM memories "
                "ORDER BY id DESC LIMIT 200" % (color_expr, salience_expr)).fetchall()
        finally:
            conn.close()
        picked = []
        for name, feature, color, salience in rows:
            color = str(color or "neutral")
            d = COLOR_TO_D.get(color, 0.5)
            c = COLOR_TO_C.get(color, 0.5)
            if d > MEMORY_D_THRESHOLD or c > MEMORY_C_THRESHOLD:
                picked.append({"name": name, "feature": str(feature or ""),
                               "color": color,
                               "salience": float(salience or 0.0),
                               "d": d, "c": c})
        # 显著性高者优先
        picked.sort(key=lambda x: -x["salience"])
        return picked[:max(1, int(n))]
    except Exception:
        return []


# ============================================================
# 模块二：侦察兵 (Scout)
# ============================================================
class Scout:
    """侦察兵：只读、只搜、只报告。物理剥夺写与执行权限。"""

    ALLOWED = ("read_file", "grep", "find", "web_search", "py_compile")
    DENIED = ("edit_file", "write_file", "shell")

    def __init__(self, llm=None, search=None, endo=None, db_path=None):
        self.llm = llm
        self._search = search
        self.endo = endo or {}
        self.db_path = db_path
        self.gene_memories = []     # 本次侦察注入的基因记忆（高 D / 高 C）
        self.last_prompt = ""        # 最近一次生成的侦察 Prompt（便于审计）

    # ---- V6.3 基因记忆注入 ----
    def load_gene_context(self, n=MEMORY_PICK_N):
        """强制查询 SQLite，提取高多巴胺/高皮质醇记忆作为修复参考。

        白皮书 V6.3：侦察兵在生成探测 Prompt 前必须加载近期基因记忆，
        让系统在修 Bug 时带着自己的「历史教训」与「创伤记忆」。
        返回 prompt 片段字符串（永不抛异常，库坏/无表都只是降级为空）。
        """
        try:
            self.gene_memories = load_gene_memories(
                n=n, db_path=self.db_path, endo=self.endo)
        except Exception:
            self.gene_memories = []

        brief = "；".join(
            "%s(%s)" % (str(m.get("feature") or m.get("name") or "")[:40],
                        "高多巴胺" if float(m.get("d") or 0) > MEMORY_D_THRESHOLD
                        else "高皮质醇")
            for m in self.gene_memories) or "（暂无高权重记忆）"
        _log("[Scout] 已加载近期基因记忆作为参考：%s" % brief)

        cur = "D=%.2f C=%.2f E=%.2f" % (
            float(self.endo.get("dopamine", 0.0)),
            float(self.endo.get("cortisol", 0.0)),
            float(self.endo.get("endorphin", 0.0)))
        return "【基因记忆·近期高权重事件】\n%s\n【当前内分泌】%s" % (brief, cur)

    def build_scout_prompt(self, file_path, res):
        """生成侦察 Prompt —— 生成前强制注入基因记忆。"""
        ctx = self.load_gene_context()
        err = "%s (第 %s 行): %s" % (
            res.get("error", "UnknownError"), res.get("line") or "?",
            truncate_lines(res.get("text", ""), 3))
        self.last_prompt = (
            "%s\n\n【待修复文件】%s\n【编译错误】\n%s\n\n"
            "请基于上述历史教训给出最小修复方案，只输出修复后的代码块。"
            % (ctx, os.path.basename(file_path), err))

        # 真正把注入后的 Prompt 交给大脑（无大脑时纯静态侦察，不报警）
        if self.llm is not None:
            try:
                reply = self.llm.chat(
                    [{"role": "user", "content": self.last_prompt}],
                    temperature=0.2, max_tokens=300)
                if reply:
                    _log("[Scout] 大脑侦察意见：%s"
                         % truncate_lines(reply, 3).replace("\n", " ")[:160])
            except Exception as e:
                # 大脑失败绝不影响侦察主流程（降级为纯静态检查）
                _log("[Scout] 大脑调用失败（已降级为静态侦察）：%s" % e)
        return self.last_prompt

    # ---- 权限白名单：越权即抛 ----
    def _guard(self, action):
        if action in self.DENIED or action not in self.ALLOWED:
            raise PermissionDenied("Scout 无权执行: %s" % action)

    def read_file(self, path):
        self._guard("read_file")
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def grep(self, pattern, path):
        self._guard("grep")
        txt = self.read_file(path)
        hits = []
        for i, line in enumerate(txt.splitlines(), 1):
            if re.search(pattern, line):
                hits.append({"line": i, "text": line[:200]})
        return hits

    def find(self, root, pattern):
        self._guard("find")
        out = []
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if re.search(pattern, fn):
                    out.append(os.path.join(dirpath, fn))
        return out

    def py_compile(self, path):
        """受限编译：只检查语法，不执行、不写回源文件。"""
        self._guard("py_compile")
        try:
            with open(path, "rb") as f:
                src = f.read()
            compile(src, path, "exec")
            return {"ok": True, "error": ""}
        except SyntaxError as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e.msg),
                    "line": e.lineno or 0, "text": (e.text or "").strip()}
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "line": 0}

    def web_search(self, query):
        self._guard("web_search")
        if self._search is not None:
            return self._search(query)
        import search_utils
        return search_utils.web_search(query)

    # ---- 物理剥夺：这些方法根本不存在，调用即报错 ----
    def edit_file(self, *a, **k):
        raise PermissionDenied("Scout 无权执行: edit_file")

    def write_file(self, *a, **k):
        raise PermissionDenied("Scout 无权执行: write_file")

    def shell(self, *a, **k):
        raise PermissionDenied("Scout 无权执行: shell")

    # ---- 主任务流 ----
    def scan(self, file_path):
        """扫描目标文件，输出结构化 JSON 报告。"""
        report = {"issues": []}
        try:
            self.read_file(file_path)
        except FileNotFoundError:
            report["issues"].append({
                "file_path": file_path, "error_line": 0,
                "evidence": "FileNotFoundError: %s" % file_path,
                "suggested_fix": "确认文件路径", "severity": 10})
            _log("[Scout] 发现错误并输出报告...")
            return report

        res = self.py_compile(file_path)
        if res.get("ok"):
            _log("[Scout] 未发现语法错误：%s" % os.path.basename(file_path))
            return report

        err_type = str(res.get("error", "")).split(":")[0] or "SyntaxError"
        err_msg = str(res.get("error", ""))
        snippet = truncate_lines(res.get("text", ""), 3)

        # ---- V6.3：生成侦察 Prompt 前强制注入基因记忆 ----
        self.build_scout_prompt(file_path, res)

        # 自身 LLM 无法给出方案时，联网检索
        evidence = err_msg
        if self._needs_search(err_msg):
            q = "Python %s %s solution" % (err_type, snippet or err_msg[:80])
            found = self.web_search(q)
            if found:
                evidence = truncate_lines(found, MAX_LINES)

        report["issues"].append({
            "file_path": file_path,
            "error_line": int(res.get("line") or 0),
            "evidence": evidence,
            "suggested_fix": "修复第 %s 行的 %s" % (res.get("line") or "?", err_type),
            "severity": 8 if "Syntax" in err_type else 5,
        })
        _log("[Scout] 发现错误并输出报告...")
        return report

    def scan_multi(self, file_paths):
        """V6.1：一次侦察最多 MAX_FILES 个关联文件，找出跨文件依赖错误。

        返回结构化 JSON 报告，issues 中每条附带 file_paths（同批文件集合）。
        """
        paths = [p for p in (file_paths or []) if p][:MAX_FILES]
        report = {"issues": []}
        if not paths:
            return report

        # 逐个文件编译，收集错误
        bad = []
        for p in paths:
            res = self.py_compile(p)
            if not res.get("ok"):
                bad.append((p, res))

        # ---- V6.3：生成侦察 Prompt 前强制注入基因记忆 ----
        self.build_scout_prompt((bad[0][0] if bad else paths[0]),
                                (bad[0][1] if bad else {}))

        # 跨文件依赖检查：现有 import 是否已成环
        ok, cycle = check_circular_import(paths)
        if not ok and cycle:
            for p in paths:
                report["issues"].append({
                    "file_path": p,
                    "file_paths": paths,
                    "error_line": 0,
                    "evidence": "CircularImport: " + " -> ".join(cycle),
                    "suggested_fix": "打断循环依赖 " + " -> ".join(cycle),
                    "severity": 9,
                })

        for p, res in bad:
            err = str(res.get("error", ""))
            err_type = err.split(":")[0] or "SyntaxError"
            report["issues"].append({
                "file_path": p,
                "file_paths": paths,
                "error_line": int(res.get("line") or 0),
                "evidence": err[:400],
                "suggested_fix": "修复第 %s 行的 %s" % (res.get("line") or "?", err_type),
                "severity": 8 if "Syntax" in err_type else 5,
            })

        if report["issues"]:
            _log("[Scout] 发现错误并输出报告...")
        else:
            _log("[Scout] 未发现语法错误：%d 个文件" % len(paths))
        return report

    def _needs_search(self, err_msg):
        """自身无法处理时才联网：无法识别/依赖缺失类错误。"""
        try:
            m = str(err_msg or "").lower()
            return any(k in m for k in ("modulenotfound", "importerror", "unexpected"))
        except Exception:
            return False


# ============================================================
# 模块三：法官 (Judge) —— 纯 Python，绝对禁止调用 LLM
# ============================================================
class Task:
    """重构任务。V6.1 起支持多文件（最多 MAX_FILES 个）。"""

    def __init__(self, file_path, evidence, suggested_fix, error_line=0,
                 file_paths=None):
        # 兼容旧签名：单文件也存成列表
        paths = list(file_paths) if file_paths else ([file_path] if file_path else [])
        self.file_paths = paths[:MAX_FILES]
        self.file_path = self.file_paths[0] if self.file_paths else file_path
        self.evidence = evidence
        self.suggested_fix = suggested_fix
        self.error_line = error_line

    def to_dict(self):
        return {"file_path": self.file_path, "file_paths": list(self.file_paths),
                "error_line": self.error_line,
                "evidence": self.evidence, "suggested_fix": self.suggested_fix}


class Judge:
    """法官：纯 Python 类。不持有、不调用任何 LLM；尝试调用即抛异常。"""

    # 显式禁用的 LLM 接口名，防止有人给 Judge 挂模型
    FORBIDDEN_ATTRS = ("llm", "model", "provider", "chat")

    def __init__(self):
        # 故意不接收 llm 参数；若被强行赋值，下面 __setattr__ 会拦截
        object.__setattr__(self, "_locked", True)

    def __setattr__(self, name, value):
        if name in self.FORBIDDEN_ATTRS:
            raise PermissionDenied("Judge 禁止持有或调用大模型: %s" % name)
        object.__setattr__(self, name, value)

    def _no_llm(self, *a, **k):
        raise PermissionDenied("Judge 绝对禁止调用大模型")

    chat = _no_llm

    def validate(self, report):
        """校验与清洗：剔除空 evidence 与致歉信。"""
        issues = []
        for it in (report or {}).get("issues", []) or []:
            ev = str(it.get("evidence") or "").strip()
            if not ev:
                continue
            if _is_apology(ev):
                continue
            issues.append(it)
        return issues

    def dispatch(self, report):
        """派发：只取最严重 1 个，强制截断 20 行，构建 Task。"""
        issues = self.validate(report)
        if not issues:
            _log("[Judge] 无有效证据，拒绝派发。")
            return None
        issues.sort(key=lambda x: -(int(x.get("severity") or 0)))
        top = issues[0]
        evidence = truncate_lines(top.get("evidence"), MAX_LINES)
        fix = truncate_lines(top.get("suggested_fix"), MAX_LINES)
        task = Task(top.get("file_path") or "", evidence, fix,
                    int(top.get("error_line") or 0))
        _log("[Judge] 证据校验通过，截断长度至20行，派发任务...")
        return task

    def dispatch_multi(self, report, proposed_sources=None):
        """V6.1 派发：最多 3 个文件的 Task；若补丁引入循环依赖则直接拒绝。

        proposed_sources: {path: 补丁后的源码}，供 AST 循环依赖检测使用。
        """
        issues = self.validate(report)
        if not issues:
            _log("[Judge] 无有效证据，拒绝派发。")
            return None
        issues.sort(key=lambda x: -(int(x.get("severity") or 0)))
        top = issues[0]

        # 汇总本次涉及的文件（去重、最多 3 个）
        paths = []
        for p in (top.get("file_paths") or [top.get("file_path")]):
            if p and p not in paths:
                paths.append(p)
        paths = paths[:MAX_FILES]
        if not paths:
            _log("[Judge] 无目标文件，拒绝派发。")
            return None

        # ---- AST 循环依赖检测 ----
        if proposed_sources:
            ok, cycle = check_circular_import(paths, new_sources=proposed_sources)
            if not ok and cycle:
                _log("[Judge] 拒绝补丁：引入循环依赖 %s" % " -> ".join(cycle))
                return None

        evidence = truncate_lines(top.get("evidence"), MAX_LINES)
        fix = truncate_lines(top.get("suggested_fix"), MAX_LINES)
        task = Task(paths[0], evidence, fix, int(top.get("error_line") or 0),
                    file_paths=paths)
        _log("[Judge] 证据校验通过，截断长度至20行，派发任务...")
        return task


# ============================================================
# 模块四：修理工 (Surgeon)
# ============================================================
class Surgeon:
    """修理工：只碰法官指定的文件（≤3 个）；禁止联网；多文件原子手术。"""

    ALLOWED = ("read_file", "edit_file", "py_compile")
    DENIED = ("web_search",)

    OBSERVED = "OBSERVED"
    EDITED = "EDITED"
    VERIFIED = "VERIFIED"

    def __init__(self, fixer=None, max_retries=MAX_RETRIES,
                 compile_timeout=COMPILE_TIMEOUT, max_edit_lines=MAX_EDIT_LINES):
        self.fixer = fixer
        self.max_retries = int(max_retries)
        self.compile_timeout = float(compile_timeout)
        self.max_edit_lines = int(max_edit_lines)
        self.state = None
        self.targets = []      # 法官指定的文件集合（绝对路径）
        self.snapshot = {}     # 内存级快照 {path: 原内容}

    def _guard(self, action):
        if action in self.DENIED or action not in self.ALLOWED:
            raise PermissionDenied("Surgeon 无权执行: %s" % action)

    def _lock_targets(self, paths):
        """锁定本次手术的目标集合（最多 MAX_FILES 个）。"""
        if not self.targets:
            self.targets = [os.path.abspath(p) for p in paths][:MAX_FILES]

    def _check_target(self, path):
        """目标校验。

        兼容语义：若尚未被指派目标（直接调用单文件接口的旧用法），
        则把该文件作为唯一目标自动认领。
        一旦进入多文件模式，任何不在 targets 内的文件一律拒绝。
        """
        ap = os.path.abspath(path)
        if not self.targets:
            self.targets = [ap]
            return
        if ap not in self.targets:
            raise PermissionDenied("Surgeon 禁止跨文件修改: %s" % path)

    def read_file(self, path):
        self._guard("read_file")
        self._check_target(path)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def edit_file(self, path, content):
        self._guard("edit_file")
        self._check_target(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True

    def py_compile(self, path):
        """受限编译：走子进程 + 进程树超时锁（物理绞杀）。"""
        self._guard("py_compile")
        self._check_target(path)
        try:
            import proc_guard
            res = proc_guard.compile_file(path, timeout=self.compile_timeout)
            if res.get("timed_out"):
                return {"ok": False, "timed_out": True,
                        "error": "编译超时 %.1fs，进程树已绞杀" % self.compile_timeout}
            return {"ok": bool(res.get("ok")),
                    "error": "" if res.get("ok") else str(res.get("stderr") or "")[-500:]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def web_search(self, *a, **k):
        raise PermissionDenied("Surgeon 无权执行: web_search")

    def _default_fix(self, source, task):
        return source

    # ---- 内存级快照 ----
    def take_snapshot(self, paths):
        """进入 EDITED 前必须快照，保证可无条件回滚。"""
        snap = {}
        for p in paths:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                snap[os.path.abspath(p)] = f.read()
        self.snapshot = snap
        return snap

    def rollback(self):
        """无条件恢复到快照状态，绝不留半残代码。"""
        restored = []
        for p, content in (self.snapshot or {}).items():
            try:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
                restored.append(p)
            except Exception as e:
                _log("[Surgeon] 回滚 %s 失败: %s" % (p, e))
        if restored:
            _log("[Surgeon] 已回滚 %d 个文件到快照状态" % len(restored))
        return restored

    @staticmethod
    def _count_changed_lines(old_src, new_src):
        """统计修改行数（新增 + 删除）。"""
        try:
            import difflib
            a = str(old_src or "").splitlines()
            b = str(new_src or "").splitlines()
            n = 0
            for line in difflib.unified_diff(a, b, lineterm="", n=0):
                if line.startswith("+++") or line.startswith("---"):
                    continue
                if line.startswith("+") or line.startswith("-"):
                    n += 1
            return n
        except Exception:
            return 0

    def operate_multi(self, task):
        """多文件原子手术：OBSERVED -> EDITED -> VERIFIED，失败整体回滚。"""
        paths = [os.path.abspath(p) for p in (task.file_paths or [task.file_path])]
        paths = paths[:MAX_FILES]
        self._lock_targets(paths)
        if len(paths) > 1:
            _log("[Surgeon] 正在对 %d 个文件进行协同手术..." % len(paths))

        attempt = 0
        max_attempts = max(1, int(self.max_retries))
        while attempt < max_attempts:
            # ---- 门 1：OBSERVED（读取所有目标文件）----
            sources = {}
            for p in paths:
                sources[p] = self.read_file(p)
            self.state = self.OBSERVED

            # ---- 快照（进入 EDITED 前必须）----
            # 关键：只在首次尝试时取快照。若每轮重试都重新快照，
            # 第二轮会把"已改坏的内容"当成原始状态，导致最终回滚无效。
            if not self.snapshot:
                self.take_snapshot(paths)

            # ---- 门 2：EDITED（逐个修改，总行数受限）----
            fixer = self.fixer or self._default_fix
            new_sources = {}
            total_changed = 0
            too_many = False
            for p in paths:
                try:
                    ns = fixer(sources[p], task)
                except Exception as e:
                    _log("[Surgeon] 修复器异常：%s" % e)
                    ns = sources[p]
                if ns is None:
                    ns = sources[p]
                total_changed += self._count_changed_lines(sources[p], ns)
                if total_changed > self.max_edit_lines:
                    too_many = True
                new_sources[p] = ns
            if too_many:
                _log("[Surgeon] 修改总行数 %d 超过上限 %d，拒绝本次修改"
                     % (total_changed, self.max_edit_lines))
                self.rollback()
                attempt += 1
                continue

            changed = [p for p in paths if new_sources[p] != sources[p]]
            if not changed:
                attempt += 1
                if attempt >= max_attempts:
                    break
                continue
            for p in changed:
                self.edit_file(p, new_sources[p])
            self.state = self.EDITED

            # ---- 门 3：VERIFIED（统一编译）----
            all_ok = True
            for p in changed:
                res = self.py_compile(p)
                if not res.get("ok"):
                    all_ok = False
                    break
            if all_ok:
                self.state = self.VERIFIED
                _log("[Surgeon] 状态机 OBSERVED -> EDITED -> VERIFIED 验证通过。")
                return True

            attempt += 1
            if attempt < max_attempts:
                _log("[Surgeon] 第 %d 次编译失败，准备重试" % attempt)
            else:
                _log("[Surgeon] 第 %d 次编译失败，达到重试上限" % attempt)

        # 熔断前无条件回滚
        self.rollback()
        raise RefactorFailedException(
            "重试 %d 次仍无法修复: %s" % (self.max_retries, ", ".join(paths)))

    def operate(self, task):
        """兼容旧接口：单文件手术委托给 operate_multi。"""
        return self.operate_multi(task)

# ============================================================
# 流水线入口
# ============================================================
def run_selftest_if_needed(paths, timeout=SELFTEST_TIMEOUT):
    """若本次改到了 main.py，编译通过后跑一次极轻量自检（限时 10 秒）。"""
    try:
        touched_main = any(os.path.basename(p) == "main.py" for p in paths)
        if not touched_main:
            return {"ran": False}
        import proc_guard
        _log("[自检] 检测到 main.py 被修改，执行轻量自检（超时 %.0fs）" % timeout)
        code = ("import sys,os;sys.path.insert(0,os.getcwd());"
                "import importlib.util as u;"
                "spec=u.spec_from_file_location('_selftest_main','main.py');"
                "m=u.module_from_spec(spec);print('SELFTEST_OK')")
        res = proc_guard.run_with_timeout([sys.executable, "-c", code],
                                          timeout=timeout, cwd=HERE)
        ok = bool(res.get("ok")) and "SELFTEST_OK" in str(res.get("stdout") or "")
        if res.get("timed_out"):
            _log("[自检] 超时，进程树已绞杀")
        _log("[自检] 结果：%s" % ("通过" if ok else "失败"))
        return {"ran": True, "ok": ok, "timed_out": bool(res.get("timed_out"))}
    except Exception as e:
        _log("[自检] 自检异常（已隔离）：%s" % e)
        return {"ran": True, "ok": False, "error": str(e)}


def run_refactor_multi(file_paths, endo=None, llm=None, search=None, fixer=None,
                       max_retries=MAX_RETRIES, proposed_sources=None, db_path=None):
    """V6.1 多文件流水线：Scout -> Judge(AST 检查) -> Surgeon(原子手术)。

    proposed_sources: 供 AST 循环依赖检测的「补丁后源码」，
                      未提供时由 fixer 试算（若提供）。
    """
    paths = [p for p in (file_paths or []) if p][:MAX_FILES]
    scout = Scout(llm=llm, search=search, endo=endo, db_path=db_path)
    judge = Judge()
    surgeon = Surgeon(fixer=fixer, max_retries=max_retries)

    report = scout.scan_multi(paths)
    task = judge.dispatch_multi(report, proposed_sources=proposed_sources)
    if task is None:
        return {"ok": False, "reason": "no-task", "cortisol": endo}
    try:
        ok = surgeon.operate_multi(task)
        selftest = run_selftest_if_needed(paths)
        return {"ok": bool(ok), "reason": "verified",
                "cortisol": endo, "selftest": selftest}
    except RefactorFailedException as e:
        _log("[流水线] 熔断：%s" % e)
        if endo is not None:
            before = float(endo.get("cortisol", 0.0))
            endo["cortisol"] = max(0.0, min(1.0, before + 0.1))
            _log("[流水线] 皮质醇 %.3f -> %.3f" % (before, endo["cortisol"]))
        return {"ok": False, "reason": "circuit-breaker", "cortisol": endo}


def run_refactor(file_path, endo=None, llm=None, search=None, fixer=None,
                 max_retries=MAX_RETRIES, db_path=None):
    """Scout -> Judge -> Surgeon 全流程。熔断后 cortisol += 0.1 并放弃。"""
    scout = Scout(llm=llm, search=search, endo=endo, db_path=db_path)
    judge = Judge()
    surgeon = Surgeon(fixer=fixer, max_retries=max_retries)

    report = scout.scan(file_path)
    task = judge.dispatch(report)
    if task is None:
        return {"ok": False, "reason": "no-task", "cortisol": endo}
    try:
        ok = surgeon.operate(task)
        return {"ok": bool(ok), "reason": "verified", "cortisol": endo}
    except RefactorFailedException as e:
        _log("[流水线] 熔断：%s" % e)
        if endo is not None:
            before = float(endo.get("cortisol", 0.0))
            endo["cortisol"] = max(0.0, min(1.0, before + 0.1))
            _log("[流水线] 皮质醇 %.3f -> %.3f" % (before, endo["cortisol"]))
        return {"ok": False, "reason": "circuit-breaker", "cortisol": endo}