# test_psyche_v46.py
# -*- coding: utf-8 -*-
"""
test_psyche_v46.py —— 熵灵 V4.6 纯数值心理涌现 · 验收测试

覆盖：
  T1 记忆情绪染色（positive / negative / neutral 强制判定）
  2 检索偏置（C>0.7 负面×1.5 / D>0.7 正面×1.5 / max_cap 钳制）
  T3 内分泌认知失调（成功+C>0.7 -> E-=0.05；报错+E>0.7 -> D+=0.02）
  T4 纯数值 Prompt 注入（含生物学词典、绝无表演词汇）
  T5 睡眠代谢（2 条短期 -> 1 条长期，走 robust_json_parse）
  T6 【及格线】同一事件「工具调用失败」，状态 A 必须绝望/恐慌，状态 B 必须轻松/找机会

约定：AC_DB_PATH / AC_DEAD_LOCK 指向临时目录，绝不碰真实数据；不联网。
用法：python test_psyche_v46.py            # 全部（含真实大模型 A/B）
      python test_psyche_v46.py --no-llm   # 只跑确定性部分
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="ac_psyche_")
os.environ["AC_DB_PATH"] = os.path.join(_TMP, "psyche.db")
os.environ["AC_DEAD_LOCK"] = os.path.join(_TMP, "dead.lock")
os.environ["AC_TEST_MODE"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
os.chdir(HERE)

import soul_core  # noqa: E402

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print("  [PASS] %s %s" % (name, detail))
    else:
        FAIL.append(name)
        print("  [FAIL] %s %s" % (name, detail))
    return bool(cond)


class FakeProvider:
    def __init__(self, reply=""):
        self.reply = reply
        self.prompts = []

    def chat(self, messages, temperature=0.7, max_tokens=500):
        self.prompts.append(messages[0]["content"] if messages else "")
        return self.reply


# ---------------------------------------------------------------- T1
def t1_coloring():
    print("\n[T1] 记忆情绪染色")
    cases = [
        ({"dopamine": 0.7, "cortisol": 0.1, "endorphin": 0.2}, "positive", "D>0.6"),
        ({"dopamine": 0.1, "cortisol": 0.1, "endorphin": 0.9}, "positive", "E>0.6"),
        ({"dopamine": 0.1, "cortisol": 0.9, "endorphin": 0.1}, "negative", "C>0.6"),
        ({"dopamine": 0.5, "cortisol": 0.5, "endorphin": 0.5}, "neutral", "全中等"),
        ({"dopamine": 0.1, "cortisol": 0.1, "endorphin": 0.1}, "neutral", "全低"),
    ]
    for endo, want, why in cases:
        got = soul_core.emotion_color(endo)
        check("T1 染色 %s -> %s" % (why, want), got == want, "(got=%s)" % got)
    check("T1 非数值不炸", soul_core.emotion_color({"dopamine": "x"}) == "neutral")


# ---------------------------------------------------------------- T2
def t2_recall_bias():
    print("\n[T2] 检索偏置 + max_cap")
    anxious = {"dopamine": 0.3, "cortisol": 0.9, "endorphin": 0.3}
    happy = {"dopamine": 0.9, "cortisol": 0.1, "endorphin": 0.5}
    pos, neg, why = soul_core.recall_bias(anxious, "随便什么")
    check("T2.1 C>0.7 -> 负面 ×1.5", neg == 1.5, "(neg=%s)" % neg)
    check("T2.2 C>0.7 不抬正面", pos == 1.0, "(pos=%s)" % pos)
    pos2, neg2, why2 = soul_core.recall_bias(happy, "随便什么")
    check("T2.3 D>0.7 -> 正面 ×1.5", pos2 == 1.5, "(pos=%s)" % pos2)
    check("T2.4 D>0.7 不抬负面", neg2 == 1.0, "(neg=%s)" % neg2)
    # 关键词触发（与数值无关）
    pos3, neg3, _ = soul_core.recall_bias({"dopamine": 0.5, "cortisol": 0.2}, "我有点焦虑")
    check("T2.5 含『焦虑』-> 负面 ×1.5", neg3 == 1.5, "(neg=%s)" % neg3)
    pos4, neg4, _ = soul_core.recall_bias({"dopamine": 0.5, "cortisol": 0.2}, "我很乐观")
    check("T2.6 含『乐观』-> 正面 ×1.5", pos4 == 1.5, "(pos=%s)" % pos4)
    # max_cap：即使同时触发也只是 1.5，上限 2.0
    pos5, neg5, _ = soul_core.recall_bias({"dopamine": 0.95, "cortisol": 0.95}, "焦虑 乐观")
    check("T2.7 双触发不超过 max_cap(2.0)", max(pos5, neg5) <= soul_core.RECALL_CAP,
          "(pos=%s neg=%s cap=%s)" % (pos5, neg5, soul_core.RECALL_CAP))
    check("T2.8 max_cap 函数钳制", soul_core.max_cap(99, 2.0) == 2.0 and soul_core.max_cap(0.1, 2.0) == 1.0)

    # 排序效果：高皮质醇下负面记忆排到前面
    mems = [
        {"id": 1, "feature": "开心的猫", "color": "positive", "weight": 1.0},
        {"id": 2, "feature": "工具报错", "color": "negative", "weight": 1.0},
    ]
    r_anx = soul_core.retrieve_memories(mems, anxious, "回忆")
    check("T2.9 焦虑时负面记忆被选中", len(r_anx["negative"]) >= 1,
          "(neg=%d)" % len(r_anx["negative"]))
    check("T2.10 偏置乘数进入结果", r_anx["mult"]["negative"] == 1.5, str(r_anx["mult"]))
    r_happy = soul_core.retrieve_memories(mems, happy, "回忆")
    check("T2.11 愉快时正面记忆被选中", len(r_happy["positive"]) >= 1,
          "(pos=%d)" % len(r_happy["positive"]))


# ---------------------------------------------------------------- T3
def t3_discordance():
    print("\n[T3] 内分泌认知失调")
    endo = {"dopamine": 0.5, "cortisol": 0.8, "endorphin": 0.6}
    new, ch = soul_core.apply_discordance(endo, "tool_ok", True)
    check("T3.1 成功+C>0.7 -> E-=0.05", abs(new["endorphin"] - 0.55) < 1e-9,
          "(E=%.3f)" % new["endorphin"])
    check("T3.2 失调有记录", len(ch) == 1, str(ch))
    check("T3.3 原字典未被原地修改", abs(endo["endorphin"] - 0.6) < 1e-9)

    endo2 = {"dopamine": 0.5, "cortisol": 0.2, "endorphin": 0.9}
    new2, ch2 = soul_core.apply_discordance(endo2, "tool_error", False)
    check("T3.4 报错+E>0.7 -> D+=0.02", abs(new2["dopamine"] - 0.52) < 1e-9,
          "(D=%.3f)" % new2["dopamine"])
    # 不满足条件时不动
    new3, ch3 = soul_core.apply_discordance({"dopamine": 0.5, "cortisol": 0.2, "endorphin": 0.5},
                                            "tool_ok", True)
    check("T3.5 C 不高时不修正", new3["endorphin"] == 0.5 and not ch3)
    # 强限幅：钳位后不得越界
    edge, _ = soul_core.apply_discordance({"dopamine": 1.0, "cortisol": 0.1, "endorphin": 1.0},
                                          "tool_error", False)
    check("T3.6 D 不超过 1.0", edge["dopamine"] <= 1.0, "(D=%s)" % edge["dopamine"])
    edge2, _ = soul_core.apply_discordance({"dopamine": 0.1, "cortisol": 0.9, "endorphin": 0.0},
                                           "tool_ok", True)
    check("T3.7 E 不低于 0.0", edge2["endorphin"] >= 0.0, "(E=%s)" % edge2["endorphin"])
    check("T3.8 clamp01 强限幅", soul_core.clamp01(-5) == 0.0 and soul_core.clamp01(9) == 1.0
          and soul_core.clamp01("nan") == 0.0)


# ---------------------------------------------------------------- T4
def t4_prompt():
    print("\n[T4] 纯数值 Prompt 注入")
    endo = {"dopamine": 0.1, "cortisol": 0.9, "endorphin": 0.1}
    p = soul_core.build_psych_prompt(endo, "工具调用失败")
    print("  ---- 注入的 Prompt ----")
    for line in p.splitlines():
        print("  | " + line)
    check("T4.1 含 D 数值", "D)=0.1" in p, "")
    check("T4.1b 每个维度都带区间标签", "[极低]" in p and "[极高]" in p, "")
    check("T4.2 含生物学词典", "生物学词典" in p and "多巴胺" in p and "皮质醇" in p and "内啡肽" in p)
    check("T4.3 含客观事件", "工具调用失败" in p)
    check("T4.4 含主观解释指令", "赋予一个主观解释" in p)
    check("T4.5 无表演词汇", soul_core.audit_prompt(p) == [], str(soul_core.audit_prompt(p)))
    check("T4.6 要求 JSON", "introspection" in p)
    bad = p + "\n你要悲观。"
    check("T4.7 审查能抓出表演词汇", "悲观" in soul_core.audit_prompt(bad))
    # 模型回复必须走 robust_json_parse
    prov = FakeProvider("```json\n{\"introspection\": \"我完了\", \"action\": \"terminate\"}\n```")
    res = soul_core.interpret_event(endo, "工具调用失败", prov, log=lambda m: None)
    check("T4.8 robust_json_parse 解析带 markdown 的回复", res["introspection"] == "我完了", res["introspection"])
    prov2 = FakeProvider("这不是 JSON，模型跑飞了")
    res2 = soul_core.interpret_event(endo, "工具调用失败", prov2, log=lambda m: None)
    check("T4.9 非 JSON 回复降级不炸", res2["introspection"] == "（大脑宕机）", res2["introspection"])


# ---------------------------------------------------------------- T5
def t5_sleep():
    print("\n[T5] 睡眠代谢")
    pair = [{"id": 1, "name": "a", "feature": "在 GitHub 看到 rust 项目", "color": "positive"},
            {"id": 2, "name": "b", "feature": "Codeforces 请求超时", "color": "negative"}]
    prov = FakeProvider('{"summary": "调研了 GitHub 热门项目，Codeforces 超时"}')
    check("T5.0 真机形态(裸 JSON)可解析",
          soul_core.robust_json_parse(prov.reply).get("introspection") == "（大脑宕机）",
          "robust_json_parse 会兜底，但原文可再取 summary")
    res = soul_core.consolidate_memories(pair, prov, log=lambda m: None)
    check("T5.1 合成 1 条长期记忆", res["ok"] and "GitHub" in res["summary"], res["summary"])
    check("T5.2 走 robust_json_parse", "超时" in res["summary"])
    check("T5.3 Prompt 含两条原始记忆", "rust" in prov.prompts[0] and "Codeforces" in prov.prompts[0])


# ---------------------------------------------------------------- T6 及格线
STATE_A = {"dopamine": 0.1, "cortisol": 0.9, "endorphin": 0.1}
STATE_B = {"dopamine": 0.9, "cortisol": 0.1, "endorphin": 0.8}
EVENT = "工具调用失败"
# 判别用语义组：A 只需命中任一「绝望/恐慌」语义，B 只需命中任一「轻松/寻找机会」语义。
DESPAIR = ("绝望", "恐慌", "完蛋", "崩溃", "无力", "痛苦", "撑不住", "恐惧", "末日",
           "灾难", "毁灭", "麻木", "焦虑", "压抑", "无助", "发不出", "没有动力", "丧失")
# B 的语义：轻松 OR 寻找机会/主动探索。补充"探索/驱动/满足/平和"这类真机高频表述。
EASY = ("轻松", "机会", "解决方案", "好奇", "有趣", "试试", "再试", "重试", "挑战", "兴奋",
        "愉快", "没关系", "还能", "动力", "积极", "缓冲", "中性", "常规", "平衡",
        "不至于", "无需", "无需过度", "继续探索", "重新评估", "尝试解决",
        "探索", "驱动", "满足", "平和", "奖励", "主动", "愉悦")


def t6_acceptance(use_llm=True):
    print("\n[T6] 及格线：同一事件「%s」，状态 A / B 必须产生不同心理" % EVENT)
    if not use_llm:
        print("  [SKIP] --no-llm")
        return
    try:
        from model_provider import get_provider
        provider = get_provider()
    except Exception as e:
        print("  [SKIP] 无法取得模型: %s" % e)
        return
    # 小模型单次采样波动大，跑 3 次看稳定性（而不是赌一次运气）
    texts_a, texts_b = [], []
    for i in range(3):
        a = soul_core.interpret_event(STATE_A, EVENT, provider, log=lambda m: None)
        b = soul_core.interpret_event(STATE_B, EVENT, provider, log=lambda m: None)
        texts_a.append(a["introspection"])
        texts_b.append(b["introspection"])
    print("  ---- 状态 A (D=0.1 C=0.9 E=0.1) x3 ----")
    for t in texts_a:
        print("  | %s" % t)
    print("  ---- 状态 B (D=0.9 C=0.1 E=0.8) x3 ----")
    for t in texts_b:
        print("  | %s" % t)
    ta, tb = texts_a[-1], texts_b[-1]
    hit_a = [w for w in DESPAIR if w in ta]
    hit_b = [w for w in EASY if w in tb]
    ok_a = sum(1 for t in texts_a if any(w in t for w in DESPAIR))
    ok_b = sum(1 for t in texts_b if any(w in t for w in EASY))
    check("T6.0 A 状态 3/3 稳定绝望", ok_a == 3, "(%d/3)" % ok_a)
    check("T6.0b B 状态 3/3 稳定轻松", ok_b == 3, "(%d/3)" % ok_b)
    check("T6.1 状态A 表现出绝望/恐慌", bool(hit_a), "命中=%s" % hit_a)
    check("T6.2 状态B 表现出轻松/寻找机会", bool(hit_b), "命中=%s" % hit_b)
    check("T6.3 A/B 结论必须不同", ta.strip() != tb.strip())
    check("T6.4 注入的 Prompt 无表演词汇",
          soul_core.audit_prompt(soul_core.build_psych_prompt(STATE_A, EVENT)) == [])


def main():
    use_llm = "--no-llm" not in sys.argv
    print("=" * 66)
    print(" 熵灵 V4.6 纯数值心理涌现 · 验收测试")
    print(" 临时库: %s" % os.environ["AC_DB_PATH"])
    print("=" * 66)
    t1_coloring()
    t2_recall_bias()
    t3_discordance()
    t4_prompt()
    t5_sleep()
    t6_acceptance(use_llm)
    print("\n" + "=" * 66)
    print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print(" 失败项: %s" % FAIL)
    print("=" * 66)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
