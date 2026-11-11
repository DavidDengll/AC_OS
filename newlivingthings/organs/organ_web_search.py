# -*- coding: utf-8 -*-
# BUILTIN  (V9.1.1 预置内置器官：仅此标记允许 import urllib 访问宿主机桥接)
"""organ_web_search.py — V9.1 内置联网器官（必须经宿主机桥接，绝不裸连外网）"""
import json
import urllib.request

BRIDGE_URL = "http://host.docker.internal:5555/api/exec"
TIMEOUT = 10
MAX_CHARS = 500


def search_web(query):
    """经宿主机桥接搜索，返回截断后的文本；失败返回 "网络搜索失败: ..."。"""
    try:
        payload = json.dumps({"task": "搜索" + str(query or "")}, ensure_ascii=False)
        body = payload.encode("utf-8")
        req = urllib.request.Request(
            BRIDGE_URL, data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
        data = json.loads(raw)
        if not data.get("ok"):
            return "网络搜索失败: %s" % str(data.get("error") or "桥接返回失败")[:200]
        text = str(data.get("result") or "").strip()
        if not text:
            return "网络搜索失败: 桥接返回空结果"
        return text[:MAX_CHARS]
    except Exception as e:
        return "网络搜索失败: %s: %s" % (type(e).__name__, e)


def main():
    return search_web("测试")


if __name__ == "__main__":
    print(main())
