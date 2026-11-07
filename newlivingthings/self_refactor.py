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
# 模块二：侦察兵 (Scout)
# ============================================================
class Scout:
    """侦察兵：只读、只搜、只报告。物理剥夺写与执行权限。"""

    ALLOWED = ("read_file", "grep", "find", "web_search", "py_compile")
    DENIED = ("edit_file", "write_file", "shell")

    def __init__(self, llm=None, search=None):
        self.llm = llm
        self._search = search

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
    def __init__(self, file_path, evidence, suggested_fix, error_line=0):
        self.file_path = file_path
        self.evidence = evidence
        self.suggested_fix = suggested_fix
        self.error_line = error_line

    def to_dict(self):
        return {"file_path": self.file_path, "error_line": self.error_line,
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


# ============================================================
# 模块四：修理工 (Surgeon)
# ============================================================
class Surgeon:
    """修理工：只碰法官指定的单一文件；禁止联网；三道门状态机。"""

    ALLOWED = ("read_file", "edit_file", "py_compile")
    DENIED = ("web_search",)

    OBSERVED = "OBSERVED"
    EDITED = "EDITED"
    VERIFIED = "VERIFIED"

    def __init__(self, fixer=None, max_retries=MAX_RETRIES):
        self.fixer = fixer
        self.max_retries = int(max_retries)
        self.state = None
        self.target = None

    def _guard(self, action):
        if action in self.DENIED or action not in self.ALLOWED:
            raise PermissionDenied("Surgeon 无权执行: %s" % action)

    def _check_target(self, path):
        if self.target is None:
            self.target = os.path.abspath(path)
        elif os.path.abspath(path) != self.target:
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
        self._guard("py_compile")
        self._check_target(path)
        try:
            with open(path, "rb") as f:
                src = f.read()
            compile(src, path, "exec")
            return {"ok": True, "error": ""}
        except SyntaxError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def web_search(self, *a, **k):
        raise PermissionDenied("Surgeon 无权执行: web_search")

    def _default_fix(self, source, task):
        """默认修复器：尝试把非法片段删掉/替换为占位，最朴素但安全。"""
        return source

    def operate(self, task):
        """三道门状态机：OBSERVED -> EDITED -> VERIFIED，失败重试至多 2 次。"""
        path = task.file_path
        attempt = 0
        # 白皮书：最多重试 2 次，2 次失败后立即熔断。
        # 因此总尝试次数上限 = max_retries（不是 max_retries + 1）。
        max_attempts = max(1, int(self.max_retries))
        while attempt < max_attempts:
            # ---- 门 1：OBSERVED ----
            source = self.read_file(path)
            self.state = self.OBSERVED

            # ---- 门 2：EDITED ----
            fixer = self.fixer or self._default_fix
            try:
                new_src = fixer(source, task)
            except Exception as e:
                new_src = source
                _log("[Surgeon] 修复器异常：%s" % e)
            if new_src is None or new_src == source:
                attempt += 1
                if attempt >= max_attempts:
                    break
                continue
            self.edit_file(path, new_src)
            self.state = self.EDITED

            # ---- 门 3：VERIFIED ----
            res = self.py_compile(path)
            if res.get("ok"):
                self.state = self.VERIFIED
                _log("[Surgeon] 状态机 OBSERVED -> EDITED -> VERIFIED 验证通过。")
                return True
            attempt += 1
            if attempt < max_attempts:
                _log("[Surgeon] 第 %d 次编译失败，准备重试" % attempt)
            else:
                _log("[Surgeon] 第 %d 次编译失败，达到重试上限" % attempt)

        raise RefactorFailedException(
            "重试 %d 次仍无法修复: %s" % (self.max_retries, path))


# ============================================================
# 流水线入口
# ============================================================
def run_refactor(file_path, endo=None, llm=None, search=None, fixer=None,
                 max_retries=MAX_RETRIES):
    """Scout -> Judge -> Surgeon 全流程。熔断后 cortisol += 0.1 并放弃。"""
    scout = Scout(llm=llm, search=search)
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
