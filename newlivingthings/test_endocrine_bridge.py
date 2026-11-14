# -*- coding: utf-8 -*-
"""test_endocrine_bridge.py -- AC OS V9.6 生理↔心理双轨融合 TDD 验收

审查者发现的致命断层：
  新内分泌 D/C/E 自启动后永远卡在 0.5（一潭死水），
  旧的 energy/curiosity/pleasure 却在偷偷越权控制一切。

本套件验证四件事：
  1. 连续 10 次工具调用失败，D/C/E 不再是 0.5 死水，而是真实反映压力
  2. 该过程确实触发了内啡肽（endorphin）分泌
  3. 内啡肽确实延缓了 vitality 归零（扣血减免）
  4. 【绝对红线】V9.5 动态激素系统完全不受影响
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail), flush=True)
    return bool(cond)


class FakeEmotion(object):
    """模拟 emotion.py 的旧情绪系统（字段与真实一致）。"""

    def __init__(self, energy=0.7, curiosity=0.5, pleasure=0.5):
        self.energy = energy
        self.curiosity = curiosity
        self.pleasure = pleasure


class FakeSoul(object):
    """模拟 soul_core.SoulState 的生命值。"""

    def __init__(self, vitality=100):
        self.vitality = vitality

    def spend(self, amount, reason=""):
        self.vitality = max(0, self.vitality - int(amount))

    def heal(self, amount, reason=""):
        self.vitality = min(100, self.vitality + int(amount))


def fresh():
    endo = {"dopamine": 0.5, "cortisol": 0.5, "endorphin": 0.5,
            "curiosity": 0.5}
    return endo, FakeEmotion()


# ============================================
# 1. 核心：连续 10 次工具调用失败
# ============================================
def test_1_ten_tool_failures():
    print("\n[1] 连续 10 次工具调用失败：D/C/E 不再是死水", flush=True)
    import endocrine_bridge as eb

    endo, emo = fresh()
    start = {k: endo[k] for k in eb.CLASSIC_KEYS}
    print("      开局: D=%.3f C=%.3f E=%.3f | energy=%.2f pleasure=%.2f"
          % (start["dopamine"], start["cortisol"], start["endorphin"],
             emo.energy, emo.pleasure), flush=True)

    trend = []
    for i in range(10):
        eb.apply_event(endo, "tool_error", emo)
        eb.sync(endo, emo)
        trend.append((round(endo["dopamine"], 3), round(endo["cortisol"], 3),
                      round(endo["endorphin"], 3), round(emo.energy, 3)))
        print("      第%2d次失败: D=%.3f C=%.3f E=%.3f | energy=%.3f pleasure=%.3f"
              % (i + 1, endo["dopamine"], endo["cortisol"], endo["endorphin"],
                 emo.energy, emo.pleasure), flush=True)

    # ---- 核心断言：不是死水 ----
    check("dopamine 已离开 0.5 死水", abs(endo["dopamine"] - 0.5) > 0.05,
          "D=%.3f" % endo["dopamine"])
    check("cortisol 已离开 0.5 死水", abs(endo["cortisol"] - 0.5) > 0.1,
          "C=%.3f" % endo["cortisol"])
    check("endorphin 已离开 0.5 死水", abs(endo["endorphin"] - 0.5) > 0.1,
          "E=%.3f" % endo["endorphin"])
    check("三键都不再恒等于 0.5",
          not all(abs(endo[k] - 0.5) < 1e-9 for k in eb.CLASSIC_KEYS))

    # ---- 方向正确：失败 -> C 升 D 降 ----
    check("失败使 cortisol 上升", endo["cortisol"] > start["cortisol"],
          "%.3f -> %.3f" % (start["cortisol"], endo["cortisol"]))
    check("失败使 dopamine 下降", endo["dopamine"] < start["dopamine"],
          "%.3f -> %.3f" % (start["dopamine"], endo["dopamine"]))
    check("全部数值仍在 [0,1]", all(0.0 <= endo[k] <= 1.0 for k in eb.CLASSIC_KEYS),
          str({k: round(endo[k], 3) for k in eb.CLASSIC_KEYS}))

    # ---- 旧系统也被真实牵动（不再是越权单飞）----
    check("旧系统 energy 被压力消耗", emo.energy < 0.7, "%.3f" % emo.energy)
    check("旧系统 pleasure 随失败下滑", emo.pleasure < 0.5, "%.3f" % emo.pleasure)
    return endo, trend


# ============================================
# 2. 内啡肽分泌
# ============================================
def test_2_endorphin_secretion(trend):
    print("\n[2] 内啡肽（endorphin）是否被真实触发", flush=True)
    import endocrine_bridge as eb

    e_series = [t[2] for t in trend]
    print("      E 轨迹: %s" % " -> ".join("%.3f" % v for v in e_series), flush=True)
    check("内啡肽确实分泌了（高于初始 0.5）", e_series[-1] > 0.5,
          "E: 0.500 -> %.3f" % e_series[-1])
    check("内啡肽呈上升趋势而非随机抖动",
          e_series[-1] >= e_series[1] - 1e-9, str(e_series[:3]))
    check("内啡肽封顶不越界", e_series[-1] <= 1.0)

    # 低压力不应平白分泌内啡肽
    endo, emo = fresh()
    eb.apply_event(endo, "tool_ok", emo)
    eb.sync(endo, emo)
    check("低压力下不滥用内啡肽", endo["endorphin"] <= 0.5 + 1e-6,
          "E=%.3f" % endo["endorphin"])

    # 镇痛 Prompt 注入
    endo2, emo2 = fresh()
    endo2["endorphin"] = 0.8
    block = eb.pain_prompt_block(endo2)
    check("内啡肽高时注入镇痛 Prompt", "虽然很痛，但我要撑住" in block, block[:60])
    endo3 = {"dopamine": 0.5, "cortisol": 0.5, "endorphin": 0.1}
    check("内啡肽低时不注入镇痛 Prompt", eb.pain_prompt_block(endo3) == "")
    return e_series


# ============================================
# 3. 内啡肽延缓 vitality 归零
# ============================================
def test_3_vitality_mitigation():
    print("\n[3] 内啡肽是否真的延缓 vitality 归零", flush=True)
    import endocrine_bridge as eb

    # ---- 纯换算层 ----
    low = {"dopamine": 0.5, "cortisol": 0.9, "endorphin": 0.0}
    high = {"dopamine": 0.5, "cortisol": 0.9, "endorphin": 0.9}
    a_low, m_low = eb.mitigate_damage(low, 10)
    a_high, m_high = eb.mitigate_damage(high, 10)
    print("      E=0.00 -> 扣血 %d (x%.2f) | E=0.90 -> 扣血 %d (x%.2f)"
          % (a_low, m_low, a_high, m_high), flush=True)
    check("无内啡肽时全额扣血", a_low == 10, str(a_low))
    check("高内啡肽时扣血减少", a_high < a_low, "%d < %d" % (a_high, a_low))
    check("减免幅度封顶不超过 60%", a_high >= int(round(10 * 0.4)), str(a_high))
    check("绝不允许无敌（至少扣 1）", eb.mitigate_damage(
        {"endorphin": 1.0}, 10)[0] >= 1)
    check("伤害绝不放大", eb.mitigate_damage(
        {"endorphin": 0.5}, 10)[0] <= 10)

    # ---- 端到端：走 main.EntropyLife._soul_spend（真实生产代码）----
    import main as M

    class FakeLife(object):
        pass

    def run_series(endorphin_start, rounds=None):
        """跑 rounds 次失败（None = 一直跑到归零）。返回 (剩余生命, 归零所需次数)。"""
        life = FakeLife()
        life.endo = {"dopamine": 0.5, "cortisol": 0.9, "endorphin": endorphin_start}
        life.soul = FakeSoul(100)
        life.system = type("S", (), {"emotion": FakeEmotion()})()
        life._check_near_death_scar = lambda: None
        life._soul_spend = M.EntropyLife._soul_spend.__get__(life, FakeLife)
        n = 0
        limit = rounds if rounds is not None else 200
        while life.soul.vitality > 0 and n < limit:
            life._soul_spend(10, "工具失败")
            n += 1
        return life.soul.vitality, n

    v_plain, r_plain = run_series(0.0)
    v_pain, r_pain = run_series(0.9)
    print("      E=0.0: 一直扣到死，第 %d 次归零" % r_plain, flush=True)
    print("      E=0.9: 一直扣到死，第 %d 次归零" % r_pain, flush=True)
    check("内啡肽确实延缓归零（需要更多次失败才死）",
          r_pain > r_plain, "%d 次 vs %d 次" % (r_pain, r_plain))

    # 同样的 10 次失败，内啡肽组剩下的血更多（公平对比）
    v10_plain, _ = run_series(0.0, rounds=10)
    v10_pain, _ = run_series(0.9, rounds=10)
    print("      10 次失败后：E=0.0 剩 %d 点 | E=0.9 剩 %d 点"
          % (v10_plain, v10_pain), flush=True)
    check("同样 10 次失败，内啡肽组剩余生命值更高", v10_pain > v10_plain,
          "%d > %d" % (v10_pain, v10_plain))
    check("内啡肽组 10 次失败后仍未归零", v10_pain > 0, str(v10_pain))
    return v10_plain, v10_pain


# ============================================
# 4. 【绝对红线】V9.5 动态激素系统不受影响
# ============================================
def test_4_dynamic_hormones_untouched():
    print("\n[4] 【绝对红线】V9.5 动态激素系统完好无损", flush=True)
    import endocrine_bridge as eb
    import hormone_registry as hr

    endo = {"dopamine": 0.5, "cortisol": 0.5, "endorphin": 0.5}
    reg = hr.HormoneRegistry(endo=endo, log=lambda m: None)
    reg.synthesize("狂暴素", value=0.8, temperature=1.0, priority=70,
                   biological_meaning="暴怒")
    reg.synthesize("孤独素", value=0.6, biological_meaning="空洞")
    dyn_before = {k: v for k, v in endo.items() if k.startswith("dynamic_")}
    check("动态激素已注入（基线确认）", len(dyn_before) == 2, str(dyn_before))

    # 让双轨同步/事件/伤害整治跑满 20 次
    emo = FakeEmotion()
    for _ in range(20):
        eb.apply_event(endo, "tool_error", emo)
        eb.sync(endo, emo)
        eb.mitigate_damage(endo, 10)

    dyn_after = {k: v for k, v in endo.items() if k.startswith("dynamic_")}
    check("动态激素键一个不少", set(dyn_before) == set(dyn_after),
          "%s vs %s" % (sorted(dyn_before), sorted(dyn_after)))
    check("动态激素数值绝未被双轨改写", dyn_before == dyn_after,
          "%s vs %s" % (dyn_before, dyn_after))
    check("注册表内激素仍然健在", reg.count() == 2, str(reg.count()))
    check("温度仲裁仍然正常", reg.arbitrate_temperature()[0] == 1.0,
          str(reg.arbitrate_temperature()))

    # 5 种上限与 200 字截断（V9.5 红线）依旧生效
    reg2 = hr.HormoneRegistry(endo={}, log=lambda m: None)
    for i in range(6):
        reg2.synthesize("h%d" % i, value=0.1 * (i + 1))
    check("V9.5 五种上限仍生效", reg2.count() == 5, str(reg2.count()))
    reg3 = hr.HormoneRegistry(endo={}, log=lambda m: None)
    for i in range(5):
        reg3.synthesize("超长激素%d" % i, value=0.9,
                        biological_meaning="很长很长的释义" * 30)
    blk = reg3.build_prompt_block()
    check("V9.5 Prompt 200 字截断仍生效", len(blk) <= 200, "%d 字" % len(blk))

    # 经典激素的 clamp 不会被动态键带偏
    check("经典三键仍被 clamp 在 [0,1]",
          all(0.0 <= endo[k] <= 1.0 for k in hr.__dict__.get(
              "CLASSIC_KEYS", ("dopamine", "cortisol", "endorphin"))))
    return dyn_after


# ============================================
# 5. 防崩：脏数据 / 缺失系统
# ============================================
def test_5_robustness():
    print("\n[5] 防崩校验：脏数据与缺失系统", flush=True)
    import endocrine_bridge as eb

    # 缺 emotion
    endo = {"dopamine": 0.5, "cortisol": 0.5, "endorphin": 0.5}
    r = eb.sync(endo, None)
    check("emotion 缺失时同步不崩", isinstance(r, dict),
          str({k: round(v, 3) for k, v in endo.items()}))

    # 脏数值
    dirty = {"dopamine": "abc", "cortisol": float("nan"), "endorphin": 99}
    eb.sync(dirty, FakeEmotion())
    check("脏数值被 clamp 修复",
          all(0.0 <= v <= 1.0 for v in dirty.values()),
          str({k: round(v, 3) for k, v in dirty.items()}))

    # 缺键
    thin = {}
    eb.sync(thin, FakeEmotion())
    check("缺键时自动补齐三键",
          all(k in thin for k in ("dopamine", "cortisol", "endorphin")), str(thin))

    # 极端参数
    check("伤害减免对空 endo 不崩", eb.mitigate_damage({}, 10) == (10, 1.0),
          str(eb.mitigate_damage({}, 10)))
    check("负伤害返回 0", eb.mitigate_damage({"endorphin": 1.0}, -5)[0] == 0)
    check("emotion 字段非法时不崩", eb.apply_event(
        {"dopamine": 0.5}, "tool_error", object()) is not None)
    return True


# ============================================
def main_guard():
    print("=" * 66, flush=True)
    print(" AC OS V9.6 生理↔心理双轨融合 TDD 验收", flush=True)
    print("=" * 66, flush=True)
    _endo, trend = test_1_ten_tool_failures()
    test_2_endorphin_secretion(trend)
    test_3_vitality_mitigation()
    test_4_dynamic_hormones_untouched()
    test_5_robustness()

    print("\n" + "=" * 66, flush=True)
    total = len(PASS) + len(FAIL)
    print(" 结果: %d/%d 通过" % (len(PASS), total), flush=True)
    if FAIL:
        print(" 失败项: %s" % ", ".join(FAIL), flush=True)
        print("=" * 66, flush=True)
        return 1
    print(" ✅ 全部通过", flush=True)
    print("=" * 66, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main_guard())
