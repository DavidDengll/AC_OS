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


def build_command(task):
    """组装 docker run 命令。Windows 下路径需要转成 Docker 可识别的形式。"""
    exe = shutil.which("docker") or "docker"
    cfg = os.path.abspath(ZEPTO_CONFIG)
    # Docker Desktop 接受 Windows 绝对路径挂载
    mount = cfg + ":/root/.zeptoclaw"
    return [
        exe, "run", "--rm",
        "-e", "RUST_LOG=error",
        "-v", mount,
        "--entrypoint", "zeptoclaw",
        ZEPTO_IMAGE,
        "agent", "--no-stream",
        "--mode", ZEPTO_MODE,
        "-m", task,
    ]


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
        result = out if ok else (err or out or "ZeptoClaw 返回空结果")
        return ok, result, {"elapsed": elapsed, "returncode": proc.returncode,
                            "cmd": " ".join(cmd[:8]) + " ..."}
    except subprocess.TimeoutExpired:
        return False, "ZeptoClaw 执行超时（%d 秒）" % ZEPTO_TIMEOUT, {"elapsed": ZEPTO_TIMEOUT}
    except Exception as e:
        return False, "启动 ZeptoClaw 失败: %s" % e, {"elapsed": round(time.time() - started, 2)}


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
    record = {"event": "task_done", "task": task, "ok": ok,
              "result": result[:800], "elapsed": meta.get("elapsed")}
    _log(record)

    print("[bridge] 执行%s，耗时 %ss" % ("成功" if ok else "失败", meta.get("elapsed")), flush=True)
    print("[bridge] 结果: %s" % result[:400], flush=True)
    print("=" * 60, flush=True)

    return jsonify({"ok": ok, "task": task, "result": result, "meta": meta})


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
