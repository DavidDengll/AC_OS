# host_agent_bridge.py
# -*- coding: utf-8 -*-
"""
host_agent_bridge.py —— 熵灵的"手脚"（宿主机侧 HTTP 桥）

架构：
    熵灵（容器内） --POST /api/exec--> host_agent_bridge.py（宿主机）
                                          |
                                          v
                              docker run ghcr.io/qhkm/zeptoclaw agent -m "任务"
                                          |
                                          v
                              ZeptoClaw 内置工具（web_search/shell/git/...）
                                          |
                                          v
    熵灵（容器内） <--------- JSON 结果 ------

启动：
    python host_agent_bridge.py
    默认监听 0.0.0.0:5555

接口：
    GET  /api/health            健康检查 + 可用性探测
    POST /api/exec              {"task": "..."} -> {"ok": bool, "result": "..."}
    GET  /api/logs?n=50         最近的执行日志
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import datetime

from flask import Flask, request, jsonify

HOST = os.environ.get("AC_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.environ.get("AC_BRIDGE_PORT", "5555"))

# ---- ZeptoClaw 运行参数 ----
ZEPTO_IMAGE = os.environ.get("AC_ZEPTO_IMAGE", "ghcr.io/qhkm/zeptoclaw:latest")
ZEPTO_CONFIG = os.environ.get("AC_ZEPTO_CONFIG", os.path.expanduser("~/.zeptoclaw"))
ZEPTO_TIMEOUT = int(os.environ.get("AC_ZEPTO_TIMEOUT", "300"))
ZEPTO_MODE = os.environ.get("AC_ZEPTO_MODE", "assistant")

# ---- 真实互联网：代理探测 + 域名直连宿主机 ----
# 实测本机没有 7890 代理；GitHub 域名被 hosts 劫持到宿主机 127.0.0.1，
# 而宿主机 443 由 Steam++ 加速器监听。容器内 127.0.0.1 指向自己，
# 因此必须把这些域名解析到宿主机网关，才能经加速器出网。
PROXY_CANDIDATES = [7890, 7891, 1080, 10808, 10809, 8080, 8888, 7897]
_PROXY_PORT = None
_PROXY_CHECKED = False
HOST_GATEWAY_IP = os.environ.get("AC_HOST_GATEWAY_IP", "192.168.65.254")
ROUTE_VIA_HOST = [
    "github.com", "api.github.com", "raw.githubusercontent.com",
    "gist.github.com", "codeload.github.com", "objects.githubusercontent.com",
]
WEB_MAX_CHARS = int(os.environ.get("AC_WEB_MAX_CHARS", "500"))

app = Flask(__name__)

_LOCK = threading.Lock()
_LOG = []          # 最近执行记录（内存环形数组）
_LOG_MAX = 200


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(entry):
    entry = dict(entry)
    entry.setdefault("time", _now())
    with _LOCK:
        _LOG.append(entry)
        del _LOG[:-_LOG_MAX]
    print("[bridge] " + json.dumps(entry, ensure_ascii=False)[:500], flush=True)


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][A-B]|\r")


def strip_ansi(text):
    """去掉 ANSI 转义与进度条刷屏."""
    if not text:
        return ""
    text = ANSI_RE.sub("", text)
    # 进度条残留：把连续的 "Thinking..." 折叠掉
    text = re.sub(r"(Thinking\.\.\.\s*)+", "", text)
    return text.strip()


HTML_TAG_RE = re.compile(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
BLANK_RE = re.compile(r"\n{3,}")


def sanitize_web_output(text, limit=None):
    """把 ZeptoClaw 抓回来的内容净化成纯文本（防小模型爆炸）。

    - 去掉 <script>/<style> 与所有标签
    - 反转义 HTML 实体
    - 压掉多余空白，截断到 limit 字符（默认 500，约 200 token）
    """
    limit = limit or WEB_MAX_CHARS
    if not text:
        return ""
    t = strip_ansi(str(text))
    had_html = bool(re.search(r"<\w+[^>]*>", t))
    if had_html:
        t = HTML_TAG_RE.sub(" ", t)
        t = TAG_RE.sub(" ", t)
        try:
            import html as _html
            t = _html.unescape(t)
        except Exception:
            pass
    # 去掉日志噪声行（RUST_LOG 的错误堆栈对 0.8B 毫无意义）
    lines = []
    for ln in t.splitlines():
        s = ln.strip()
        if not s:
            continue
        if re.match(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s+(ERROR|WARN|INFO|DEBUG)", s):
            continue
        lines.append(s)
    t = "\n".join(lines)
    t = re.sub(r"[ \t]+", " ", t)
    t = BLANK_RE.sub("\n\n", t).strip()
    if len(t) > limit:
        t = t[:limit].rstrip() + "…"
    return t


def summarize_json(raw, limit=None):
    """把 GitHub / Codeforces 的 JSON 结果提炼成人能读的中文摘要。

    0.8B 小模型读不懂原始 JSON，这里先替它归纳，再交给它"感受"。
    """
    limit = limit or WEB_MAX_CHARS
    try:
        data = json.loads(raw)
    except Exception:
        return None

    lines = []
    # GitHub 搜索接口
    items = data.get("items")
    if isinstance(items, list):
        for i, it in enumerate(items[:5], 1):
            name = it.get("full_name") or it.get("name") or "?"
            stars = it.get("stargazers_count")
            desc = (it.get("description") or "").strip().replace("\n", " ")[:80]
            parts = ["%d. %s" % (i, name)]
            if stars is not None:
                parts.append("★%s" % stars)
            if desc:
                parts.append(desc)
            lines.append(" | ".join(parts))
        if lines:
            head = "GitHub 热门项目 Top%d：\n" % len(lines)
            return (head + "\n".join(lines))[:limit]

    # Codeforces 比赛列表
    if isinstance(data.get("result"), list) and data.get("status") == "OK":
        contests = data["result"]
        upcoming = [c for c in contests if c.get("phase") == "BEFORE"]
        recent = [c for c in contests if c.get("phase") == "FINISHED"]
        out = []
        if upcoming:
            out.append("即将开始的比赛 %d 场：" % len(upcoming))
            for c in upcoming[:3]:
                out.append("- %s" % c.get("name", "?"))
        if recent:
            out.append("最近结束的比赛：")
            for c in recent[:3]:
                out.append("- %s" % c.get("name", "?"))
        if out:
            return ("\n".join(out))[:limit]

    return None


def docker_ok():
    exe = shutil.which("docker")
    if not exe:
        return False, "docker 不在 PATH 中"
    try:
        r = subprocess.run([exe, "info"], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            return False, "Docker 引擎未就绪"
        return True, "ok"
    except Exception as e:
        return False, str(e)


def detect_proxy():
    """探测宿主机上可用的 HTTP 代理端口（默认猜 7890，失败则扫描常见端口）。"""
    global _PROXY_PORT, _PROXY_CHECKED
    if _PROXY_CHECKED:
        return _PROXY_PORT
    _PROXY_CHECKED = True

    envp = os.environ.get("AC_PROXY_PORT")
    if envp and str(envp).isdigit():
        _PROXY_PORT = int(envp)
        print("[bridge] 使用环境变量指定的代理端口: %d" % _PROXY_PORT, flush=True)
        return _PROXY_PORT

    import socket
    for port in PROXY_CANDIDATES:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.6)
            s.close()
            _PROXY_PORT = port
            print("[bridge] 探测到宿主机代理端口: %d" % port, flush=True)
            return port
        except Exception:
            continue
    _PROXY_PORT = None
    print("[bridge] 未探测到 HTTP 代理端口（无需代理，走域名直连）", flush=True)
    return None


def build_command(task):
    """组装 docker run 命令。Windows 下路径需要转成 Docker 可识别的形式。"""
    exe = shutil.which("docker") or "docker"
    cfg = os.path.abspath(ZEPTO_CONFIG)
    # Docker Desktop 接受 Windows 绝对路径挂载
    mount = cfg + ":/root/.zeptoclaw"

    cmd = [exe, "run", "--rm", "-e", "RUST_LOG=error"]

    # 1) 代理：如果宿主机有可用代理，强制注入到容器
    proxy = detect_proxy()
    if proxy:
        proxy_url = "http://host.docker.internal:%d" % proxy
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            cmd += ["-e", "%s=%s" % (k, proxy_url)]
        cmd += ["-e", "NO_PROXY=localhost,127.0.0.1"]

    # 2) 域名路由：GitHub 系域名指向宿主机网关（经 Steam++ 加速器出网）
    for host in ROUTE_VIA_HOST:
        cmd += ["--add-host", "%s:%s" % (host, HOST_GATEWAY_IP)]

    cmd += ["-v", mount, "--entrypoint", "zeptoclaw", ZEPTO_IMAGE,
            "agent", "--no-stream", "--mode", ZEPTO_MODE, "-m", task]
    return cmd


def run_zeptoclaw(task):
    """执行 ZeptoClaw，返回 (ok, result_text, meta)."""
    cmd = build_command(task)
    started = time.time()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=ZEPTO_TIMEOUT,
                              creationflags=flags)
        out = strip_ansi(proc.stdout.decode("utf-8", "replace"))
        err = strip_ansi(proc.stderr.decode("utf-8", "replace"))
        elapsed = round(time.time() - started, 2)
        ok = proc.returncode == 0 and bool(out)
        raw = out if ok else (err or out or "ZeptoClaw 返回空结果")
        # 净化：绝不把原始 HTML / 日志堆栈直接回传给熵灵
        result = sanitize_web_output(raw)
        return ok, result, {"elapsed": elapsed, "returncode": proc.returncode,
                            "raw_len": len(raw), "clean_len": len(result),
                            "cmd": " ".join(cmd[:8]) + " ..."}
    except subprocess.TimeoutExpired:
        return False, "ZeptoClaw 执行超时（%d 秒）" % ZEPTO_TIMEOUT, {"elapsed": ZEPTO_TIMEOUT}
    except Exception as e:
        return False, "启动 ZeptoClaw 失败: %s" % e, {"elapsed": round(time.time() - started, 2)}


MIRROR_SITES = [
    ("GitHub 热榜（Gitee 镜像）", "https://gitee.com/explore"),
    ("博客园首页", "https://www.cnblogs.com/"),
]


def fetch_mirror(n=1):
    """外网不通时的兜底：抓国内可访问的镜像站正文。"""
    import urllib.request
    results = []
    for name, url in MIRROR_SITES[:n]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 entropy"})
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode("utf-8", "replace")
            clean = sanitize_web_output(raw)
            if clean:
                results.append({"name": name, "url": url, "ok": True, "result": clean})
        except Exception as e:
            results.append({"name": name, "url": url, "ok": False,
                            "result": "抓取失败: %s" % e})
    return results


@app.route("/api/health", methods=["GET"])
def health():
    ok, why = docker_ok()
    return jsonify({"ok": ok, "docker": why, "image": ZEPTO_IMAGE,
                    "config": ZEPTO_CONFIG, "timeout": ZEPTO_TIMEOUT,
                    "mode": ZEPTO_MODE, "time": _now()})


@app.route("/api/exec", methods=["POST"])
def exec_task():
    payload = request.get_json(silent=True) or {}
    task = (payload.get("task") or "").strip()
    if not task:
        return jsonify({"ok": False, "error": "缺少 task 字段"}), 400

    print("=" * 60, flush=True)
    print("[bridge] 收到任务: %s" % task, flush=True)
    _log({"event": "task_received", "task": task})

    ok, result, meta = run_zeptoclaw(task)

    # 外网失败 -> 自动降级到国内镜像站，保证链路不死
    fallback_used = False
    if not ok and payload.get("fallback", True):
        print("[bridge] ZeptoClaw 失败，尝试国内镜像站兜底 ...", flush=True)
        mirrors = fetch_mirror(1)
        for m in mirrors:
            if m.get("ok") and m.get("result"):
                result = "[镜像站:%s] %s" % (m["name"], m["result"])
                ok = True
                fallback_used = True
                meta["fallback_url"] = m["url"]
                break
        if not fallback_used:
            meta["fallback_error"] = mirrors[0].get("result") if mirrors else ""

    record = {"event": "task_done", "task": task, "ok": ok,
              "result": result[:800], "elapsed": meta.get("elapsed"),
              "fallback": fallback_used}
    _log(record)

    print("[bridge] 执行%s，耗时 %ss%s" % ("成功" if ok else "失败", meta.get("elapsed"),
                                       "（镜像兜底）" if fallback_used else ""), flush=True)
    print("[bridge] 结果: %s" % result[:400], flush=True)
    print("=" * 60, flush=True)

    return jsonify({"ok": ok, "task": task, "result": result, "meta": meta,
                    "fallback": fallback_used})


@app.route("/api/fetch", methods=["POST"])
def fetch_url():
    """直接抓取指定 URL 并返回清洗后的正文（供熵灵看真实网页用）。"""
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "缺少 url 字段"}), 400
    limit = int(payload.get("limit") or WEB_MAX_CHARS)
    print("[bridge] 抓取网页: %s" % url, flush=True)
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; EntropyACOS/1.0)",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=int(payload.get("timeout") or 30)) as r:
            raw = r.read().decode("utf-8", "replace")
        # JSON 接口先提炼成中文摘要，再交给小模型
        clean = summarize_json(raw, limit=limit) or sanitize_web_output(raw, limit=limit)
        _log({"event": "fetch_done", "url": url, "ok": bool(clean),
              "raw_len": len(raw), "clean_len": len(clean)})
        return jsonify({"ok": bool(clean), "url": url, "result": clean,
                        "raw_len": len(raw)})
    except Exception as e:
        _log({"event": "fetch_done", "url": url, "ok": False, "error": str(e)[:200]})
        return jsonify({"ok": False, "url": url, "error": str(e)[:300]})


@app.route("/api/logs", methods=["GET"])
def logs():
    n = int(request.args.get("n", 50))
    with _LOCK:
        return jsonify({"logs": _LOG[-n:]})


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print("=" * 60)
    print(" AC_OS 宿主机桥接（ZeptoClaw 手套）")
    print(" 监听    : http://%s:%d" % (HOST, PORT))
    print(" 镜像    : %s" % ZEPTO_IMAGE)
    print(" 配置    : %s" % ZEPTO_CONFIG)
    ok, why = docker_ok()
    print(" Docker  : %s (%s)" % ("OK" if ok else "不可用", why))
    print(" 容器内访问地址: http://host.docker.internal:%d/api/exec" % PORT)
    print("=" * 60, flush=True)
    if not ok:
        print("!! 警告：Docker 不可用，/api/exec 会失败。请先启动 Docker Desktop。")
    app.run(host=HOST, port=PORT, threaded=True)
