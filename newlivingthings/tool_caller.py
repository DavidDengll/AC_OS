# tool_caller.py
# -*- coding: utf-8 -*-
"""
tool_caller.py —— 熵灵的"意图 -> 工具"通道

职责：
  1. 从熵灵的回复里识别 [CALL_TOOL] 任务标记
  2. 把任务通过 HTTP POST 发给宿主机的 host_agent_bridge.py
  3. 把 ZeptoClaw 的执行结果交回主循环（存入短期记忆、下一轮打印）

链路：
    熵灵(容器) --[CALL_TOOL]--> tool_caller --> host.docker.internal:5555/api/exec
                                                   --> ZeptoClaw(宿主机) --> 结果
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

# 标记格式：[CALL_TOOL] 任务内容
TOOL_MARKER = "[CALL_TOOL]"
TOOL_RE = re.compile(r"\[CALL_TOOL\]\s*(.+?)(?:\n|$)", re.IGNORECASE)

# 桥接地址（容器内用 host.docker.internal；本机调试可用 127.0.0.1）
BRIDGE_URL = os.environ.get("AC_BRIDGE_URL", "http://host.docker.internal:5555/api/exec")
BRIDGE_TIMEOUT = int(os.environ.get("AC_BRIDGE_TIMEOUT", "300"))

_LOCK = threading.Lock()


def has_tool_call(text):
    return bool(text) and TOOL_MARKER.lower() in text.lower()


def extract_task(text):
    if not text:
        return None
    m = TOOL_RE.search(text)
    if not m:
        return None
    task = m.group(1).strip().strip(chr(34892) + chr(12300) + chr(12301) + chr(34) + chr(39) + chr(96) + " ")
    return task or None


def extract_all_tasks(text, limit=3):
    if not text:
        return []
    out = []
    for m in TOOL_RE.finditer(text):
        t = m.group(1).strip().strip(chr(34892) + chr(12300) + chr(12301) + chr(34) + chr(39) + chr(96) + " ")
        if t:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def strip_marker(text):
    if not text:
        return ""
    cleaned = TOOL_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def call_bridge(task, timeout=None):
    timeout = timeout or BRIDGE_TIMEOUT
    payload = json.dumps({"task": task}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BRIDGE_URL, data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return {
            "ok": bool(data.get("ok")),
            "result": data.get("result", ""),
            "error": "" if data.get("ok") else data.get("error", "工具执行失败"),
            "elapsed": data.get("meta", {}).get("elapsed", round(time.time() - started, 2)),
        }
    except urllib.error.URLError as e:
        return {"ok": False, "result": "",
                "error": "无法连接宿主机桥接(%s): %s" % (BRIDGE_URL, e),
                "elapsed": round(time.time() - started, 2)}
    except Exception as e:
        return {"ok": False, "result": "", "error": "%s: %s" % (type(e).__name__, e),
                "elapsed": round(time.time() - started, 2)}


# 好奇心/未知概念时，熵灵想查什么（按优先级轮换，避免每次都问同一件事）
_TASK_TEMPLATES = [
    "帮我查一下今天的新闻，挑一条最值得说的，用中文一句话总结",
    "搜索一下最近 AI 领域有什么新进展，用中文一句话总结",
    "帮我查一下明天的天气，用中文简短回答",
    "介绍一下{counterparty}这个词是什么意思，用中文一句话回答",
    "搜索一下最新的科技新闻，用中文一句话总结",
]


def build_task_from_context(scene, curiosity=0.0, unknown=False):
    """根据当前场景与情绪，生成一个具体的 [CALL_TOOL] 任务文本。"""
    if unknown and scene:
        subject = str(scene).strip()[:20]
        return "帮我查一下「%s」是什么，用中文一句话回答" % subject
    idx = int(abs(curiosity) * 1000) % len(_TASK_TEMPLATES)
    task = _TASK_TEMPLATES[idx]
    return task.replace("{counterparty}", (str(scene or "")[:12] or "熵灵"))


def health():
    url = BRIDGE_URL.rsplit("/", 2)[0] + "/api/health"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_tools_from_text(text, log=print):
    tasks = extract_all_tasks(text)
    results = []
    for task in tasks:
        log("[工具] 熵灵请求执行: %s" % task)
        res = call_bridge(task)
        res["task"] = task
        if res["ok"]:
            log("[工具] ZeptoClaw 返回 (%ss): %s" % (res["elapsed"], (res["result"] or "")[:200]))
        else:
            log("[工具] 执行失败: %s" % res["error"])
        results.append(res)
    return results


if __name__ == "__main__":
    import sys
    task = " ".join(sys.argv[1:]) or "用一句中文介绍你自己"
    print("桥接地址:", BRIDGE_URL)
    print("健康检查:", json.dumps(health(), ensure_ascii=False))
    print("执行任务:", task)
    print(json.dumps(call_bridge(task), ensure_ascii=False, indent=2))
