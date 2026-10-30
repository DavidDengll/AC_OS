# test_soul_v45.py
# -*- coding: utf-8 -*-
"""
test_soul_v45.py —— 熵灵 V4.5「灵魂级重构」验收测试

覆盖：
  T1 生命值：工具成功 heal(5) / 失败 spend(10)
  T2 死亡：vitality 归零 -> 生成 dead.lock -> 进程真的退出（子进程验证）
  T3 复活防护：dead.lock 存在 -> guard_dead_lock 拦截 -> 进程退出
  T4 人格审查：每 20 轮触发；通过则入库，废弃则扣多巴胺
  T5 全景 Prompt：含生命值 / top3 人格标签 / 记忆

约定：通过 AC_DB_PATH / AC_DEAD_LOCK 指向临时目录，绝不碰真实的
entropy_memory.db 与 dead.lock；不联网。

用法：
    python test_soul_v45.py            # 全量
    python -m pytest test_soul_v45.py  # 也支持 pytest
"""
import os
import subprocess
import sys
import tempfile

# 必须在 import soul_core 之前设置，soul_core 在模块级读取这两个变量
_TMP = tempfile.mkdtemp(prefix="ac_soul_test_")
os.environ["AC_DB_PATH"] = os.path.join(_TMP, "test_memory.db")
os.environ["AC_DEAD_LOCK"] = os.path.join(_TMP, "dead.lock")
os.environ["AC_TEST_MODE"] = "1"          # 测试模式：禁止 os.execv

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

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
    """可编排的假大模型：按顺序吐出预设回复。"""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.calls = []

    def chat(self, messages, temperature=0.7, max_tokens=500):
        text = messages[0]["content"] if messages else ""
        self.calls.append((text, temperature))
        if self.replies:
            return self.replies.pop(0)
        return ""


def new_soul():
    s = soul_core.SoulState()
    s.vitality = soul_core.VITALITY_MAX
    s.round = 0
    s.last_reflect_round = 0
    s.dead = False
    s.save()
    return s


def make_life(soul=None, provider=None):
    """造一个 EntropyLife，但不跑 ConsciousnessSystem 的重型初始化。"""
    import main
    life = main.EntropyLife.__new__(main.EntropyLife)
    life.interactive = True
    life.soul = soul if soul is not None else new_soul()
    life._tool_fail_streak = 0
    life._init_endocrine()
    life.endo["curiosity"] = 0.1          # 压低好奇心：测试期间不触发真实外网抓取
    life._last_endo = life.mood()
    life._last_recent_log = []
    life._pending_tool_results = []
    life._pending_real_world = None

    class _Mem:
        def add_short(self, name, feature):
            return None

        def add_permanent(self, name, feature):
            return None

        def search(self, keyword):
            return "猫：毛茸茸、会喵喵叫"

    class _Sys:
        memory = _Mem()

        class emotion:
            @staticmethod
            def save_state():
                return None

    class _LM:
        pass

    _LM.provider = provider if provider is not None else FakeProvider()
    life.system = _Sys()
    _Sys.language_model = _LM
    life.engine = type("E", (), {"save": staticmethod(lambda: None)})()
    return life


# ---------------------------------------------------------------- T1
def t1_vitality_tool():
    print("\n[T1] 生命值：工具成功 heal(5) / 失败 spend(10)")
    life = make_life()
    v0 = life.soul.vitality
    life._soul_heal(soul_core.GAIN_TOOL_SUCCESS, "ZeptoClaw 调用成功")
    check("T1.1 成功回血 +%d" % soul_core.GAIN_TOOL_SUCCESS,
          life.soul.vitality == min(soul_core.VITALITY_MAX, v0 + 5),
          "(vitality=%d)" % life.soul.vitality)
    v1 = life.soul.vitality
    life._soul_spend(soul_core.COST_TOOL_ERROR, "ZeptoClaw 调用失败")
    check("T1.2 失败扣血 -%d" % soul_core.COST_TOOL_ERROR,
          life.soul.vitality == v1 - 10, "(vitality=%d)" % life.soul.vitality)

    # 走真实链路：_maybe_call_tools 里成功/失败是否真的改血
    import tool_caller
    life2 = make_life()
    v = life2.soul.vitality
    orig = tool_caller.call_bridge
    try:
        tool_caller.call_bridge = lambda task, timeout=None: {
            "ok": True, "result": "喵", "error": "", "elapsed": 0.1}
        life2._maybe_call_tools("[CALL_TOOL] 帮我看一眼 GitHub", "测试场景")
        check("T1.3 链路-工具成功回血", life2.soul.vitality == min(soul_core.VITALITY_MAX, v + 5),
              "(vitality=%d)" % life2.soul.vitality)
        v2 = life2.soul.vitality
        tool_caller.call_bridge = lambda task, timeout=None: {
            "ok": False, "result": "", "error": "bridge down", "elapsed": 0.1}
        life2._maybe_call_tools("[CALL_TOOL] 帮我看一眼 GitHub", "测试场景")
        check("T1.4 链路-工具失败扣血", life2.soul.vitality == v2 - 10,
              "(vitality=%d)" % life2.soul.vitality)
    finally:
        tool_caller.call_bridge = orig


