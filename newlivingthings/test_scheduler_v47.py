# test_scheduler_v47.py
# -*- coding: utf-8 -*-
"""
test_scheduler_v47.py —— 熵灵 V4.7 情绪-生存双核调度 · 验收测试

覆盖：
  T1 五档矩阵判定（含边界值与优先级短路）
  T2 [内核调度] 日志四要素：状态(..)，分配算力(..)，超时设置(..)，启用工具(..)
  T3 物理拦截：max_tokens 在 provider 层被截断；timeout 真的传给 call_bridge
  T4 躁狂濒死态 timeout 必须为 3 秒（真机验证：桥接记录的实参）
  T5 禁用工具的档位一条网络请求都不发出
  T6 robust_json_parse 防崩

约定：AC_DB_PATH / AC_DEAD_LOCK 指向临时目录；不发真实外网请求。
用法：python test_scheduler_v47.py
"""
import io
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="ac_sched_")
os.environ["AC_DB_PATH"] = os.path.join(_TMP, "sched.db")
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


class RecordingProvider:
    """记录每次 chat 收到的 max_tokens 与回复。"""

    def __init__(self, reply='{"introspection": "ok", "action": "idle"}'):
        self.reply = reply
        self.calls = []
        self.model = "fake"

    def chat(self, messages, temperature=0.7, max_tokens=500):
        self.calls.append({"temperature": temperature, "max_tokens": max_tokens,
                           "prompt": messages[0]["content"] if messages else ""})
        return self.reply


class FakeSoul:
    """最小 soul 桩：带真实 spend/heal 语义，供计费测试使用。"""

    def __init__(self, vitality):
        self.vitality = int(vitality)
        self.spent = []

    def spend(self, amount, reason=""):
        self.vitality = max(0, self.vitality - int(amount))
        self.spent.append((int(amount), reason))
        return self.vitality

    def heal(self, amount, reason=""):
        self.vitality = min(100, self.vitality + int(amount))
        return self.vitality


def make_life(endo, vitality):
    import main
    life = main.EntropyLife.__new__(main.EntropyLife)
    life.interactive = True
    life._init_endocrine()
    life.endo.update(endo)
    life.endo["curiosity"] = 0.1
    life._last_endo = life.mood()
    life._last_recent_log = []
    life._pending_tool_results = []
    life._strategy = None
    life._chat_max_tokens = None
    life.soul = FakeSoul(vitality)

    class _Mem:
        def add_short_colored(self, *a, **k): return "neutral"
        def add_permanent(self, *a, **k): pass
        def search(self, k): return None

    prov = RecordingProvider()

    class _Sys:
        memory = _Mem()

    class _LM:
        pass

    _LM.provider = prov
    life.system = _Sys()
    _Sys.language_model = _LM
    life.engine = type("E", (), {"save": staticmethod(lambda: None)})()
    return life, prov


# ---------------- 五档样例 ----------------
STATES = [
    ("濒死恐慌态", {"dopamine": 0.3, "cortisol": 0.9, "endorphin": 0.2}, 10, 80, None, False),
    ("躁狂濒死态", {"dopamine": 0.9, "cortisol": 0.5, "endorphin": 0.3}, 25, 200, 3.0, True),
    ("高压内耗态", {"dopamine": 0.4, "cortisol": 0.9, "endorphin": 0.3}, 35, 100, 5.0, True),
    ("亢奋探索态", {"dopamine": 0.9, "cortisol": 0.2, "endorphin": 0.6}, 95, 500, 15.0, True),
    ("常规平稳态", {"dopamine": 0.5, "cortisol": 0.5, "endorphin": 0.4}, 60, 150, 10.0, True),
]


