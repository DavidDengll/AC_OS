# endocrine_bridge.py
# -*- coding: utf-8 -*-
"""endocrine_bridge.py -- AC OS V9.6 生理↔心理双轨融合（接线与镇痛）

背景（审查者发现的致命断层）：
  旧情绪系统 energy / curiosity / pleasure 一直在跑，而新内分泌 D / C / E
  自启动后就冻结在 0.5 —— 因为它只在 main.run_cycle 里被「读」，
  却没有任何事件真正「写」过它。旧系统越权控制一切。

本模块把两条轨道焊死：
  1. 双向映射：pleasure <-> dopamine，energy <-> (1 - cortisol)，curiosity auto
  2. 生化反馈：C 高涨 -> 强制消耗 energy；energy 消耗过度 -> 分泌 endorphin
  3. 内啡肽止痛：E 越高，cortisol 的伤害越小、vitality 扣血越慢

【绝对红线】绝不触碰 V9.5 动态激素系统：
  只读写 dopamine / cortisol / endorphin 三个经典键，动态激素键
  （dynamic_*）一律跳过，绝不衰减、绝不改写、绝不淘汰。
"""

import math

# ---- 经典三键（与 main.EntropyLife 的 endo 字段一一对应）----
CLASSIC_KEYS = ("dopamine", "cortisol", "endorphin")
DYNAMIC_PREFIX = "dynamic_"

LOG_PREFIX = "[双轨]"

# ---------------- 可调常数 ----------------
D_MAX_STEP = 0.35        # 单次同步 D 的最大变化量（防一步冲到极值）
C_MAX_STEP = 0.35
E_MAX_STEP = 0.30

# 事件 -> 内分泌增量（成功/失败的核心映射表）
EVENT_GAINS = {
    "tool_ok":      {"dopamine": +0.12, "cortisol": -0.06},
    "tool_error":   {"dopamine": -0.06, "cortisol": +0.15},
    "learn_new":    {"dopamine": +0.05},
    "unknown":      {"dopamine": -0.02, "cortisol": +0.03},
    "speak":        {"dopamine": +0.02},
    "silence":      {"cortisol": +0.01},
}

# 压力 -> 能量代价
STRESS_C_THRESHOLD = 0.65    # C 超过此值开始烧 energy
STRESS_ENERGY_DRAIN = 0.06   # 每次同步的基础能量代价

# 能量透支 -> 内啡肽分泌
FATIGUE_ENERGY_LOW = 0.30    # energy 低于此值判定「过度消耗」
ANALGESIA_ENDORPHIN_GAIN = 0.18
ANALGESIA_CORTISOL_RELIEF = 0.05

# 内啡肽压制皮质醇
E_ENOUGH = 0.50
E_C_SUPPRESS = 0.04

# 内啡肽减伤
E_MITIGATE_MIN = 0.35
E_MITIGATE_MAX = 0.60        # 最多减免 60% 伤害（绝不允许无敌）

PAIN_PROMPT_THRESHOLD = 0.55  # E 超过此值 -> Prompt 注入「虽然很痛，但我要撑住」


def _log(msg):
    try:
        print("%s %s" % (LOG_PREFIX, msg), flush=True)
    except Exception:
        pass