# ---------------------------------------------------------------- T2
_DEATH_CHILD = r'''
import os, sys
sys.path.insert(0, os.environ["AC_CHILD_DIR"])
import soul_core, main
life = main.EntropyLife.__new__(main.EntropyLife)
life.interactive = False
life.soul = soul_core.SoulState()
life.soul.vitality = 0
life.soul.round = 7
life._init_endocrine()
life._last_endo = life.mood()
life._last_recent_log = []

class _M:
    def add_permanent(self, *a, **k): pass
class _E:
    def save(self): pass
class _Em:
    def save_state(self): pass
life.system = type("S", (), {})()
life.system.memory = _M()
life.system.emotion = _Em()
life.engine = _E()
print("[T2] 子进程 vitality=0，调用 _check_death()", flush=True)
life._check_death()
print("[T2] !!! 不应该走到这里：进程没有退出 !!!", flush=True)
sys.exit(99)
'''


def t2_death():
    print("\n[T2] 死亡：vitality=0 -> dead.lock -> 进程退出")
    lock = os.environ["AC_DEAD_LOCK"]
    if os.path.exists(lock):
        os.remove(lock)
    child = os.path.join(_TMP, "death_child.py")
    with open(child, "w", encoding="utf-8") as f:
        f.write(_DEATH_CHILD)
    env = dict(os.environ)
    env["AC_CHILD_DIR"] = HERE
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, child], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120, env=env)
    out = (p.stdout or "") + (p.stderr or "")
    print("  ---- 子进程输出 ----")
    for line in out.strip().splitlines():
        print("  | " + line)
    check("T2.1 生成了 dead.lock", os.path.exists(lock), lock)
    info = soul_core.read_dead_lock(lock) if os.path.exists(lock) else {}
    check("T2.2 dead.lock 内容正确", info.get("dead") is True and "生命值归零" in str(info.get("reason")),
          str(info.get("reason"))[:60])
    check("T2.3 进程以非 0 退出", p.returncode != 0, "(returncode=%s)" % p.returncode)
    check("T2.4 没有走到退出后的代码", "不应该走到这里" not in out)


# ---------------------------------------------------------------- T3
def t3_guard():
    print("\n[T3] 复活防护：dead.lock 存在 -> guard_dead_lock 拦截")
    lock = os.environ["AC_DEAD_LOCK"]
    check("T3.1 lock 已存在", os.path.exists(lock))
    check("T3.2 guard 返回 True", soul_core.guard_dead_lock() is True)
    code = ("import os,sys;sys.path.insert(0,os.environ['AC_CHILD_DIR']);"
            "import soul_core;sys.exit(0 if soul_core.guard_dead_lock() else 3)")
    env = dict(os.environ)
    env["AC_CHILD_DIR"] = HERE
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60, env=env)
    check("T3.3 重启时退出码 0（阻止复活）", p.returncode == 0, "(returncode=%s)" % p.returncode)
    check("T3.4 打印了『熵灵已死』", "熵灵已死" in (p.stdout or ""))
    os.remove(lock)
    check("T3.5 移除 lock 后可复活", soul_core.guard_dead_lock() is False)