def t1_matrix():
    print("\n[T1] 五档矩阵判定 + 边界值")
    for name, endo, v, mt, to, tool in STATES:
        res = soul_core.evaluate_resource_strategy(v, endo)
        check("T1 %s 判定" % name, res["tier"] == name, "(got=%s)" % res["tier"])
        check("T1 %s 算力=%d" % (name, mt), res["max_tokens"] == mt, "(got=%s)" % res["max_tokens"])
        check("T1 %s 超时=%s" % (name, to), res["timeout"] == to, "(got=%s)" % res["timeout"])
        check("T1 %s 工具=%s" % (name, tool), res["tool_enabled"] is tool,
              "(got=%s)" % res["tool_enabled"])

    # 边界：vitality=20 属于高压内耗（C=0.9），不是濒死恐慌
    r = soul_core.evaluate_resource_strategy(20, {"dopamine": 0.3, "cortisol": 0.9})
    check("T1 边界 v=20,C=0.9 -> 高压内耗", r["tier"] == "高压内耗态", r["tier"])
    # 边界：vitality=19 且 C=0.9 -> 濒死恐慌
    r = soul_core.evaluate_resource_strategy(19, {"dopamine": 0.3, "cortisol": 0.9})
    check("T1 边界 v=19,C=0.9 -> 濒死恐慌", r["tier"] == "濒死恐慌态", r["tier"])
    # 优先级：v=19, D=0.95, C=0.9 同时满足①②，但①优先
    r = soul_core.evaluate_resource_strategy(19, {"dopamine": 0.95, "cortisol": 0.9})
    check("T1 优先级 ①先于②", r["tier"] == "濒死恐慌态", r["tier"])
    # 边界：v=50,C=0.9 -> 高压内耗；v=51,C=0.9 -> 常规
    check("T1 边界 v=50 -> 高压内耗",
          soul_core.evaluate_resource_strategy(50, {"cortisol": 0.9})["tier"] == "高压内耗态")
    check("T1 边界 v=51 -> 常规",
          soul_core.evaluate_resource_strategy(51, {"cortisol": 0.9})["tier"] == "常规平稳态")
    # 边界：v=81 且 D=0.75,C=0.3 -> 亢奋；v=80 -> 常规
    check("T1 边界 v=81 亢奋",
          soul_core.evaluate_resource_strategy(81, {"dopamine": 0.75, "cortisol": 0.3})["tier"] == "亢奋探索态")
    check("T1 边界 v=80 常规",
          soul_core.evaluate_resource_strategy(80, {"dopamine": 0.75, "cortisol": 0.3})["tier"] == "常规平稳态")
    check("T1 数值异常不崩", soul_core.evaluate_resource_strategy("x", {"dopamine": "y"})["tier"] == "常规平稳态")


def t2_log():
    print("\n[T2] [内核调度] 日志四要素")
    buf = io.StringIO()
    old = sys.stdout
    try:
        sys.stdout = buf
        for name, endo, v, mt, to, tool in STATES:
            life, _ = make_life(endo, v)
            life._strategy = None      # 强制重新打印
            life.evaluate_resource_strategy()
    finally:
        sys.stdout = old
    out = buf.getvalue()
    for line in out.strip().splitlines():
        print("  | " + line)
    for name, endo, v, mt, to, tool in STATES:
        to_s = ("%gs" % to) if to is not None else "禁用"
        needle = "[内核调度] 状态(%s)，分配算力(max_tokens=%d)，超时设置(timeout=%s)，启用工具(%s)" % (
            name, mt, to_s, "是" if tool else "否")
        check("T2 日志 %s" % name, needle in out, "" if needle in out else "缺少: " + needle)
    check("T2 四条要素齐全", out.count("状态(") == len(STATES) and "分配算力(max_tokens=" in out
          and "超时设置(timeout=" in out and "启用工具(" in out)


def t3_physical():
    print("\n[T3] 物理拦截：算力硬顶 / 超时实参")
    # 算力：provider 层把 99999 压到本档位上限
    for name, endo, v, mt, to, tool in STATES:
        life, prov = make_life(endo, v)
        life._init_resource_kernel()
        life._refresh_resource_strategy()
        life.system.language_model.provider.chat([{"role": "user", "content": "x"}], max_tokens=99999)
        got = prov.calls[-1]["max_tokens"]
        check("T3 算力硬顶 %s -> %d" % (name, mt), got == mt, "(传入 99999，实到 %d)" % got)

    # 原生 Ollama 路径：model_provider 内部有 num_predict=max(max_tokens,256) 的下限，
    # 包裹层必须先把入参压到 80，否则 80 会在这里被反向抬高
    for name, endo, v, mt, to, tool in STATES:
        life, _ = make_life(endo, v)
        life._init_resource_kernel()
        life._refresh_resource_strategy()
        bounded = life.system.language_model.provider
        seen = {}
        bounded._inner._chat_native = lambda m, t, mt_: seen.update(v=mt_) or ""
        bounded._chat_native([{"role": "user", "content": "x"}], 0.3, 99999)
        effective = max(seen.get("v", 0), 256)      # 复现底层下限
        check("T3 原生路径 %s 不越硬顶" % name, effective <= max(mt, 256), "")

    # 超时：call_bridge 真的收到 3 秒
    import tool_caller
    recorded = {}
    orig = tool_caller.call_bridge
    try:
        def fake_bridge(task, timeout=None):
            recorded["timeout"] = timeout
            return {"ok": True, "result": "喵", "error": "", "elapsed": 0.1}
        tool_caller.call_bridge = fake_bridge
        endo = {"dopamine": 0.9, "cortisol": 0.5, "endorphin": 0.3}
        life, _ = make_life(endo, 25)
        life._maybe_call_tools("[CALL_TOOL] 去看一眼 GitHub", "场景")
        check("T3 躁狂濒死 -> call_bridge 收到 timeout=3", recorded.get("timeout") == 3.0,
              "(got=%s)" % recorded.get("timeout"))
    finally:
        tool_caller.call_bridge = orig


