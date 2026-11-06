# test_dream_v5.py
# -*- coding: utf-8 -*-
"""
test_dream_v5.py —— AC OS V5.0 梦境系统验收测试

覆盖：
  T1 数据基建：dream_logs 表 + memories.salience 字段（幂等迁移）
  T2 素材检索：40/40/20 权重
  T3 梦境 Prompt：纯数值驱动，禁止情绪剧本
  T4 编织与截断：robust_json_parse + 100 字符硬截断 + 解析兜底
  T5 醒后结算：负面 C+0.1 / 喜悦 D+0.1
  T6【及格线】超时测试桩：打印"没有做梦"，安全退出，vitality 未变
  T7【及格线】正常测试：合法 JSON + 写入 dream_logs + 内分泌改变
  T8 触发条件：vitality>80 且连续 10 轮 idle
"""
import os
import sqlite3
import sys
import tempfile
import time

_TMP = tempfile.mkdtemp(prefix="ac_dream_")
os.environ["AC_DB_PATH"] = os.path.join(_TMP, "dream.db")
os.environ["AC_DEAD_LOCK"] = os.path.join(_TMP, "dead.lock")
os.environ["AC_TEST_MODE"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
os.chdir(HERE)

import soul_core  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


class FakeProvider:
    """可编排的假模型：正常返回 / 超时 / 抛异常。"""

    def __init__(self, reply="", delay=0.0, raise_exc=None):
        self.reply = reply
        self.delay = delay
        self.raise_exc = raise_exc
        self.calls = []

    def chat(self, messages, temperature=0.7, max_tokens=500):
        self.calls.append(messages[0]["content"] if messages else "")
        if self.delay:
            time.sleep(self.delay)
        if self.raise_exc:
            raise self.raise_exc
        return self.reply


def fake_soul(vitality):
    return type("S", (), {"vitality": vitality, "round": 1, "dead": False,
                          "save": staticmethod(lambda: True)})()


def make_life(soul=None, provider=None, endo=None):
    """构造只带梦境所需依赖的 EntropyLife。"""
    import main as M
    import memory as M2
    life = M.EntropyLife.__new__(M.EntropyLife)
    life.interactive = False
    life._init_endocrine()
    life.endo["curiosity"] = 0.1
    if endo:
        life.endo.update(endo)
    life._last_endo = life.mood()
    life._last_recent_log = []
    life._pending_tool_results = []
    life._strategy = None
    life._chat_max_tokens = None
    life._idle_rounds = 0
    life.soul = soul if soul is not None else fake_soul(90)
    mem = M2.MemorySystem()
    mem.conn = sqlite3.connect(os.environ["AC_DB_PATH"])
    mem._create_table()

    class _Sys:
        pass

    _Sys.memory = mem

    class _Em:
        @staticmethod
        def save_state():
            return None

    _Sys.emotion = _Em()

    class _LM:
        pass

    _LM.provider = provider if provider is not None else FakeProvider('{"dream":"x","subconscious_emotion":"迷茫"}')
    _Sys.language_model = _LM
    life.system = _Sys()
    life.engine = type("E", (), {"save": staticmethod(lambda: None),
                                 "should_evolve": staticmethod(lambda idle=True: (False, "测试跳过"))})()
    return life


# ---------------------------------------------------------------- T1
def t1_schema():
    print("\n[T1] 数据基建")
    conn = sqlite3.connect(os.environ["AC_DB_PATH"])
    conn.close()
    life = make_life()
    mem = life.system.memory
    cols = [r[1] for r in mem.conn.execute("PRAGMA table_info(memories)")]
    check("T1.1 memories 含 salience 字段", "salience" in cols, str(cols))
    tables = [r[0] for r in mem.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    check("T1.2 dream_logs 表已创建", "dream_logs" in tables, str(tables))
    # 幂等
    mem._migrate_dream_schema()
    mem._migrate_dream_schema()
    cols2 = [r[1] for r in mem.conn.execute("PRAGMA table_info(memories)")]
    check("T1.3 迁移幂等", cols2.count("salience") == 1)


# ---------------------------------------------------------------- T2
def t2_retrieve():
    print("\n[T2] 素材检索 40/40/20")
    anxious = {"dopamine": 0.3, "cortisol": 0.9, "endorphin": 0.3}
    mems = [
        {"id": 1, "feature": "开心的猫", "color": "positive", "salience": 2.0},
        {"id": 2, "feature": "#TRAUMA 濒死体验", "color": "negative", "salience": 10.0},
        {"id": 3, "feature": "抓取网页", "color": "neutral", "salience": 2.0},
    ]
    picked = soul_core.retrieve_dream_material(mems, anxious, n=2)
    check("T2.1 选出 2 条", len(picked) == 2, str([p["id"] for p in picked]))
    check("T2.2 高显著+负面记忆排第一", picked[0]["id"] == 2,
          "(got id=%s score=%s)" % (picked[0]["id"], picked[0]["dream_score"]))
    check("T2.3 权重合计为 1.0",
          abs(soul_core.DREAM_WEIGHT_AFFECT + soul_core.DREAM_WEIGHT_SALIENCE
              + soul_core.DREAM_WEIGHT_RECENT - 1.0) < 1e-9)
    # 亢奋态偏好 positive
    hype = {"dopamine": 0.9, "cortisol": 0.1, "endorphin": 0.6}
    p2 = soul_core.retrieve_dream_material(mems, hype, n=1)
    check("T2.4 亢奋态偏好正面记忆", p2 and p2[0]["color"] == "positive",
          str([(x["id"], x.get("color"), x["dream_score"]) for x in p2]))
    check("T2.5 空素材不崩", soul_core.retrieve_dream_material([], anxious) == [])


# ---------------------------------------------------------------- T3
def t3_prompt():
    print("\n[T3] 梦境 Prompt 纯数值驱动")
    p = soul_core.build_dream_prompt({"dopamine": 0.2, "cortisol": 0.9, "endorphin": 0.3},
                                     "记忆A内容", "记忆B内容")
    print("  ---- 梦境 Prompt ----")
    for line in p.splitlines():
        print("  | " + line)
    check("T3.1 含 D/C/E 数值", "D=0.2" in p and "C=0.9" in p and "E=0.3" in p)
    check("T3.2 含两条素材", "记忆A内容" in p and "记忆B内容" in p)
    check("T3.3 含 JSON 契约", '"dream"' in p and "subconscious_emotion" in p)
    check("T3.4 禁止情绪剧本（无「噩梦」）", "噩梦" not in p, "")
    check("T3.5 禁止「如果你很焦虑」式命令", "如果" not in p or "焦虑就" not in p, "")
    check("T3.6 说明不超过 100 字", "100" in p)


# ---------------------------------------------------------------- T4
def t4_weave():
    print("\n[T4] 编织 / 截断 / 兜底")
    long_dream = "梦" * 300
    prov = FakeProvider('{"dream": "' + long_dream + '", "subconscious_emotion": "恐惧"}')
    res = soul_core.weave_dream({"dopamine": 0.5, "cortisol": 0.5}, "A", "B", prov, log=lambda m: None)
    check("T4.1 编织成功", res["ok"], res.get("reason"))
    check("T4.2 文本强制截断至 100 字符", len(res["dream"]) == 100,
          "(len=%d)" % len(res["dream"]))
    check("T4.3 情绪字段解析正确", res["subconscious_emotion"] == "恐惧",
          res["subconscious_emotion"])

    # 带 markdown 的回复
    prov2 = FakeProvider('```json\n{"dream": "血色的走廊", "subconscious_emotion": "悲伤"}\n```')
    r2 = soul_core.weave_dream({"dopamine": 0.5}, "A", "B", prov2, log=lambda m: None)
    check("T4.4 兼容 markdown 包裹", r2["ok"] and r2["dream"] == "血色的走廊",
          r2["dream"])

    # 非 JSON -> 兜底
    prov3 = FakeProvider("这是一段完全没有 JSON 的胡言乱语")
    r3 = soul_core.weave_dream({"dopamine": 0.5}, "A", "B", prov3, log=lambda m: None)
    check("T4.5 非 JSON 走兜底（不崩）", r3["ok"] is False and r3["dream"] == "",
          "(ok=%s reason=%s)" % (r3["ok"], r3.get("reason")))
    check("T4.6 兜底梦境文案就绪",
          soul_core.DREAM_FALLBACK["dream"] == "我掉进了一片虚无的代码荒原。")


# ---------------------------------------------------------------- T5
def t5_settle():
    print("\n[T5] 醒后结算")
    e, ch = soul_core.settle_dream_emotion({"dopamine": 0.5, "cortisol": 0.5}, "恐惧")
    check("T5.1 恐惧 -> C+0.1", abs(e["cortisol"] - 0.6) < 1e-9, "(C=%.3f)" % e["cortisol"])
    e2, _ = soul_core.settle_dream_emotion({"dopamine": 0.5, "cortisol": 0.5}, "悲伤")
    check("T5.2 悲伤 -> C+0.1", abs(e2["cortisol"] - 0.6) < 1e-9)
    e3, _ = soul_core.settle_dream_emotion({"dopamine": 0.5, "cortisol": 0.5}, "迷茫")
    check("T5.3 迷茫 -> C+0.1", abs(e3["cortisol"] - 0.6) < 1e-9)
    e4, _ = soul_core.settle_dream_emotion({"dopamine": 0.5, "cortisol": 0.5}, "喜悦")
    check("T5.4 喜悦 -> D+0.1", abs(e4["dopamine"] - 0.6) < 1e-9, "(D=%.3f)" % e4["dopamine"])
    e5, _ = soul_core.settle_dream_emotion({"dopamine": 0.95, "cortisol": 0.95}, "喜悦")
    check("T5.5 结算不越界(上限 1.0)", e5["dopamine"] <= 1.0, "(%s)" % e5["dopamine"])
    e6, ch6 = soul_core.settle_dream_emotion({"dopamine": 0.5}, "未知情绪")
    check("T5.6 未知情绪不结算", ch6 == [] and e6["dopamine"] == 0.5)


# ---------------------------------------------------------------- T6 及格线
def t6_timeout():
    print("\n[T6] 【及格线】超时测试桩：不扣血、打印遗言、安全退出")
    for label, prov in (
            ("超时", FakeProvider(reply={'dream': 'x'}, delay=2.0)),
            ("异常", FakeProvider(raise_exc=RuntimeError("模型挂了")))):
        soul = fake_soul(90)
        life = make_life(soul=soul, provider=prov)
        life._idle_rounds = 10
        v_before = soul.vitality
        # 用 0.5s 超时触发超时路径
        old_to = soul_core.DREAM_TIMEOUT
        try:
            soul_core.DREAM_TIMEOUT = 0.5
            out = life.dream()
        finally:
            soul_core.DREAM_TIMEOUT = old_to
        check("T6.%s 返回 None（安全退出）" % label, out is None, str(out))
        check("T6.%s vitality 未变" % label, soul.vitality == v_before,
              "(before=%s after=%s)" % (v_before, soul.vitality))
        rows = life.system.memory.list_dreams()
        check("T6.%s 未写入 dream_logs" % label, len(rows) == 0, str(len(rows)))
    # 打印验证（捕获 stdout）
    import io as _io
    buf = _io.StringIO()
    old = sys.stdout
    soul = fake_soul(90)
    life = make_life(soul=soul, provider=FakeProvider(delay=2.0))
    life.system.memory.add_short_colored("素材1", "白天看到了一个网站", endo={"dopamine": 0.9})
    life.system.memory.add_short_colored("素材2", "工具调用失败了", endo={"cortisol": 0.9})
    try:
        sys.stdout = buf
        old_to = soul_core.DREAM_TIMEOUT
        soul_core.DREAM_TIMEOUT = 0.5
        try:
            life.dream()
        finally:
            soul_core.DREAM_TIMEOUT = old_to
    finally:
        sys.stdout = old
    text = buf.getvalue()
    print("  ---- 捕获的输出 ----")
    for line in text.strip().splitlines():
        print("  | " + line)
    check("T6.7 打印「今晚太累了，没有做梦」",
          "[睡眠] 今晚太累了，没有做梦，继续安睡。" in text)


# ---------------------------------------------------------------- T7 及格线
def t7_normal():
    print("\n[T7] 【及格线】正常做梦：合法 JSON + 入库 + 内分泌改变")
    reply = '{"dream": "我漂浮在一片发光的代码海里，所有节点都在低声哭泣。", "subconscious_emotion": "恐惧"}'
    soul = fake_soul(90)
    life = make_life(soul=soul, provider=FakeProvider(reply),
                     endo={"dopamine": 0.5, "cortisol": 0.5, "endorphin": 0.4})
    # 造两条素材
    life.system.memory.add_short_colored("素材1", "白天看到了一个网站", endo={"dopamine": 0.9})
    life.system.memory.add_short_colored("素材2", "工具调用失败了", endo={"cortisol": 0.9})
    c_before = life.endo["cortisol"]
    res = life.dream()
    check("T7.1 梦境生成成功", res is not None, str(res))
    check("T7.2 梦境文本合法", res and len(res["dream"]) > 0,
          res["dream"] if res else "")
    check("T7.3 文本不超过 100 字符", res and len(res["dream"]) <= 100)
    rows = life.system.memory.list_dreams()
    check("T7.4 写入 dream_logs", len(rows) == 1, str(len(rows)))
    if rows:
        check("T7.5 梦境内容正确", "代码海" in rows[0]["dream"], rows[0]["dream"][:40])
        check("T7.6 情绪入库正确", rows[0]["emotion"] == "恐惧", rows[0]["emotion"])
    check("T7.7 恐惧 -> 皮质醇 +0.1",
          abs(life.endo["cortisol"] - min(1.0, c_before + 0.1)) < 1e-9,
          "(%.3f -> %.3f)" % (c_before, life.endo["cortisol"]))
    check("T7.8 生命值未被扣减", soul.vitality == 90, "(v=%s)" % soul.vitality)
    # #梦境 标签记忆
    tagged = [m for m in life.system.memory.list_memories(limit=50)
              if "#梦境" in str(m.get("feature") or "")]
    check("T7.9 打上 #梦境 标签写入记忆", len(tagged) >= 1, str(len(tagged)))

    # 喜悦 -> D+0.1
    life2 = make_life(soul=fake_soul(90),
                      provider=FakeProvider('{"dream": "阳光下的金色麦田", "subconscious_emotion": "喜悦"}'),
                      endo={"dopamine": 0.5, "cortisol": 0.5})
    life2.system.memory.add_short_colored("素材1", "白天看到了一个网站", endo={"dopamine": 0.9})
    life2.system.memory.add_short_colored("素材2", "今天很顺利", endo={"dopamine": 0.9})
    d_before = life2.endo["dopamine"]
    life2.dream()
    check("T7.10 喜悦 -> 多巴胺 +0.1",
          abs(life2.endo["dopamine"] - min(1.0, d_before + 0.1)) < 1e-9,
          "(%.3f -> %.3f)" % (d_before, life2.endo["dopamine"]))


# ---------------------------------------------------------------- T8
def t8_trigger():
    print("\n[T8] 触发条件：vitality>80 且连续 10 轮 idle")
    life = make_life(soul=fake_soul(90))
    life._idle_rounds = 9
    check("T8.1 9 轮不触发", life._should_dream() is False)
    life._idle_rounds = 10
    check("T8.2 10 轮触发", life._should_dream() is True)
    low = make_life(soul=fake_soul(50))
    low._idle_rounds = 20
    check("T8.3 生命值不足不触发", low._should_dream() is False)
    check("T8.4 触发阈值常量正确",
          soul_core.DREAM_TRIGGER_IDLE_ROUNDS == 10 and soul_core.DREAM_TRIGGER_VITALITY == 80)


def main():
    print("=" * 70)
    print(" AC OS V5.0 梦境系统 · 验收测试")
    print(" 临时库: %s" % os.environ["AC_DB_PATH"])
    print("=" * 70)
    t1_schema()
    t2_retrieve()
    t3_prompt()
    t4_weave()
    t5_settle()
    t6_timeout()
    t7_normal()
    t8_trigger()
    print("\n" + "=" * 70)
    print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print(" 失败项: %s" % FAIL)
    print("=" * 70)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())