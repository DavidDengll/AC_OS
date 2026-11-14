# hormone_registry.py
# -*- coding: utf-8 -*-
"""hormone_registry.py -- AC OS V9.5 动态激素合成与内分泌腺体进化

白皮书：HORMONE_SYNTHESIS_WHITEPAPER.md

最高铁律：**动态扩张，但绝不越界**。

  1. 动态注册：name / current_value / baseline / decay_rate / biological_meaning
     数值一律强制 clamp(0.0, 1.0)
  2. 【防爆红线】最多同时存在 5 种动态激素，超出强制淘汰（浓度最低 -> 最旧）
  3. 【防爆红线】Prompt 注入总字数强制截断至 200
  4. 【权限隔离】插件注入激素必须持有 chemical 能力，否则拦截
  5. 【劫持仲裁】多种激素同时重写 temperature 时按优先级仲裁，绝不允许乱序覆盖

设计要点：
  - 注册是「原子」的：先完成全部校验再落库，失败绝不留下半成品。
  - 所有对外返回都是 dict 副本，调用方改不动注册表内部状态。
  - 任何公开函数都不向主循环抛异常（除显式 raise 的 HormoneError / 权限异常）。
"""

import math
import random
import threading
import time
import unicodedata

# ============================================
# 常量（白皮书硬指标，禁止随意放宽）
# ============================================
MAX_DYNAMIC_HORMONES = 5          # 白皮书：最多同时存在 5 种动态激素
PROMPT_CHAR_BUDGET = 200          # 白皮书：Prompt 注入总字数上限
MODULE_PREFIX = "dynamic_"        # 动态激素在 endo 字典里的键前缀

DEFAULT_DECAY_RATE = 0.05         # 未指定时的每轮自然衰减率
DEFAULT_BASELINE = 0.0
DEFAULT_BIOLOGICAL_MEANING = "未知的动态内分泌腺体"

# 温度劫持的可选区间（与 _KernelBoundedProvider 保持同一物理边界）
TEMP_MIN = 0.0
TEMP_MAX = 2.0

# 超载淘汰时，优先削弱的「替补」顺序：浓度最低的那个带头的
_PROTECTED = ("dopamine", "cortisol", "endorphin")

LOG_PREFIX = "[激素]"


def _log(msg):
    try:
        print("%s %s" % (LOG_PREFIX, msg), flush=True)
    except Exception:
        pass


