# plugin_manager.py
# -*- coding: utf-8 -*-
"""plugin_manager.py -- AC OS V9.4 插件系统（Plugin System）

白皮书：PLUGIN_SYSTEM_WHITEPAPER.md

最高铁律：**开放式接口，封闭式安全**。
  1. manifest.json 规范校验（name / version / entry / function / capabilities）
  2. AST 静态免疫审计：只认代码结构，不认注释字符串
  3. 能力白名单：ctx 只暴露只读接口；未声明 network 的插件联网必被拒
  4. 子进程物理绞杀：multiprocessing 隔离 + timeout=10s，超时直接杀进程并拉黑
  5. 输出强制截断：text[:500]，防止撑爆主上下文
  6. 热更新：按「清单 + 入口文件」哈希对比，发现新增/变更自动挂载

本模块的任何函数都不允许把异常抛给主循环（除显式 raise 的 PluginError），
主循环即使插件全烂也只会多几滴皮质醇，绝不会崩。
"""

import ast
import hashlib
import json
import multiprocessing
import os
import re
import sys
import threading
import time

# ============================================
# 常量（白皮书硬指标，禁止随意放宽）
# ============================================
PLUGIN_TIMEOUT = 10          # 白皮书：强制 timeout=10 秒
MAX_OUTPUT_CHARS = 500       # 白皮书：text[:500] 强制截断
MAX_PLUGIN_LINES = 100       # 白皮书：代码行数严格限制在 100 行以内
MAX_MANIFEST_BYTES = 64 * 1024
MAX_SOURCE_BYTES = 512 * 1024
PLUGIN_PREFIX = "plugin_"     # 注册到 tool_caller 白名单的命名规则
MAX_HORMONE_REQUESTS = 5      # V9.5：单个插件单次执行最多申请几种动态激素

# ---- AST 黑名单：模块 / 函数 / 属性 三层全部拦截 ----
BANNED_MODULES = frozenset({
    "os", "subprocess", "socket", "sys", "shutil", "pathlib", "ctypes",
    "pickle", "marshal", "importlib", "builtins", "__builtin__", "pty",
    "multiprocessing", "threading", "signal", "resource", "gc", "inspect",
    "tempfile", "glob", "sqlite3", "urllib", "urllib2", "urllib3",
    "http", "requests", "ftplib", "telnetlib", "smtplib", "asyncio",
    "platform", "getpass", "webbrowser", "code", "codeop", "runpy",
    "site", "sysconfig", "distutils", "setuptools", "pkg_resources",
})
BANNED_CALLS = frozenset({
    "eval", "exec", "compile", "__import__", "open", "input", "globals",
    "locals", "vars", "getattr", "setattr", "delattr", "breakpoint",
    "memoryview", "exit", "quit",
})
BANNED_ATTRS = frozenset({
    "system", "popen", "spawn", "spawnl", "spawnv", "fork", "execv",
    "execve", "execl", "remove", "unlink", "rmdir", "rmtree", "chmod",
    "chown", "kill", "killpg", "setuid", "setgid",
    "__class__", "__bases__", "__subclasses__", "__globals__", "__code__",
    "__closure__", "__mro__", "__reduce__", "__reduce_ex__", "__getattribute__",
})
# 源码级兜底正则（词边界，避免 urlopen 被 open 误伤、posix 被 os 误伤）
_BANNED_NAME_RE = {
    "os": r"(?<![a-z0-9_.])os\s*\.",
    "subprocess": r"(?<![a-z0-9_.])subprocess\s*\.",
    "socket": r"(?<![a-z0-9_.])socket\s*\.",
}
_DANGEROUS_MAGIC = ("__subclasses__", "__globals__", "__bases__", "__builtins__")

# 插件可以 import 的标准库（纯计算 / 纯文本，无 IO 无进程无网络）
SAFE_IMPORTS = frozenset({
    "json", "re", "math", "random", "time", "datetime", "itertools",
    "functools", "collections", "string", "textwrap", "unicodedata",
    "statistics", "decimal", "fractions", "hashlib", "base64", "binascii",
    "uuid", "copy", "enum", "typing", "dataclasses", "operator", "bisect",
    "heapq", "array", "numbers", "difflib", "html",
})

# 已知能力白名单（V9.4 定义 network；V9.5 增加 chemical —— 动态激素注入）
KNOWN_CAPABILITIES = frozenset({"network", "chemical"})

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PLUGINS_DIR = os.path.join(HERE, "plugins")
BLACKLIST_FILE = os.path.join(HERE, "plugin_blacklist.json")

LOG_PREFIX = "[插件]"

# multiprocessing 全局状态（进程级单例，热更新与测试共享）
_MP_LOCK = threading.Lock()
_MP_CTX = None
_MP_EXECUTOR = None


def _log(msg):
    try:
        print("%s %s" % (LOG_PREFIX, msg), flush=True)
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


class PluginError(Exception):
    """插件生命周期中的可预期错误（审计拒绝 / 清单非法 / 超时拉黑）。"""