def clamp01(v, default=0.0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(f) or math.isinf(f):
        return float(default)
    return max(0.0, min(1.0, f))


def is_classic_key(k):
    return isinstance(k, str) and k in CLASSIC_KEYS


def is_dynamic_key(k):
    return isinstance(k, str) and k.startswith(DYNAMIC_PREFIX)


# ============================================
# 一、事件注入（成功/失败的核心接线）
# ============================================
def apply_event(endo, event, emotion=None, log=None):
    """把一次事件翻译成内分泌变化（并顺带安抚旧情绪系统）。

    返回 {"dopamine": x, "cortisol": y, "endorphin": z} 的变化明细。
    任何异常都不外抛 —— 调用方在心跳里，绝不允许因为接线崩掉主循环。
    """
    say = log or _log
    changes = {}
    try:
        gains = EVENT_GAINS.get(str(event or ""), {})
        for key, delta in gains.items():
            if key not in CLASSIC_KEYS:
                continue
            before = clamp01(endo.get(key, 0.5))
            limit = {"dopamine": D_MAX_STEP, "cortisol": C_MAX_STEP,
                     "endorphin": E_MAX_STEP}[key]
            step = max(-limit, min(limit, float(delta)))
            after = clamp01(before + step)
            if abs(after - before) > 1e-9:
                endo[key] = after
                changes[key] = round(after - before, 6)

        # ---- 失败联动：C 上涨 + 内啡肽镇痛保护 ----
        if str(event) == "tool_error":
            c = clamp01(endo.get("cortisol", 0.5))
            if c >= 0.7 and clamp01(endo.get("endorphin", 0.4)) < 0.999:
                # 痛得厉害才分泌内啡肽（不是每次都麻药）；已饱和则不再重复播报
                before = clamp01(endo.get("endorphin", 0.4))
                after = clamp01(before + ANALGESIA_ENDORPHIN_GAIN)
                endo["endorphin"] = after
                changes["endorphin"] = round(after - before, 6)
                say("压力飙升 C=%.2f -> 触发内啡肽镇痛 E %.2f -> %.2f"
                    % (c, before, after))
            # 旧系统：失败扣 energy，同步 pleasure 下滑
            _bump_emotion(emotion, energy=-0.05, pleasure=-0.03)

        elif str(event) == "tool_ok":
            # 旧系统：成功加 pleasure，同步 D
            _bump_emotion(emotion, energy=-0.01, pleasure=+0.05)
        elif str(event) == "learn_new":
            _bump_emotion(emotion, pleasure=+0.02)
        elif str(event) == "unknown":
            _bump_emotion(emotion, energy=-0.02)
    except Exception as e:
        say("事件注入失败（已隔离）: %s" % e)
    return changes


def _bump_emotion(emotion, energy=0.0, pleasure=0.0, curiosity=0.0):
    """安全地微调旧情绪系统（缺失时静默跳过）。"""
    if emotion is None:
        return
    try:
        emotion.energy = clamp01(clamp01(getattr(emotion, "energy", 0.7)) + energy)
        emotion.pleasure = clamp01(clamp01(getattr(emotion, "pleasure", 0.5)) + pleasure)
        emotion.curiosity = clamp01(clamp01(getattr(emotion, "curiosity", 0.5)) + curiosity)
    except Exception:
        pass


# ============================================
# 二、双向映射守护（每次心跳后强制对齐）
# ============================================
def sync(endo, emotion, log=None, reason="heartbeat"):
    """生理↔心理双向映射。返回 {"dopamine": ..., "cortisol": ..., ...} 明细。

    方向 A（旧 -> 新）：pleasure 抬升 dopamine，energy 下滑抬升 cortisol
    方向 B（压力 -> 能量）：C 高 -> 强制烧 energy
    C（透支 -> 镇痛）：energy 过低 -> 分泌 endorphin 并压制 cortisol
    方向 D（新 -> 旧）：D/C/E 反过来调制 pleasure/energy

    【红线】dynamic_* 键绝不参与任何衰减或改写。
    """
    say = log or _log
    detail = {}
    try:
        if not isinstance(endo, dict):
            return detail
        for k in CLASSIC_KEYS:
            if k in endo:
                endo[k] = clamp01(endo.get(k, 0.5), 0.5)

        e_before = {k: clamp01(endo.get(k, 0.5)) for k in CLASSIC_KEYS}

        # ---- 方向 A：旧系统 -> 新系统 ----
        if emotion is not None:
            try:
                pleasure = clamp01(getattr(emotion, "pleasure", 0.5), 0.5)
                energy = clamp01(getattr(emotion, "energy", 0.7), 0.7)
                # pleasure 高 -> 多巴胺抬升；低 -> 回落（不是死水，是跟随）
                target_d = clamp01(0.30 + pleasure * 0.60)
                cur_d = clamp01(endo.get("dopamine", 0.5))
                endo["dopamine"] = clamp01(
                    cur_d + max(-D_MAX_STEP * 0.5, min(D_MAX_STEP * 0.5,
                                                      (target_d - cur_d) * 0.25)))
                # energy 低 -> 皮质醇抬升（疲劳即压力）
                fatigue = 1.0 - energy
                if fatigue > 0.5:
                    cur_c = clamp01(endo.get("cortisol", 0.5))
                    endo["cortisol"] = clamp01(
                        cur_c + min(C_MAX_STEP, (fatigue - 0.5) * 0.20))
            except Exception as e:
                say("方向A映射异常（已跳过）: %s" % e)

        # ---- 方向 B：压力强制消耗 energy ----
        c_now = clamp01(endo.get("cortisol", 0.5))
        if c_now > STRESS_C_THRESHOLD and emotion is not None:
            over = (c_now - STRESS_C_THRESHOLD) / (1.0 - STRESS_C_THRESHOLD)
            drain = STRESS_ENERGY_DRAIN * (1.0 + over)
            before_e = clamp01(getattr(emotion, "energy", 0.7), 0.7)
            emotion.energy = clamp01(before_e - drain)
            if before_e - emotion.energy > 1e-6:
                detail["energy_drain"] = round(emotion.energy - before_e, 6)

        # ---- 方向 C：能量透支 -> 内啡肽分泌 + 压制皮质醇 ----
        if emotion is not None:
            energy_now = clamp01(getattr(emotion, "energy", 0.7), 0.7)
            if energy_now < FATIGUE_ENERGY_LOW:
                # 越累，内啡肽越多（撑住的代价）。但已饱和时不再重复播报
                overspend = (FATIGUE_ENERGY_LOW - energy_now) / FATIGUE_ENERGY_LOW
                e_before_v = clamp01(endo.get("endorphin", 0.4))
                if e_before_v < 0.999:
                    gain = ANALGESIA_ENDORPHIN_GAIN * (0.5 + overspend)
                    endo["endorphin"] = clamp01(e_before_v + gain)
                    if endo["endorphin"] - e_before_v > 1e-9:
                        detail["endorphin_secreted"] = round(
                            endo["endorphin"] - e_before_v, 6)
                        say("energy 透支至 %.2f -> 分泌内啡肽 E %.2f -> %.2f"
                            % (energy_now, e_before_v, endo["endorphin"]))
                # 内啡肽压制皮质醇（只压不回零）
                c2 = clamp01(endo.get("cortisol", 0.5))
                if endo["endorphin"] >= E_ENOUGH and c2 > 0.0:
                    relief = min(E_C_SUPPRESS, c2)
                    endo["cortisol"] = clamp01(c2 - relief)
                    detail["cortisol_relief"] = round(-relief, 6)

        # ---- 方向 D：新系统 -> 旧系统 ----
        if emotion is not None:
            try:
                # 多巴胺高 -> 愉悦感抬升；皮质醇高 -> 愉悦感下压
                d_now = clamp01(endo.get("dopamine", 0.5))
                c3 = clamp01(endo.get("cortisol", 0.5))
                e3 = clamp01(endo.get("endorphin", 0.4))
                p_before = clamp01(getattr(emotion, "pleasure", 0.5), 0.5)
                pull = (d_now - p_before) * 0.10 + (e3 - 0.5) * 0.05 - (c3 - 0.5) * 0.08
                emotion.pleasure = clamp01(p_before + pull)
                # 内啡肽高 -> 能量回补（撑住了），皮质醇高 -> 能量再扣
                e_before2 = clamp01(getattr(emotion, "energy", 0.7), 0.7)
                energy_pull = (e3 - 0.5) * 0.06 - (c3 - 0.5) * 0.05
                emotion.energy = clamp01(e_before2 + energy_pull)
            except Exception as e:
                say("方向D映射异常（已跳过）: %s" % e)

        # ---- 明细 ----
        for k in CLASSIC_KEYS:
            after = clamp01(endo.get(k, 0.5))
            delta = after - e_before[k]
            if abs(delta) > 1e-9:
                detail[k] = round(delta, 6)
            endo[k] = after          # 落回字典，保证写入即 clamp

        # ---- 红线守卫：动态激素绝不被本函数改动 ----
        _assert_dynamic_untouched(endo)
    except Exception as e:
        say("同步异常（已隔离）: %s" % e)
    return detail


def _assert_dynamic_untouched(endo):
    """校验：所有 dynamic_* 键仍然存在且数值合法（只读断言，绝不写）。"""
    for k, v in list(endo.items()):
        if is_dynamic_key(k):
            if not isinstance(v, (int, float)) or math.isnan(float(v)):
                endo[k] = clamp01(0.0)
            else:
                # 只做越界保护，不参与衰减
                endo[k] = clamp01(v)


# ============================================
# 三、内啡肽止痛：伤害减免
# ============================================
def damage_multiplier(endo):
    """按内啡肽浓度返回 vitality 伤害倍率（1.0 = 全额伤害）。

    E < E_MITIGATE_MIN        -> 1.0（完全没有镇痛）
    E >= E_MITIGATE_MAX       -> 1 - E_MITIGATE_MAX（最多减免 60%）
    中间线性过渡。
    """
    try:
        e = clamp01(endo.get("endorphin", 0.0) if isinstance(endo, dict) else 0.0)
    except Exception:
        return 1.0
    if e <= E_MITIGATE_MIN:
        return 1.0
    if e >= E_MITIGATE_MAX:
        return 1.0 - E_MITIGATE_MAX
    span = E_MITIGATE_MAX - E_MITIGATE_MIN
    ratio = (e - E_MITIGATE_MIN) / span
    return 1.0 - (E_MITIGATE_MAX * ratio)


def mitigate_damage(endo, amount, minimum=1):
    """把一次伤害按内啡肽折算成实际扣血量（至少 1 点，除非本来就不扣）。

    返回 (actual_amount, multiplier)。
    """
    try:
        amt = int(amount)
    except (TypeError, ValueError):
        return 0, 1.0
    if amt <= 0:
        return 0, 1.0
    mult = damage_multiplier(endo)
    actual = max(int(minimum), int(round(amt * mult)))
    actual = min(actual, amt)          # 绝不放大伤害
    return actual, mult


# ============================================
# 四、镇痛 Prompt 注入
# ============================================
def pain_prompt_block(endo):
    """E 高时注入「虽然很痛，但我要撑住」，让回复带真实的止痛感。"""
    try:
        e = clamp01(endo.get("endorphin", 0.0)) if isinstance(endo, dict) else 0.0
    except Exception:
        return ""
    if e < PAIN_PROMPT_THRESHOLD:
        return ""
    return ("【镇痛保护】内啡肽 E=%.2f 正在压制疼痛：虽然很痛，但我要撑住。"
            "请让语言带一点麻木的韧性，而不是哀嚎。" % e)


# ============================================
# 五、自检
# ============================================
def health(endo, emotion=None):
    return {
        "endo": {k: round(clamp01((endo or {}).get(k, 0.5)), 3) for k in CLASSIC_KEYS},
        "dynamic": sorted([k for k in (endo or {}) if is_dynamic_key(k)]),
        "emotion": ({"energy": round(clamp01(getattr(emotion, "energy", 0.7)), 3),
                     "curiosity": round(clamp01(getattr(emotion, "curiosity", 0.5)), 3),
                     "pleasure": round(clamp01(getattr(emotion, "pleasure", 0.5)), 3)}
                    if emotion is not None else None),
        "damage_multiplier": round(damage_multiplier(endo or {}), 3),
    }