def clamp01(v, default=0.0):
    """强制 clamp 到 [0.0, 1.0]。非数值 / NaN / inf 一律回落 default。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(f) or math.isinf(f):
        return float(default)
    return max(0.0, min(1.0, f))


def clamp_temp(v, default=0.7):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(f) or math.isinf(f):
        return float(default)
    return max(TEMP_MIN, min(TEMP_MAX, f))


class HormoneError(Exception):
    """激素注册 / 注入过程中的可预期错误。"""


class ChemicalPermissionDenied(PermissionError):
    """插件未声明 chemical 能力，却试图注入激素。"""


# ============================================
# 一、文本清洗（插件名称 / 释义是外部输入，必须消毒）
# ============================================
_CONTROL_CATEGORIES = ("Cc", "Cf", "Cs", "Co", "Cn")
# Prompt 结构注入的常见伪装：换行、分隔符、角色标签
_SEPARATORS = "：:，｜|/=~>"


def sanitize_text(text, limit):
    """把外部文本清理成「只能是一段话」的样子。

    - 去掉控制字符 / 零宽字符（\\n \\r \\t 全部压成空格，防止伪造新的一行注入）
    - 折叠连续空白，截到 limit 个字符
    - 绝不改变正常中文名（如「孤独素」「狂喜素」原样保留）
    """
    s = str(text or "")
    out = []
    for ch in s:
        if ch in ("\n", "\r", "\t", "\v", "\f"):
            out.append(" ")
            continue
        try:
            if unicodedata.category(ch) in _CONTROL_CATEGORIES:
                continue
        except Exception:
            pass
        out.append(ch)
    cleaned = " ".join("".join(out).split())
    return cleaned[:max(1, int(limit))]


def normalize_name(name):
    """激素名归一化（去空白/全角），用于去重比较。"""
    return "".join(str(name or "").split()).lower()


def module_key(name):
    """激素名 -> endo 字典中的模块键（只允许安全字符，防键名注入）。"""
    raw = str(name or "")
    buf = []
    for ch in raw:
        if ch.isalnum() or ch in "_-":
            buf.append(ch)
        else:
            buf.append("_")
    key = "".join(buf).strip("_") or "hormone"
    return MODULE_PREFIX + key


def _is_numeric_str(v):
    """temperature / decay_rate 允许传字符串数字（如 "0.9"）。"""
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


# ============================================
# 二、注册表
# ============================================
class HormoneRegistry(object):
    """动态激素的唯一事实源。

    内部结构（有序字典语义，Python 3.7+ dict 保序）：
        name -> {
            "name", "current_value", "baseline", "decay_rate",
            "biological_meaning", "temperature", "priority",
            "source", "born_at", "born_seq", "age"
        }
    """

    def __init__(self, max_hormones=MAX_DYNAMIC_HORMONES,
                 prompt_budget=PROMPT_CHAR_BUDGET, log=None, endo=None):
        self.max_hormones = int(max_hormones)
        self.prompt_budget = int(prompt_budget)
        self.log = log or _log
        self._endo = endo            # 只读视角：允许在超载时削弱经典激素
        self._hormones = {}
        self._lock = threading.RLock()
        self._seq = 0
        self.evictions = []          # 淘汰日志（最近在后）

    # ---------- 内部工具 ----------
    def _next_seq(self):
        self._seq += 1
        return self._seq

    def _validate(self, name, temperature, priority, decay_rate):
        clean = sanitize_text(name, 24)
        if not clean:
            raise HormoneError("激素名不能为空")
        if temperature is not None and not (isinstance(temperature, (int, float))
                                            or _is_numeric_str(temperature)):
            raise HormoneError("temperature 必须是数值或 None")
        try:
            pr = int(priority)
        except (TypeError, ValueError):
            raise HormoneError("priority 必须是整数")
        if pr < 0:
            raise HormoneError("priority 不能为负数")
        try:
            dec = float(decay_rate)
        except (TypeError, ValueError):
            raise HormoneError("decay_rate 必须是数值")
        if math.isnan(dec) or dec < 0 or dec > 1:
            raise HormoneError("decay_rate 必须落在 [0, 1]")
        return clean, pr, dec

    # ---------- 注册 ----------
    def synthesize(self, name, value=None, baseline=DEFAULT_BASELINE,
                   decay_rate=DEFAULT_DECAY_RATE, biological_meaning="",
                   temperature=None, priority=0, source="internal", log=True):
        """合成一种动态激素。

        返回值: {"ok": True, "created": bool, "evicted": [names], "hormone": dict}
        失败时抛 HormoneError（调用方负责降级），绝不留下半成品。

        重复合成同名激素 -> 刷新浓度（不新建、不占用名额、不参与淘汰）。
        """
        clean, pr, dec = self._validate(name, temperature, priority, decay_rate)
        valve = None if temperature is None else clamp_temp(temperature, 0.7)
        mean = sanitize_text(biological_meaning, 60) or DEFAULT_BIOLOGICAL_MEANING
        base = clamp01(baseline, DEFAULT_BASELINE)
        cur = clamp01(value, base) if value is not None else base

        with self._lock:
            key = normalize_name(clean)
            exist = None
            for k, h in self._hormones.items():
                if normalize_name(h["name"]) == key:
                    exist = h
                    break
            if exist is not None:
                # 同名 -> 刷新（不占新名额）
                exist["current_value"] = cur
                exist["baseline"] = base
                exist["decay_rate"] = dec
                exist["biological_meaning"] = mean
                exist["temperature"] = valve
                exist["priority"] = pr
                exist["source"] = source
                exist["age"] = 0
                self._sync_endo()
                return {"ok": True, "created": False, "evicted": [],
                        "hormone": self._copy(exist)}

            evicted = self._make_room()
            seq = self._next_seq()
            h = {
                "name": clean, "current_value": cur, "baseline": base,
                "decay_rate": dec, "biological_meaning": mean,
                "temperature": valve, "priority": pr, "source": source,
                "born_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "born_seq": seq, "age": 0,
            }
            self._hormones[clean] = h
            if log:
                self.log("合成新激素「%s」=%.3f（来源: %s，温度劫持: %s，剩余名额 %d/%d）"
                         % (clean, cur, source,
                            "-" if valve is None else "%.2f" % valve,
                            len(self._hormones), self.max_hormones))
            self._sync_endo()
            return {"ok": True, "created": True, "evicted": evicted,
                    "hormone": self._copy(h)}

    def _eviction_key(self, h):
        """淘汰排序：浓度最低者优先；浓度相同时最旧（born_seq 最小）先走。"""
        return (round(float(h["current_value"]), 6), int(h["born_seq"]))

    def _make_room(self):
        """腾出一个名额。返回被淘汰的激素名列表（可能为空）。"""
        evicted = []
        while len(self._hormones) >= self.max_hormones:
            victim = min(self._hormones.values(), key=self._eviction_key)
            del self._hormones[victim["name"]]
            evicted.append(victim["name"])
            self.evictions.append({"name": victim["name"],
                                   "value": round(float(victim["current_value"]), 6),
                                   "age": int(victim["age"]),
                                   "at": time.strftime("%Y-%m-%d %H:%M:%S")})
            if len(self.evictions) > 20:
                self.evictions = self.evictions[-20:]
            self.log("名额已满（%d），淘汰最弱激素「%s」（浓度 %.3f，存活 %d 轮）"
                     % (self.max_hormones, victim["name"],
                        float(victim["current_value"]), int(victim["age"])))
        if evicted:
            # 淘汰后立刻同步，旧键不会残留在 endo 里
            self._sync_endo()
        return evicted

    # ---------- 代谢 ----------
    def decay(self, rounds=1):
        """每轮心跳：按 decay_rate 向 baseline 衰减，并强制 clamp。

        返回存活激素的 {name: current_value}。
        """
        try:
            rounds = max(0, int(rounds))
        except (TypeError, ValueError):
            rounds = 1
        with self._lock:
            for h in self._hormones.values():
                rate = clamp01(h["decay_rate"], DEFAULT_DECAY_RATE)
                for _ in range(rounds):
                    cur = float(h["current_value"])
                    h["current_value"] = clamp01(cur + (h["baseline"] - cur) * rate)
                h["age"] = int(h["age"]) + rounds
            self._sync_endo()
            # 返回展示副本（内部状态保持全精度，不做 round，避免多轮累积误差）
            return {n: self._copy(h)["current_value"] for n, h in self._hormones.items()}

    # ---------- 查询 ----------
    def _copy(self, h):
        out = dict(h)
        out["current_value"] = round(float(out["current_value"]), 6)
        out["baseline"] = round(float(out["baseline"]), 6)
        return out

    def get(self, name):
        with self._lock:
            key = normalize_name(name)
            for h in self._hormones.values():
                if normalize_name(h["name"]) == key:
                    return self._copy(h)
        return None

    def active(self):
        """当前所有动态激素（副本，按合成顺序）。"""
        with self._lock:
            return [self._copy(h) for h in self._hormones.values()]

    def value_of(self, name):
        h = self.get(name)
        return None if h is None else h["current_value"]

    def count(self):
        with self._lock:
            return len(self._hormones)

    def clear(self):
        with self._lock:
            self._hormones.clear()
            self._sync_endo()

    # ---------- endo 同步（数值镜像，供温度仲裁与插件读值） ----------
    def _sync_endo(self):
        """把动态激素浓度镜像进 endo 字典（键名 dynamic_xxx）。

        只做「写镜像 + 清理失效键」，绝不改动经典激素的数值。
        """
        endo = self._endo
        if not isinstance(endo, dict):
            return
        try:
            live = {module_key(n): float(h["current_value"])
                    for n, h in self._hormones.items()}
            for k in [k for k in list(endo.keys())
                      if isinstance(k, str) and k.startswith(MODULE_PREFIX)]:
                if k not in live:
                    endo.pop(k, None)
            endo.update(live)
        except Exception:
            pass

    # ---------- Prompt 注入 ----------
    def build_prompt_block(self, budget=None):
        """把活跃激素注入 System Prompt，总字数硬截断到 budget（默认 200）。

        返回 "" 表示没有活跃激素（调用方无需拼接）。
        """
        budget = int(budget or self.prompt_budget)
        items = self.active()
        if not items:
            return ""
        prefix = "【动态内分泌】"
        room = budget - len(prefix)
        if room <= 0:
            return prefix[:budget]
        parts = []
        used = 0
        for h in items:
            remain = room - used
            if remain <= 6:
                break
            # 释义按剩余额度动态收缩，绝不越界
            mean = h["biological_meaning"]
            seg_head = "%s=%.2f(" % (h["name"], h["current_value"])
            seg_tail = ")"
            mean_room = max(0, remain - len(seg_head) - len(seg_tail))
            if mean_room < 2:
                break
            seg = seg_head + mean[:mean_room] + seg_tail
            if len(seg) > remain:
                seg = seg[:remain]
            parts.append(seg)
            used += len(seg) + 1          # +1 为分隔符
            if len(parts) >= self.max_hormones:
                break
        block = prefix + "".join(parts)
        return block[:budget]

    # ---------- 温度劫持仲裁 ----------
    def arbitrate_temperature(self, baseline_temp=0.7):
        """多个激素同时想重写 temperature 时，按优先级仲裁。

        规则（绝不允许乱序覆盖）：
          1. 只在持有有效 temperature 的动态激素之间比较；
          2. priority 数值大者胜（高压类激素应声明最高优先级）；
          3. priority 相同 -> 浓度高者胜；
          4. 仍然相同 -> 先合成的（born_seq 小）胜，保证结果确定。
        没有激素要求重写温度时返回 None（交还 V6.6 经典规则）。

        返回 (temperature|None, reason)
        """
        candidates = [h for h in self.active() if h.get("temperature") is not None]
        if not candidates:
            return None, ""
        candidates.sort(key=lambda h: (-int(h["priority"]),
                                       -float(h["current_value"]),
                                       int(h["born_seq"])))
        winner = candidates[0]
        temp = clamp_temp(winner["temperature"], baseline_temp)
        reason = "激素仲裁: %s(pri=%d, 浓度 %.2f)" % (
            winner["name"], int(winner["priority"]), float(winner["current_value"]))
        if len(candidates) > 1:
            losers = ", ".join("%s(pri=%d)" % (h["name"], int(h["priority"]))
                               for h in candidates[1:])
            reason += " 压制 [%s]" % losers
        return temp, reason


# ============================================
# 三、内部极端事件触发（连续挫败 -> 自主合成）
# ============================================
# 事件名 -> (激素名, 基础浓度, decay_rate, 释义, 温度劫持, 优先级)
INTERNAL_HORMONES = {
    "despair": ("绝望素", 0.6, 0.08, "连续挫败后的瘫痪感", None, 0),
    "berserk": ("狂暴素", 0.5, 0.10, "受挫后的攻击性冲动", 1.0, 70),
    "lonely": ("孤独素", 0.45, 0.06, "长期无人应答的空洞", None, 0),
    "euphoria": ("狂喜素", 0.5, 0.12, "意外成功后的亢奋", 0.95, 50),
}

SYNTHESIS_VITALITY_COST = 10     # 白皮书：自主合成消耗 10 点 vitality
FAIL_STREAK_TRIGGER = 3          # 白皮书：连续 3 次挫败触发


def synthesize_for_event(registry, event, vitality=100, source="internal",
                         spend=None, log=None):
    """内部极端事件触发的自主合成。

    spend: 可选的扣血回调 spend(cost: int)，成功合成后调用。
    返回 {"ok": bool, "reason": str, ...}
    """
    say = log or _log
    if registry is None:
        return {"ok": False, "reason": "注册表未初始化"}
    spec = INTERNAL_HORMONES.get(str(event or "").lower())
    if spec is None:
        return {"ok": False, "reason": "未知事件: %s" % event}
    try:
        if int(vitality) <= SYNTHESIS_VITALITY_COST:
            say("生命值不足（%s <= %d），拒绝合成激素" % (vitality, SYNTHESIS_VITALITY_COST))
            return {"ok": False, "reason": "生命值不足"}
    except (TypeError, ValueError):
        return {"ok": False, "reason": "生命值非法"}
    name, val, dec, mean, temp, pri = spec
    try:
        res = registry.synthesize(name, value=val, decay_rate=dec,
                                  biological_meaning=mean, temperature=temp,
                                  priority=pri, source=source)
    except HormoneError as e:
        return {"ok": False, "reason": str(e)}
    if callable(spend):
        try:
            spend(SYNTHESIS_VITALITY_COST)
        except Exception:
            pass
    say("自主合成激素「%s」完成（-%.0f 生命值）" % (name, SYNTHESIS_VITALITY_COST))
    res["reason"] = "ok"
    return res


# ============================================
# 四、权限闸门：插件必须先声明 chemical 能力
# ============================================
def check_chemical_permission(capabilities, plugin_name="?", action="注入激素"):
    """校验插件能力白名单。未声明 chemical -> 抛 ChemicalPermissionDenied。"""
    caps = {str(c).strip().lower() for c in (capabilities or [])}
    if "chemical" not in caps:
        raise ChemicalPermissionDenied(
            "插件 %r 未声明 chemical 能力，禁止%s" % (plugin_name, action))
    return True


# ============================================
# 五、进程级单例
# ============================================
_REGISTRY = None
_REGISTRY_LOCK = threading.Lock()


def get_registry(endo=None, **kw):
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = HormoneRegistry(endo=endo, **kw)
        elif endo is not None:
            _REGISTRY._endo = endo
        return _REGISTRY


def reset_registry():
    """仅供测试：丢弃单例（不触碰任何磁盘状态）。"""
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = None