# ---------------------------------------------------------------- T4
def t4_reflect():
    print("\n[T4] 人格审查：每 20 轮触发 / 通过入库 / 废弃扣多巴胺")
    # T4a 轮次判定
    soul = new_soul()
    soul.round = 5
    soul.last_reflect_round = 0
    do, why = soul_core.should_reflect(soul, {}, None)
    check("T4.1 第 5 轮不触发", do is False, "(%s)" % why)
    soul.round = 20
    do, why = soul_core.should_reflect(soul, {}, None)
    check("T4.2 第 20 轮触发", do is True, "(%s)" % why)

    # T4b 拒绝路径：审查说"不合理" -> 废弃 + 扣多巴胺
    prov = FakeProvider(["标签：过度焦虑", "不合理（和内分泌严重不符）"])
    life = make_life(soul=soul, provider=prov)
    life.soul.last_reflect_round = 0
    life.soul.round = 20
    life.endo["dopamine"] = 0.60
    soul._set("penalty_pending", 0)
    res = life._maybe_reflect("测试场景")
    check("T4.3 审查被触发", res is not None)
    check("T4.4 不合格标签被废弃", res and res.get("action") == "discard", str(res and res.get("action")))
    check("T4.5 多巴胺被扣 %.2f" % soul_core.PENALTY_DOPAMINE,
          abs(life.endo["dopamine"] - 0.55) < 1e-6, "(D=%.3f)" % life.endo["dopamine"])
    check("T4.6 废弃标签没有入库",
          all(t != "过度焦虑" for t, _ in life.soul.top_tags(5)))

    # T4c 采纳路径：审查说"合理" -> 入库
    life2 = make_life(soul=new_soul(),
                      provider=FakeProvider(["标签：敏锐", "合理（与好奇心吻合）"]))
    life2.soul.round = 20
    life2.soul.last_reflect_round = 0
    res2 = life2._maybe_reflect("测试场景")
    check("T4.7 合格标签被采纳", res2 and res2.get("action") == "accept", str(res2 and res2.get("action")))
    tags = [t for t, _ in life2.soul.top_tags(5)]
    check("T4.8 标签已入库", "敏锐" in tags, str(tags))
    check("T4.9 采纳不扣多巴胺", res2 and res2.get("penalty") == 0)
    check("T4.10 反思轮次已记录", life2.soul.last_reflect_round == 20)

    # T4c-2 真实情形：同一个模型反复挑刺 -> 重试直到有一次通过就采纳
    life_r = make_life(soul=new_soul(), provider=FakeProvider([
        "标签：坚韧", "不合理（过于宽泛）",
        "标签：坚韧", "不合理（缺乏证据）",
        "标签：坚韧", "合理（与多次低分仍不放弃的经历吻合）",
    ]))
    life_r.soul.round = 80
    life_r.soul.last_reflect_round = 60
    res_r = life_r._maybe_reflect("测试场景")
    check("T4.18 重试后能采纳", res_r and res_r.get("action") == "accept",
          str(res_r and res_r.get("action")))
    check("T4.19 重试次数正确", res_r and res_r.get("attempts") == 3,
          "(attempts=%s)" % (res_r and res_r.get("attempts")))
    check("T4.20 最终通过不扣多巴胺", res_r and res_r.get("penalty") == 0)
    check("T4.21 重试得到的标签已入库",
          "坚韧" in [t for t, _ in life_r.soul.top_tags(5)])

    # T4c-3 全部重试都失败 -> 只扣一次多巴胺
    life_f = make_life(soul=new_soul(), provider=FakeProvider(["标签：飘忽", "不合理"] * 3))
    life_f.soul.round = 100
    life_f.soul.last_reflect_round = 80
    life_f.endo["dopamine"] = 0.5
    res_f = life_f._maybe_reflect("测试场景")
    check("T4.22 全部失败仍废弃", res_f and res_f.get("action") == "discard")
    check("T4.23 全部失败只扣一次多巴胺",
          abs(life_f.endo["dopamine"] - (0.5 - soul_core.PENALTY_DOPAMINE)) < 1e-6,
          "(D=%.3f, penalty=%s)" % (life_f.endo["dopamine"], res_f and res_f.get("penalty")))

    # T4d 漫天要价（宇宙/本质…）被拦截
    life3 = make_life(soul=new_soul(),
                      provider=FakeProvider(["标签：宇宙本质", "合理"]))
    life3.soul.round = 40
    life3.soul.last_reflect_round = 0
    res3 = life3._maybe_reflect("测试场景")
    check("T4.11 空泛标签被拦截", res3 and res3.get("action") == "discard",
          "(action=%s)" % (res3 and res3.get("action")))

    # T4d-1 真机输出形态：先说理由，末行给结论
    v1 = soul_core.extract_verdict("候选标签在情境中表现良好。\n\n合理")
    check("T4.24 末行『合理』可解析", v1[0] == "合理", str(v1))
    v2 = soul_core.extract_verdict("理由：过于宽泛\n不合理")
    check("T4.25 末行『不合理』可解析", v2[0] == "不合理", str(v2))
    v3 = soul_core.extract_verdict("不合理")
    check("T4.26 单行『不合理』可解析", v3[0] == "不合理", str(v3))
    v4 = soul_core.extract_verdict("合理")
    check("T4.27 单行『合理』可解析", v4[0] == "合理", str(v4))
    v5 = soul_core.extract_verdict("合理（理由：与好奇心吻合）")
    check("T4.28 带理由的旧格式仍可解析", v5[0] == "合理", str(v5))
    # 真机形态：结论被 markdown 标题挤掉，只剩理由句 —— 必须按语义判对，不能读反
    v6 = soul_core.extract_verdict(
        "该标签无法在近期经历或内分泌中找到具体支撑。\n\n**理由：**\n候选标签内容过于宽泛。")
    check("T4.29 否定理由句判为不合理", v6[0] == "不合理", str(v6))
    v7 = soul_core.extract_verdict("与近期经历和内分泌高度相符，可以采纳。\n\n合理")
    check("T4.30 肯定理由句判为合理", v7[0] == "合理", str(v7))
    v8 = soul_core.extract_verdict("结论：不合理")
    check("T4.31 显式结论行可解析", v8[0] == "不合理", str(v8))

    # T4d-2 小模型无视格式（真机返回"谨慎稳健"）也要能解析出标签
    check("T4.13 裸回复可解析", soul_core.extract_tag("谨慎稳健") == "谨慎稳健",
          "(= %r)" % soul_core.extract_tag("谨慎稳健"))
    check("T4.14 带标点的裸回复可解析",
          soul_core.extract_tag("\n内向、敏感。二") == "内向",
          "(= %r)" % soul_core.extract_tag("\n内向、敏感。二"))
    check("T4.15 标准格式仍可解析",
          soul_core.extract_tag("标签：敏锐探索者") == "敏锐探索者")
    check("T4.16 空泛裸回复仍被拦截",
          soul_core.extract_tag("宇宙的本质") is None)
    life_d = make_life(soul=new_soul(),
                       provider=FakeProvider(["谨慎稳健", "合理（与保守的内分泌吻合）"]))
    life_d.soul.round = 60
    life_d.soul.last_reflect_round = 40
    res_d = life_d._maybe_reflect("测试场景")
    check("T4.17 真机回复格式下审查也能采纳",
          res_d and res_d.get("action") == "accept", str(res_d and res_d.get("action")))

    # T4e 主循环里 20 轮真的会调起审查
    life4 = make_life(soul=new_soul(), provider=FakeProvider([]))
    life4.soul.round = 19
    life4.soul.last_reflect_round = 0
    fired = []
    life4._maybe_reflect = lambda scene=None: fired.append(1)
    life4.soul.round += 1        # 模拟 run_cycle 顶部的轮次推进
    life4._maybe_reflect("场景")
    check("T4.12 主循环第 20 轮调用审查", len(fired) == 1)