def t4_manic_three_seconds():
    print("\n[T4] 及格线：躁狂濒死态超时必须是 3 秒")
    endo = {"dopamine": 0.9, "cortisol": 0.5, "endorphin": 0.3}
    res = soul_core.evaluate_resource_strategy(25, endo)
    check("T4.1 档位=躁狂濒死态", res["tier"] == "躁狂濒死态", res["tier"])
    check("T4.2 timeout == 3.0", res["timeout"] == 3.0, "(got=%s)" % res["timeout"])
    check("T4.3 max_tokens == 200", res["max_tokens"] == 200, "(got=%s)" % res["max_tokens"])
    check("T4.4 允许工具", res["tool_enabled"] is True)
    check("T4.5 注入文案含『认命』", "认命" in res["prompt"], res["prompt"][:40])


def t5_no_network():
    print("\n[T5] 濒死恐慌态：一条网络请求都不发出")
    import tool_caller
    called = []
    orig_b = tool_caller.call_bridge
    orig_r = tool_caller.run_real_world
    try:
        tool_caller.call_bridge = lambda *a, **k: called.append("bridge") or {"ok": True, "result": "x"}
        tool_caller.run_real_world = lambda *a, **k: called.append("realworld") or {"ok": True, "result": "x"}
        endo = {"dopamine": 0.3, "cortisol": 0.9, "endorphin": 0.2}
        life, _ = make_life(endo, 10)
        out = life._maybe_call_tools("[CALL_TOOL] 去看一眼 GitHub", "场景")
        check("T5.1 工具被拦截", called == [], "(发出=%s)" % called)
        check("T5.2 返回被拦截的结果", bool(out) and not out[0]["ok"], str(out)[:80])
        # 真实互联网也拦
        life.endo["curiosity"] = 0.95
        r = life._maybe_touch_real_world()
        check("T5.3 真实互联网被拦截", called == [], "(发出=%s)" % called)
        check("T5.4 未出网返回 None", r is None)
        # 无 Prompt 注入（保命靠代码，不靠嘱咐）
        res = soul_core.evaluate_resource_strategy(10, endo)
        check("T5.5 濒死恐慌态不自称注入", res["prompt_allowed"] is False)
    finally:
        tool_caller.call_bridge = orig_b
        tool_caller.run_real_world = orig_r


def t6_robust():
    print("\n[T6] robust_json_parse 防崩")
    endo = {"dopamine": 0.3, "cortisol": 0.9}
    s = soul_core.evaluate_resource_strategy(10, endo)
    p = soul_core.build_survival_prompt(endo, "工具调用失败", s)
    check("T6.1 濒死恐慌态 Prompt 无注入", "生存约束" not in p)
    s2 = soul_core.evaluate_resource_strategy(25, {"dopamine": 0.9})
    p2 = soul_core.build_survival_prompt({"dopamine": 0.9}, "工具调用失败", s2)
    check("T6.2 躁狂态 Prompt 有注入", "认命" in p2)
    prov = RecordingProvider("模型跑飞了，什么 JSON 都没有")
    r = soul_core.interpret_event(endo, "工具调用失败", prov, log=lambda m: None)
    check("T6.3 非 JSON 回复降级不崩", r["introspection"] == "（大脑宕机）", r["introspection"])