class PluginAuditResult(object):
    def __init__(self, ok, reason="", violations=None):
        self.ok = ok
        self.reason = reason
        self.violations = violations or []

    def __repr__(self):
        return "PluginAuditResult(ok=%s, reason=%r)" % (self.ok, self.reason)


# ============================================
# 一、manifest.json 解析与初检
# ============================================
def _safe_join(root, rel):
    """把 manifest 里的相对路径安全地拼到插件根目录，禁止路径穿越。"""
    rel = str(rel or "").strip()
    if not rel:
        raise PluginError("entry 为空")
    if os.path.isabs(rel) or rel.startswith("~"):
        raise PluginError("entry 不允许绝对路径: %s" % rel)
    full = os.path.normpath(os.path.join(root, rel))
    root_abs = os.path.normpath(os.path.abspath(root))
    if os.path.commonpath([root_abs, os.path.abspath(full)]) != root_abs:
        raise PluginError("entry 越界（路径穿越）: %s" % rel)
    return full


def parse_manifest(plugin_dir):
    """读取并校验 manifest.json，返回规范化后的 dict（非法即抛 PluginError）。"""
    path = os.path.join(plugin_dir, "manifest.json")
    if not os.path.isfile(path):
        raise PluginError("缺少 manifest.json")
    try:
        size = os.path.getsize(path)
        if size > MAX_MANIFEST_BYTES:
            raise PluginError("manifest.json 过大（%d bytes）" % size)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except PluginError:
        raise
    except json.JSONDecodeError as e:
        raise PluginError("manifest.json 不是合法 JSON: %s" % e)
    except Exception as e:
        raise PluginError("manifest.json 读取失败: %s: %s" % (type(e).__name__, e))
    if not isinstance(data, dict):
        raise PluginError("manifest.json 顶层必须是对象")

    out = {}
    for key in ("name", "version", "entry", "function"):
        val = data.get(key)
        if not isinstance(val, str) or not val.strip():
            raise PluginError("manifest 缺少必填字段: %s" % key)
        out[key] = val.strip()
    # 插件名只允许字母数字下划线中划线，作为白名单 key 必须干净
    name = out["name"]
    if not all(c.isalnum() or c in "_-" for c in name) or name.startswith("_"):
        raise PluginError("插件名非法（只允许字母数字 _-）: %r" % name)
    func = out["function"]
    if not (func.isidentifier() and not func.startswith("_")):
        raise PluginError("function 名非法: %r" % func)

    caps = data.get("capabilities") or []
    if not isinstance(caps, list) or any(not isinstance(c, str) for c in caps):
        raise PluginError("capabilities 必须是字符串数组")
    caps = [c.strip().lower() for c in caps if c.strip()]
    unknown = sorted(set(caps) - KNOWN_CAPABILITIES)
    if unknown:
        raise PluginError("未知能力声明（白名单外）: %s" % ", ".join(unknown))
    out["capabilities"] = sorted(set(caps))

    out["entry_path"] = _safe_join(plugin_dir, out["entry"])
    if not os.path.isfile(out["entry_path"]):
        raise PluginError("入口文件不存在: %s" % out["entry"])
    desc = data.get("description")
    out["description"] = desc.strip()[:200] if isinstance(desc, str) else ""
    out["dir"] = os.path.abspath(plugin_dir)
    return out


