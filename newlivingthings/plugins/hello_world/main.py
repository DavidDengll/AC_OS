# -*- coding: utf-8 -*-
"""hello_world —— V9.4 插件系统示例（最小契约）

契约：def run(ctx, query: str) -> str
  - ctx 是只读上下文，只能读生理数值，不能联网（未声明 network）。
  - 返回值会被主进程强制截断至 500 字符。
"""
import json


def run(ctx, query):
    state = json.dumps({"D": round(ctx.get_dopamine(), 3),
                        "vitality": ctx.get_vitality()}, ensure_ascii=False)
    return "Hello from hello_world! 熵灵你好，我是第一个插件。query=%s state=%s" % (
        str(query or "")[:50], state)