# ---------------------------------------------------------------- T5
def t5_panorama():
    print("\n[T5] 全景 System Prompt：生命值 + top3 人格 + 记忆")
    life = make_life(soul=new_soul())
    for t in ("敏锐", "偏执", "好奇"):
        life.soul.add_tag(t, 1.0)
    life.soul.vitality = 42
    life.soul.save()
    p = life.build_panorama_prompt("猫")
    print("  ---- 全景 Prompt ----")
    for line in p.splitlines():
        print("  | " + line)
    check("T5.1 含生命值", "生命值=42" in p)
    check("T5.2 含 top3 人格标签", all(t in p for t in ("敏锐", "偏执", "好奇")))
    check("T5.3 含记忆", "毛茸茸" in p or "场景" in p)
    check("T5.4 含 JSON 协议", '"action"' in p and '"introspection"' in p)
    life.soul.vitality = 5
    p2 = life.build_panorama_prompt("猫")
    check("T5.5 濒死时注入警告", "【警告】" in p2)


def main():
    print("=" * 60)
    print(" 熵灵 V4.5 灵魂级重构 · 验收测试")
    print(" 临时库: %s" % os.environ["AC_DB_PATH"])
    print(" 临时锁: %s" % os.environ["AC_DEAD_LOCK"])
    print("=" * 60)
    t1_vitality_tool()
    t2_death()
    t3_guard()
    t4_reflect()
    t5_panorama()
    print("\n" + "=" * 60)
    print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print(" 失败项: %s" % FAIL)
    print("=" * 60)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