def plugin_digest(manifest):
    """清单 + 入口文件的联合哈希，热更新以此判断「新增/变更」。"""
    h = hashlib.sha256()
    for path in (os.path.join(manifest["dir"], "manifest.json"), manifest["entry_path"]):
        try:
            with open(path, "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
        except Exception as e:
            h.update(("ERR:%s" % e).encode("utf-8", "replace"))
    return h.hexdigest()[:32]


# ============================================
# 二、AST 静态免疫审计（核心防线）
# ============================================
def _module_root(name):
    return str(name or "").split(".")[0]


def _strip_comments_and_strings(source):
    """用 tokenize 剥离注释与字符串字面量，只留下真正的代码文本。

    AST 本身就会忽略注释，这里是给「源码级正则兜底」用的：
    先剥掉注释/字符串，正则就不会被注释里的 `os.` 误触发，
    也不会因为把黑名单关键字藏进字符串就逃过检查。
    """
    import io
    import tokenize
    try:
        pieces = []
        readline = io.StringIO(source).readline
        for tok in tokenize.generate_tokens(readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING,
                            tokenize.FSTRING_START if hasattr(tokenize, "FSTRING_START") else -1,
                            getattr(tokenize, "FSTRING_MIDDLE", -1)):
                continue
            pieces.append(tok.string)
        return "\n".join(pieces)
    except Exception:
        # tokenize 失败（语法畸形）-> 语法层已经会拒绝，这里退回原文
        return source


def audit_source(source, capabilities=None):
    """AST 免疫审计：只认代码结构，不认注释与字符串。

    返回 PluginAuditResult；绝不抛异常。
    """
    caps = set(capabilities or [])
    src = str(source or "")
    if not src.strip():
        return PluginAuditResult(False, "插件代码为空")

    lines = [ln for ln in src.splitlines() if ln.strip()]
    if len(lines) > MAX_PLUGIN_LINES:
        return PluginAuditResult(
            False, "代码超过 %d 行限制（实际 %d 行）" % (MAX_PLUGIN_LINES, len(lines)))
    if len(src.encode("utf-8", "replace")) > MAX_SOURCE_BYTES:
        return PluginAuditResult(False, "源码体积超过上限")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return PluginAuditResult(False, "语法错误: %s" % (e.msg,))

    bad = []

    # ---- 1. import 层：黑名单模块 / 白名单外模块 一律拒绝 ----
    for node in ast.walk(tree):
        roots = []
        if isinstance(node, ast.Import):
            for a in node.names:
                roots.append(("import", a.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                bad.append("相对导入(level=%d)" % node.level)
            if node.module:
                roots.append(("from", node.module))
            else:
                roots.append(("from", ""))
        for kind, mod in roots:
            root = _module_root(mod)
            if not root:
                bad.append("%s 导入了匿名模块" % kind)
                continue
            if root in BANNED_MODULES:
                bad.append("危险模块 %s" % root)
                continue
            if "network" in caps and root == "network":
                # 唯一允许的出网通道：注入的 ctx.net（manifest 声明后可自行导入）
                continue
            if root not in SAFE_IMPORTS:
                bad.append("非白名单 import: %s" % root)

    # ---- 2. 调用层：eval / exec / open / getattr ... ----
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in BANNED_CALLS:
            bad.append("危险调用 %s()" % fn.id)
        elif isinstance(fn, ast.Attribute) and fn.attr in BANNED_ATTRS:
            bad.append("危险属性调用 .%s()" % fn.attr)

    # ---- 3. 属性链 / 双下划线穿透：__subclasses__、__globals__ ... ----
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                if node.attr in BANNED_ATTRS or node.attr == "__dict__":
                    bad.append("双下划线穿透 %s" % node.attr)
        elif isinstance(node, ast.Name):
            if node.id in _DANGEROUS_MAGIC:
                bad.append("危险内建引用 %s" % node.id)

    # ---- 4. 源码级兜底：用 tokenize 剥离注释与字符串后，再按词边界匹配 ----
    # 目的：覆盖 'import os'（AST 的 Import 已拦）与 'os.system(...)' 这类
    # **没有点号前面 import** 的情况下可能被拼写变体绕过的写法。
    # 关键：先 tokenize 去掉注释和字符串常量，所以「注释伪装」既拦不住人、
    # 也不会误伤（注释里写 import os 不会触发告警，但也不会被当成通行证）。
    active = _strip_comments_and_strings(src)
    low = active.lower()
    for word, pattern in _BANNED_NAME_RE.items():
        hit = re.search(pattern, low)
        if not hit:
            # import 形式：tokenize 后按词边界看是否存在该模块名
            hit = re.search(r"(?m)^\s*(?:import|from)\s+%s\b" % re.escape(word), low)
        if word in BANNED_MODULES and hit:
            if ("危险模块 %s" % word) not in bad:
                bad.append("危险模块 %s（源码级命中）" % word)

    if bad:
        uniq = sorted(set(bad))
        return PluginAuditResult(
            False, "免疫拦截: %s" % "; ".join(uniq[:6]), uniq)
    return PluginAuditResult(True, "审计通过")


# ============================================
# 三、运行时上下文 ctx（能力白名单注入 + 子进程侧守卫）
# ============================================
class NetworkDenied(PermissionError):
    """未声明 network 能力的插件试图联网。"""


class ChemicalPermissionDenied(PermissionError):
    """未声明 chemical 能力的插件试图注入动态激素（V9.5）。"""


class BridgeUnavailable(ConnectionError):
    """已授权联网，但宿主机桥接不可达（网络问题，不是能力问题）。"""


class _NetDenied(object):
    """未授权网络接口：任何调用都抛 NetworkDenied（明确拒绝，不静默返回空）。"""

    __slots__ = ("reason",)

    def __init__(self, reason):
        self.reason = reason

    def _deny(self, *a, **kw):
        raise NetworkDenied(self.reason)

    post = _deny
    get = _deny
    fetch = _deny
    request = _deny

    def __repr__(self):
        return "<NetDenied %s>" % self.reason


class _Net(object):
    """已授权网络接口：强制走宿主机桥接（host_agent_bridge:5555），绝不裸连外网。"""

    BRIDGE_URL = os.environ.get("AC_BRIDGE_URL",
                                "http://host.docker.internal:5555/api/exec")
    TIMEOUT = 8
    MAX_CHARS = MAX_OUTPUT_CHARS
    def post(self, url, data=None, timeout=None):
        # 注意：本方法在子进程内执行，urllib 由 _child_entry 预注入
        import json as _json
        import urllib.error as _ue
        import urllib.request as _ur
        target = str(url or "").strip()
        if not target:
            raise ValueError("net.post 需要 url")
        payload = _json.dumps({"url": target, "task": str(data or ""),
                               "timeout": timeout or self.TIMEOUT},
                              ensure_ascii=False).encode("utf-8")
        req = _ur.Request(self.BRIDGE_URL, data=payload,
                          headers={"Content-Type": "application/json; charset=utf-8"},
                          method="POST")
        try:
            with _ur.urlopen(req, timeout=(timeout or self.TIMEOUT) + 5) as r:
                raw = r.read().decode("utf-8", "replace")
        except (_ue.URLError, OSError) as e:
            # 能力已授权，但桥接不可达 -> 明确报"桥接故障"，绝不伪装成能力拒绝
            raise BridgeUnavailable(
                "宿主机桥接不可达（%s）: %s。请确认 ensure_bridge.ps1 已启动"
                % (self.BRIDGE_URL, e))
        try:
            body = _json.loads(raw)
        except Exception:
            return raw[:self.MAX_CHARS]
        if isinstance(body, dict):
            return str(body.get("result") or body.get("error") or "")[:self.MAX_CHARS]
        return str(body)[:self.MAX_CHARS]

    def get(self, url, **kw):
        return self.post(url, data=kw.get("data", ""), timeout=kw.get("timeout"))


class PluginContext(object):
    """注入给插件主函数的 ctx —— 只读、无状态、可 JSON 序列化。

    白皮书：只暴露安全的只读接口 get_vitality() / get_dopamine() 等；
    联网必须走 ctx.net.post() 且 manifest 声明 network。
    """

    __slots__ = ("name", "capabilities", "_endo", "_vitality", "_clock",
                 "hormone_requests")

    def __init__(self, name, capabilities=None, endo=None, vitality=100, clock=None):
        self.name = name
        self.capabilities = tuple(sorted(set(capabilities or [])))
        self._endo = dict(endo or {})
        self._vitality = vitality
        self._clock = clock
        # V9.5：本次执行期间申请的动态激素（由宿主主进程统一落库）
        self.hormone_requests = []

    # ---- 只读生理接口 ----
    def get_vitality(self):
        try:
            return int(self._vitality)
        except (TypeError, ValueError):
            return 100

    def get_dopamine(self):
        return clamp01(self._endo.get("dopamine", 0.0))

    def get_cortisol(self):
        return clamp01(self._endo.get("cortisol", 0.0))

    def get_endorphin(self):
        return clamp01(self._endo.get("endorphin", 0.0))

    def get_name(self):
        return self.name

    def has_capability(self, cap):
        return str(cap or "").lower() in self.capabilities

    def now(self):
        return self._clock if self._clock is not None else time.time()

    # ---- 能力白名单 ----
    @property
    def net(self):
        if "network" in self.capabilities:
            return _Net()
        return _NetDenied("插件 %r 未声明 network 能力，禁止联网" % self.name)

    # ---- V9.5 动态激素注入（必须声明 chemical） ----
    def synthesize_hormone(self, name, value=0.5, biological_meaning="",
                           decay_rate=None, temperature=None, priority=0):
        """向宿主内核注入一种动态激素。

        权限铁律：未声明 chemical 能力的插件一律拦截（抛 PermissionError）。
        子进程里只能拿到「已登记的申请单」，真正的合成由宿主主进程落库 ——
        插件永远无法直接改写内核的激素表。
        """
        if "chemical" not in self.capabilities:
            raise ChemicalPermissionDenied(
                "插件 %r 未声明 chemical 能力，禁止注入激素" % self.name)
        req = {"name": str(name or ""),
               "value": value,
               "biological_meaning": str(biological_meaning or ""),
               "temperature": temperature, "priority": priority}
        if decay_rate is not None:
            req["decay_rate"] = decay_rate
        # 限制单次执行最多申请 5 条，防止恶意插件刷爆申请单
        if len(self.hormone_requests) >= MAX_HORMONE_REQUESTS:
            raise HormoneError("单次执行最多申请 %d 种激素" % MAX_HORMONE_REQUESTS)
        self.hormone_requests.append(req)
        return {"ok": True, "queued": True, "name": req["name"]}

    def to_dict(self):
        return {"name": self.name, "capabilities": list(self.capabilities),
                "vitality": self.get_vitality(),
                "endo": {"dopamine": self.get_dopamine(),
                         "cortisol": self.get_cortisol(),
                         "endorphin": self.get_endorphin()}}


def make_callable_ctx(ctx_dict):
    """在子进程内把 ctx 字典还原成真正的 PluginContext（含网络守卫）。"""
    return PluginContext(ctx_dict.get("name", "?"),
                         ctx_dict.get("capabilities") or [],
                         ctx_dict.get("endo") or {},
                         ctx_dict.get("vitality", 100))


# ============================================
# 四、子进程执行体（必须定义在模块顶层，否则 spawn 无法 pickl）
# ============================================
def _child_entry(conn, plugin_meta, query, ctx_dict):
    """子进程内：加载插件模块 -> 调用主函数 -> 把结果塞回管道。

    绝不允许把异常抛出去：一切失败都转成 {"ok": False, ...} 回传父进程。
    """
    import os as _os
    import sys as _sys
    try:
        _sys.stdout.flush()
    except Exception:
        pass
    # 子进程是「无窗口的沉默器官」：插件里任何 print 都不允许污染主循环日志
    try:
        _devnull = open(_os.devnull, "w", encoding="utf-8")
        _sys.stdout = _devnull
        _sys.stderr = _devnull
    except Exception:
        pass
    path = plugin_meta.get("entry_path")
    func_name = plugin_meta.get("function") or "run"
    name = plugin_meta.get("name") or "?"
    try:
        import importlib.util
        # 网络能力已在父进程审计过 manifest，这里只给已授权的插件补 urllib
        if "network" in (plugin_meta.get("capabilities") or []):
            import urllib.request  # noqa: F401  仅 _Net 内部使用
        spec = importlib.util.spec_from_file_location(
            "%s%s" % (PLUGIN_PREFIX, name), path)
        if spec is None or spec.loader is None:
            raise ImportError("无法创建模块 spec")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, func_name, None)
        if not callable(fn):
            raise AttributeError("插件缺少主函数 %s" % func_name)
        ctx = make_callable_ctx(ctx_dict)
        result = fn(ctx, query)
        conn.send({"ok": True, "result": repr(result) if not isinstance(result, str)
                   else result, "error": "",
                   # V9.5：插件申请的动态激素（未经宿主落库，只是申请单）
                   "hormones": list(getattr(ctx, "hormone_requests", []) or [])})
    except BaseException as e:  # noqa: BLE001  子进程任何异常都只回传，不逃逸
        try:
            conn.send({"ok": False, "result": "", "error": "%s: %s"
                       % (type(e).__name__, str(e)[:300]), "hormones": []})
        except Exception:
            pass


# ============================================
# 五、物理绞杀执行器（防崩核心）
# ============================================
def _mp_context():
    """优先 spawn：插件在全新解释器里跑，绝不继承主进程内存/句柄。"""
    global _MP_CTX
    with _MP_LOCK:
        if _MP_CTX is None:
            try:
                _MP_CTX = multiprocessing.get_context("spawn")
            except (ValueError, AttributeError):
                _MP_CTX = multiprocessing.get_context()
        return _MP_CTX


def _run_in_subprocess(plugin_meta, query, ctx_dict, timeout=PLUGIN_TIMEOUT):
    """把插件丢进子进程跑，超时 -> 物理 kill -> 返回 timed_out=True。

    返回 dict: {ok, result, error, timed_out, killed, elapsed}
    """
    ctx = _mp_context()
    # 用 Pipe 而非 Queue：Queue 会拉起 feeder 线程，仍会有句柄被插件子进程继承，
    # Pipe 在 spawn 下是干净的单工连接，随进程一起被物理销毁。
    recv_conn, send_conn = ctx.Pipe(duplex=False)
    started = time.time()
    proc = ctx.Process(target=_child_entry,
                       args=(send_conn, plugin_meta, query, ctx_dict),
                       name="plugin-%s" % plugin_meta.get("name", "?"),
                       daemon=True)
    out = {"ok": False, "result": "", "error": "", "timed_out": False,
           "killed": False, "elapsed": 0.0, "hormones": []}
    try:
        proc.start()
        # 父进程必须立刻丢掉写端，否则读端永远不会 EOF
        try:
            send_conn.close()
        except Exception:
            pass
        proc.join(timeout)
        if proc.is_alive():
            # ---- 物理绞杀：terminate -> 宽限 1s -> kill ----
            out["timed_out"] = True
            _hard_kill(proc)
            out["killed"] = True
            out["error"] = "插件超时 %ds，已物理强杀" % timeout
            return out
        try:
            payload = recv_conn.recv() if recv_conn.poll(1.0) else None
        except (EOFError, OSError):
            payload = None
        except Exception:
            payload = None
        if payload is None:
            rc = proc.exitcode
            out["error"] = "插件进程无返回（exitcode=%s，可能被自身崩溃终止）" % rc
            return out
        out["ok"] = bool(payload.get("ok"))
        out["result"] = payload.get("result") or ""
        out["error"] = payload.get("error") or ""
        # V9.5：把插件申请的动态激素一并带出子进程
        out["hormones"] = list(payload.get("hormones") or [])
        return out
    finally:
        out["elapsed"] = round(time.time() - started, 2)
        try:
            if proc.is_alive():
                _hard_kill(proc)
            recv_conn.close()
        except Exception:
            pass


def _hard_kill(proc):
    """真正的物理绞杀：不允许子进程自杀式的忽略 terminate。"""
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.join(1.0)
    except Exception:
        pass
    if proc.is_alive():
        try:
            if hasattr(proc, "kill"):
                proc.kill()
        except Exception:
            pass
        try:
            proc.join(1.0)
        except Exception:
            pass


def _get_executor():
    """线程池：让主循环在等待子进程时也绝不阻塞心跳（超时也有物理兜底）。"""
    global _MP_EXECUTOR
    with _MP_LOCK:
        if _MP_EXECUTOR is None:
            try:
                from concurrent.futures import ThreadPoolExecutor
                _MP_EXECUTOR = ThreadPoolExecutor(
                    max_workers=2, thread_name_prefix="plugin-runner")
            except Exception:
                _MP_EXECUTOR = False
        return _MP_EXECUTOR


def shutdown_executor():
    global _MP_EXECUTOR
    with _MP_LOCK:
        ex = _MP_EXECUTOR
        _MP_EXECUTOR = None
    if ex:
        try:
            ex.shutdown(wait=False)
        except Exception:
            pass


# ============================================
# 六、黑名单（永久拉黑，落盘持久化）
# ============================================
def load_blacklist(path=None):
    try:
        path = path or BLACKLIST_FILE
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_blacklist(data, path=None):
    path = path or BLACKLIST_FILE
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        _log("黑名单写入失败（内存中仍生效）: %s" % e)
        return False


# ============================================
# 七、插件管理器
# ============================================
class PluginManager(object):
    """扫描 / 审计 / 注册 / 绞杀 的唯一入口。

    主循环只需要两个动作：
      mgr.scan()            -> 热更新扫描（每 50 轮心跳）
      mgr.run(name, query)  -> 在子进程里跑插件（timeout=10s，超时拉黑+升皮质醇）
    """

    def __init__(self, plugins_dir=None, tool_caller=None, blacklist_path=None,
                 endo=None, timeout=PLUGIN_TIMEOUT, log=None):
        self.plugins_dir = os.path.abspath(plugins_dir or DEFAULT_PLUGINS_DIR)
        self.tool_caller = tool_caller
        self.blacklist_path = blacklist_path or BLACKLIST_FILE
        self.timeout = int(timeout)
        self.log = log or _log
        self._endo = endo if endo is not None else {}
        self._lock = threading.RLock()
        self.plugins = {}        # name -> manifest(dict) + 'digest'
        self.blacklist = load_blacklist(self.blacklist_path)
        self.hormone_registry = None   # V9.5：由主循环 bind_hormone_registry 注入
        self.last_scan_round = 0
        self.scan_count = 0
        self.kill_count = 0

    # ---------- 内分泌 ----------
    def bind_endo(self, endo):
        self._endo = endo if endo is not None else {}

    def _bump_cortisol(self, amount=0.1):
        """插件爆炸 -> 熵灵真的会焦虑。"""
        endo = self._endo
        try:
            before = clamp01(endo.get("cortisol", 0.0))
            endo["cortisol"] = round(clamp01(before + amount), 6)
            self.log("皮质醇 +%.2f -> %.2f" % (amount, endo["cortisol"]))
            return endo["cortisol"]
        except Exception:
            return None

    def _vitality(self):
        try:
            return int(self._endo.get("vitality", 100))
        except Exception:
            return 100

    # ---------- 黑名单 ----------
    def is_blacklisted(self, name):
        return str(name) in self.blacklist

    def blacklist_plugin(self, name, reason=""):
        with self._lock:
            self.blacklist[str(name)] = {
                "reason": str(reason)[:200],
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.plugins.pop(str(name), None)
            save_blacklist(self.blacklist, self.blacklist_path)
            # 同步摘掉 tool_caller 白名单，防止再被调用
            self._unregister_tool(name)

    # ---------- tool_caller 白名单 ----------
    def _register_tool(self, manifest):
        key = PLUGIN_PREFIX + manifest["name"]
        if self.tool_caller is None:
            try:
                import tool_caller as _tc
                self.tool_caller = _tc
            except Exception:
                return
        try:
            if not hasattr(self.tool_caller, "DYNAMIC_ORGANS"):
                self.tool_caller.DYNAMIC_ORGANS = {}
            # 关键：白名单里挂的不是插件函数，而是「绞杀通道」
            self.tool_caller.DYNAMIC_ORGANS[key] = {
                "func": lambda q="": self.run(manifest["name"], q),
                "path": manifest["entry_path"],
                "func_name": manifest["function"],
                "plugin": True,
                "builtin": False,
            }
            names = getattr(self.tool_caller, "PLUGIN_TOOLS", None)
            if not isinstance(names, list):
                names = []
            if key not in names:
                names.append(key)
            self.tool_caller.PLUGIN_TOOLS = names
        except Exception as e:
            self.log("注册白名单失败（插件仍可直接经 mgr.run 调用）: %s" % e)

    def _unregister_tool(self, name):
        try:
            if self.tool_caller is None:
                import tool_caller as _tc
                self.tool_caller = _tc
            self.tool_caller.DYNAMIC_ORGANS.pop(PLUGIN_PREFIX + str(name), None)
            names = getattr(self.tool_caller, "PLUGIN_TOOLS", None)
            if isinstance(names, list) and (PLUGIN_PREFIX + str(name)) in names:
                names.remove(PLUGIN_PREFIX + str(name))
        except Exception:
            pass

    # ---------- 扫描 / 审计 / 挂载 ----------
    def load_plugin_dir(self, plugin_dir):
        """完整生命周期：解析清单 -> AST 审计 -> 注册。返回 (ok, name, reason)。"""
        try:
            manifest = parse_manifest(plugin_dir)
        except PluginError as e:
            return False, os.path.basename(plugin_dir), str(e)
        except Exception as e:
            return False, os.path.basename(plugin_dir), "%s: %s" % (type(e).__name__, e)
        name = manifest["name"]

        if self.is_blacklisted(name):
            return False, name, "已被永久拉黑（%s）" % (
                (self.blacklist.get(name) or {}).get("reason", "历史崩溃"))
        with self._lock:
            if name in self.plugins:
                return True, name, "已挂载，跳过"

        try:
            with open(manifest["entry_path"], "rb") as f:
                raw = f.read(MAX_SOURCE_BYTES + 1)
            source = raw.decode("utf-8", "replace")
        except Exception as e:
            return False, name, "入口文件读取失败: %s" % e

        audit = audit_source(source, manifest["capabilities"])
        if not audit.ok:
            self.log("免疫审计拒绝 %s -> %s" % (name, audit.reason))
            return False, name, audit.reason

        manifest["digest"] = plugin_digest(manifest)
        manifest["loaded_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self.plugins[name] = manifest
        self._register_tool(manifest)
        self.log("已挂载插件 %s v%s -> %s%s（能力: %s）" % (
            name, manifest["version"], PLUGIN_PREFIX, name,
            ",".join(manifest["capabilities"]) or "无"))
        return True, name, "ok"

    def scan(self, round_no=None):
        """热更新扫描：对比「清单+入口」哈希，发现新增/更新自动挂载。

        返回 {"added": [...], "updated": [...], "rejected": [(name, reason)], ...}
        任何异常都在内部消化，绝不抛给主循环。
        """
        out = {"added": [], "updated": [], "rejected": [], "removed": [],
               "scanned": 0, "round": round_no}
        try:
            if round_no is not None:
                self.last_scan_round = int(round_no)
            self.scan_count += 1
            if not os.path.isdir(self.plugins_dir):
                return out
            seen = set()
            for entry in sorted(os.listdir(self.plugins_dir)):
                if entry.startswith(".") or entry.startswith("_"):
                    continue
                pdir = os.path.join(self.plugins_dir, entry)
                if not os.path.isdir(pdir):
                    continue
                if not os.path.isfile(os.path.join(pdir, "manifest.json")):
                    continue
                out["scanned"] += 1
                try:
                    manifest = parse_manifest(pdir)
                except PluginError as e:
                    out["rejected"].append((entry, str(e)))
                    continue
                name = manifest["name"]
                seen.add(name)
                if self.is_blacklisted(name):
                    out["rejected"].append((name, "已拉黑"))
                    continue
                current = self.plugins.get(name)
                digest = plugin_digest(manifest)
                if current and current.get("digest") == digest:
                    continue          # 无变化
                ok, _, reason = self.load_plugin_dir(pdir)
                if not ok:
                    out["rejected"].append((name, reason))
                    continue
                if current:
                    out["updated"].append(name)
                    self.log("热更新：插件 %s 已重新挂载" % name)
                else:
                    out["added"].append(name)
                    self.log("热更新：发现新插件 %s，已自动挂载" % name)
            # 目录被删 -> 卸载（不拉黑，只是摘掉白名单）
            for name in list(self.plugins.keys()):
                if name not in seen:
                    self.plugins.pop(name, None)
                    self._unregister_tool(name)
                    out["removed"].append(name)
                    self.log("插件 %s 的目录已消失，已卸载" % name)
        except Exception as e:
            self.log("扫描异常（已隔离）: %s: %s" % (type(e).__name__, e))
        return out

    def should_scan(self, round_no, every=50):
        """每 N 轮心跳扫描一次（白皮书：每 50 轮）。"""
        try:
            r = int(round_no)
        except (TypeError, ValueError):
            return False
        if r <= 0:
            return False
        return r % int(every) == 0 and r != self.last_scan_round

    def list_plugins(self):
        return {n: {"version": m.get("version"), "capabilities": m.get("capabilities"),
                    "entry": m.get("entry"), "loaded_at": m.get("loaded_at")}
                for n, m in sorted(self.plugins.items())}

    # ---------- 执行（物理绞杀） ----------
    def bind_hormone_registry(self, registry):
        """V9.5：把动态激素注册表交给管理器（插件申请在此落库）。"""
        self.hormone_registry = registry

    def _apply_hormone_requests(self, plugin_name, requests, capabilities):
        """在**宿主主进程**里把插件申请的激素落库。返回已合成的激素名列表。"""
        out = []
        reg = getattr(self, "hormone_registry", None)
        if reg is None or not requests:
            return out
        try:
            # 出口再校验一次能力白名单：子进程的 ctx 可能被绕过，
            # 但 parent 这里的 manifest 能力是可信的事实源。
            import hormone_registry as hr
            hr.check_chemical_permission(capabilities, plugin_name, "注入激素")
        except Exception as e:
            self.log("插件 %s 的激素申请被拒绝（%s）" % (plugin_name, e))
            return out
        for req in requests[:MAX_HORMONE_REQUESTS]:
            try:
                res = reg.synthesize(
                    req.get("name"), value=req.get("value"),
                    biological_meaning=req.get("biological_meaning", ""),
                    decay_rate=(req.get("decay_rate")
                                if req.get("decay_rate") is not None else 0.05),
                    temperature=req.get("temperature"),
                    priority=req.get("priority", 0),
                    source="plugin:%s" % plugin_name)
                out.append(res["hormone"]["name"])
            except Exception as e:
                self.log("插件 %s 注入激素失败: %s: %s"
                         % (plugin_name, type(e).__name__, e))
        return out

    def run(self, name, query="", timeout=None):
        """在子进程里运行插件，返回 dict（永不抛异常）。"""
        timeout = int(timeout or self.timeout)
        name = str(name or "")
        res = {"ok": False, "plugin": name, "result": "", "error": "",
               "timed_out": False, "killed": False, "cortisol": None, "elapsed": 0.0,
               "hormones": []}
        with self._lock:
            manifest = self.plugins.get(name)
        if manifest is None:
            res["error"] = ("插件 %r 已被拉黑，拒绝执行" % name
                            if self.is_blacklisted(name) else "插件 %r 未挂载" % name)
            return res
        if self.is_blacklisted(name):
            res["error"] = "插件 %r 已被拉黑，拒绝执行" % name
            return res

        ctx = PluginContext(name, manifest.get("capabilities") or [],
                            self._endo, self._vitality())
        payload = dict(manifest)
        try:
            raw = _run_in_subprocess(payload, str(query or ""), ctx.to_dict(), timeout)
        except Exception as e:
            raw = {"ok": False, "result": "", "error": "%s: %s" % (type(e).__name__, e),
                   "timed_out": False, "killed": False, "elapsed": 0.0}
        res.update({k: raw.get(k) for k in ("ok", "result", "error", "timed_out",
                                            "killed", "elapsed")})

        # ---- V9.5：插件申请的动态激素由宿主统一落库（超时/崩溃的插件不作数）----
        if res.get("ok"):
            try:
                res["hormones"] = self._apply_hormone_requests(
                    name, raw.get("hormones") or [], manifest.get("capabilities") or [])
            except Exception as e:
                self.log("激素申请处理异常（已隔离）: %s" % e)
                res["hormones"] = []

        if raw.get("timed_out"):
            # ---- 超时：物理强杀 + 永久拉黑 + 皮质醇 +0.1 ----
            self.kill_count += 1
            res["cortisol"] = self._bump_cortisol(0.1)
            self.blacklist_plugin(name, "执行超时 %ds（死循环/阻塞），已物理强杀" % timeout)
            self.log("☠ 插件 %s 超时 %ds 已物理绞杀并永久拉黑（皮质醇 %.2f）"
                     % (name, timeout, res["cortisol"] or 0.0))
            res["ok"] = False
            res["result"] = ""
        elif not raw.get("ok"):
            self.log("插件 %s 执行失败（已隔离，主循环不受影响）: %s"
                     % (name, res.get("error", "")[:160]))
        # ---- 输出强制截断 ----
        res["result"] = _truncate(res.get("result", ""))
        return res

    def tool_entry(self, name):
        return self.tool_caller.DYNAMIC_ORGANS.get(PLUGIN_PREFIX + name) \
            if self.tool_caller else None


def _truncate(text):
    """白皮书：强制截断至 text[:500]。"""
    try:
        s = text if isinstance(text, str) else str(text)
    except Exception:
        return ""
    return s[:MAX_OUTPUT_CHARS]


# ============================================
# 八、进程级单例（main.py 与测试共用）
# ============================================
_MANAGER = None
_MANAGER_LOCK = threading.Lock()


def get_manager(plugins_dir=None, endo=None, tool_caller=None, **kw):
    """获取全局插件管理器（首次调用时创建；后续可 update endo 绑定）。"""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = PluginManager(plugins_dir=plugins_dir, tool_caller=tool_caller,
                                     endo=endo, **kw)
        else:
            if plugins_dir:
                _MANAGER.plugins_dir = os.path.abspath(plugins_dir)
            if endo is not None:
                _MANAGER.bind_endo(endo)
            if tool_caller is not None:
                _MANAGER.tool_caller = tool_caller
        return _MANAGER


def reset_manager():
    """仅供测试：清空单例与黑名单（不删除磁盘文件以外的任何东西）。"""
    global _MANAGER
    with _MANAGER_LOCK:
        _MANAGER = None
    shutdown_executor()
