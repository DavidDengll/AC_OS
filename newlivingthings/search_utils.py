# search_utils.py
# -*- coding: utf-8 -*-
"""
search_utils.py —— 统一搜索适配器（SELF_REFACTOR 白皮书 第二节）

提供 web_search(query) -> str，并焊死三条防呆铁律：
  1. 致歉信过滤：命中 I'm sorry / network error / 无法访问 等 -> 返回空串
  2. 长度截断：强制截断至最多 20 行（防上下文爆炸）
  3. 前置校验：模块名必须是合法 Python 标识符，普通英文单词（Would 等）不得误判
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

MAX_LINES = 20

# 致歉/失败标记：命中即视为无效搜索结果
APOLOGY_MARKERS = (
    "i'm sorry", "i am sorry", "sorry",
    "network error", "couldn't", "could not", "can't use", "cannot use",
    "unable to", "not able to", "api key", "unauthorized", "rate limit",
    "无法访问", "抱歉", "搜索失败", "网络错误", "无权访问",
)

# 合法的 LoRA 模块名特征：必须是已知的投影层命名
_KNOWN_MODULES = (
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
    "query_key_value", "dense", "dense_h_to_4h", "dense_4h_to_h",
    "fc1", "fc2", "w1", "w2", "w3", "Wqkv", "Wo",
)


def _log(msg):
    try:
        print("[搜索] %s" % msg, flush=True)
    except Exception:
        pass


def is_apology(text):
    """判断文本是否是搜索工具的致歉/失败信息（而非真实搜索结果）。"""
    try:
        t = str(text or "").strip()
        if not t:
            return True
        low = t.lower()
        has_marker = any(mk in low for mk in APOLOGY_MARKERS)
        # 若同时出现明确的模块/配置线索，则不算致歉
        has_module_hint = ("target_modules" in low or "_proj" in low)
        if has_marker and not has_module_hint:
            return True
        # 注意：不能"只要短就判无效"—— 合法证据常常很短
        # （例如 "SyntaxError: invalid syntax" 仅 29 字符），会被误杀。
        return False
    except Exception:
        return True


def truncate_lines(text, max_lines=MAX_LINES):
    """强制截断至 max_lines 行。"""
    try:
        lines = str(text or "").splitlines()
        return "\n".join(lines[:max(1, int(max_lines))])
    except Exception:
        return ""


def is_valid_identifier(name):
    """前置校验：必须是合法 Python 标识符，且属于已知 LoRA 模块命名。"""
    try:
        s = str(name or "").strip()
        if not s or len(s) > 64:
            return False
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s):
            return False
        return s in _KNOWN_MODULES
    except Exception:
        return False


def extract_modules(text):
    """从文本中提取合法模块名（标识符 + 白名单双重校验）。"""
    try:
        blob = str(text or "")
        found = []
        for m in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", blob):
            if is_valid_identifier(m) and m not in found:
                found.append(m)
        return found
    except Exception:
        return []


def web_search(query, bridge=None):
    """统一搜索接口。返回清洗后的文本（≤20 行）；无效则返回空串。"""
    try:
        if bridge is None:
            import tool_caller
            bridge = tool_caller.call_bridge
        _log("发起搜索：%s" % query)
        res = bridge(str(query), timeout=120) or {}
        if isinstance(res, dict):
            if not res.get("ok"):
                _log("搜索失败：%s" % str(res.get("error"))[:120])
                return ""
            raw = str(res.get("result") or "")
        else:
            raw = str(res or "")

        if is_apology(raw):
            _log("命中致歉信过滤，丢弃结果")
            return ""
        cut = truncate_lines(raw, MAX_LINES)
        if cut != raw:
            _log("结果已截断至 %d 行" % MAX_LINES)
        return cut
    except Exception as e:
        _log("搜索异常：%s" % e)
        return ""