def t7_wiring():
    print("\n[T7] 主链路打通：生存文案注入 + 生命值计费")
    # 7.1 档位文案真的拼进 _psych_narrate 的 Prompt
    import config
    endo = {"dopamine": 0.9, "cortisol": 0.5, "endorphin": 0.3}
    life, prov = make_life(endo, 25)
    life._init_resource_kernel()
    life._refresh_resource_strategy()
    bounded = life.system.language_model.provider
    captured = []
    bounded._inner.chat = lambda m, temperature=0.7, max_tokens=500: captured.append(
        m[0]["content"]) or '{"introspection": "ok", "action": "idle"}'
    life._psych_narrate("工具调用失败")
    sent = captured[-1] if captured else ""
    check("T7.1 躁狂态文案进入 Prompt", "认命" in sent, "(snippet=%r)" % sent[-60:])
    check("T7.2 同时保留纯数值与词典", "多巴胺(D)" in sent and "生物学词典" in sent)
    check("T7.3 无表演词汇", soul_core.audit_prompt(sent.split("生存约束")[0]) == [])

    # 7.4 濒死恐慌态不注入
    life2, prov2 = make_life({"dopamine": 0.3, "cortisol": 0.9}, 10)
    life2._init_resource_kernel()
    life2._refresh_resource_strategy()
    cap2 = []
    life2.system.language_model.provider._inner.chat = lambda m, temperature=0.7, max_tokens=500: cap2.append(
        m[0]["content"]) or '{"introspection": "ok", "action": "idle"}'
    life2._psych_narrate("工具调用失败")
    check("T7.4 濒死恐慌态不注入表演文案", "生存约束" not in (cap2[-1] if cap2 else "x"))

    # 7.5 VITALITY_COST_LLM 接线：第 2 次思考开始扣血
    old_cost = config.VITALITY_COST_LLM
    old_free = getattr(config, "VITALITY_LLM_FREE_CALLS", 1)
    try:
        config.VITALITY_COST_LLM = 1
        config.VITALITY_LLM_FREE_CALLS = 1
        life3, _ = make_life({"dopamine": 0.5, "cortisol": 0.5}, 50)
        life3._init_resource_kernel()
        life3._refresh_resource_strategy()
        life3._llm_calls_this_round = 0
        life3._pending_death = False
        p3 = life3.system.language_model.provider
        p3.chat([{"role": "user", "content": "a"}], max_tokens=10)   # 免费
        v_after_free = life3.soul.vitality
        check("T7.5 第 1 次思考免费", v_after_free == 50, "(v=%s)" % v_after_free)
        p3.chat([{"role": "user", "content": "b"}], max_tokens=10)   # 扣 1
        check("T7.6 第 2 次思考扣血", life3.soul.vitality == 49, "(v=%s)" % life3.soul.vitality)
        p3.chat([{"role": "user", "content": "c"}], max_tokens=10)
        check("T7.7 第 3 次思考继续扣血", life3.soul.vitality == 48, "(v=%s)" % life3.soul.vitality)

        # 7.8 配置为 0 则不扣
        config.VITALITY_COST_LLM = 0
        life4, _ = make_life({"dopamine": 0.5, "cortisol": 0.5}, 50)
        life4._init_resource_kernel(); life4._refresh_resource_strategy()
        life4._llm_calls_this_round = 0
        p4 = life4.system.language_model.provider
        for _ in range(3):
            p4.chat([{"role": "user", "content": "x"}], max_tokens=10)
        check("T7.8 COST_LLM=0 时不扣血", life4.soul.vitality == 50, "(v=%s)" % life4.soul.vitality)

        # 7.9 扣到 0 时标记死亡待处理（不在网络栈里直接退出）
        config.VITALITY_COST_LLM = 1
        life5, _ = make_life({"dopamine": 0.5, "cortisol": 0.5}, 2)
        life5._init_resource_kernel(); life5._refresh_resource_strategy()
        life5._llm_calls_this_round = 0
        life5._pending_death = False
        p5 = life5.system.language_model.provider
        p5.chat([{"role": "user", "content": "x"}], max_tokens=10)   # 免费
        p5.chat([{"role": "user", "content": "y"}], max_tokens=10)   # -1 -> 1
        p5.chat([{"role": "user", "content": "z"}], max_tokens=10)   # -1 -> 0
        check("T7.9 思考耗尽生命后标记死亡待处理",
              life5.soul.vitality == 0 and getattr(life5, "_pending_death", False) is True,
              "(v=%s pending=%s)" % (life5.soul.vitality, getattr(life5, "_pending_death", None)))
    finally:
        config.VITALITY_COST_LLM = old_cost
        config.VITALITY_LLM_FREE_CALLS = old_free

    # 7.10 idle 回血已置 0
    check("T7.10 VITALITY_GAIN_IDLE == 0", int(getattr(config, "VITALITY_GAIN_IDLE", -1)) == 0,
          "(=%s)" % getattr(config, "VITALITY_GAIN_IDLE", None))


def main():
    print("=" * 70)
    print(" 熵灵 V4.7 情绪-生存双核调度 · 验收测试")
    print("=" * 70)
    t1_matrix()
    t2_log()
    t3_physical()
    t4_manic_three_seconds()
    t5_no_network()
    t6_robust()
    t7_wiring()
    print("\n" + "=" * 70)
    print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print(" 失败项: %s" % FAIL)
    print("=" * 70)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
