# test_finetune_adapter.py
# -*- coding: utf-8 -*-
"""
test_finetune_adapter.py —— 微调配置联网搜索与双重断言模块验收

覆盖：
  T1 搜索触发：注册表命中不联网 / 未命中调用 bridge
  T2 稳健提取：大模型优先 / 字符串兜底 / 无法提取返回 None
  T3 断言一：错误模块列表必须被拦截
  T4 断言二：极小占比必须被拦截
  T5 兜底降级：任一步失败返回 None 并提示
  T6 内存稳定性：全流程 RSS 平稳，不加载权重
  T7 红线：模块内不得出现 from_pretrained 全量加载
"""
import os
import sys
import tracemalloc

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
os.chdir(HERE)

import finetune_search_adapter as fsa  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


CONFIG = {
    "architectures": ["LlamaForCausalLM"],
    "hidden_size": 1024,
    "num_hidden_layers": 16,
    "num_attention_heads": 16,
    "num_key_value_heads": 8,
    "intermediate_size": 4096,
    "vocab_size": 49000,
}


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def chat(self, messages, temperature=0.7, max_tokens=500):
        self.calls.append(messages[0]["content"] if messages else "")
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def fake_bridge_ok(payload):
    def _b(task, timeout=None):
        return {"ok": True, "result": payload}
    return _b


def fake_bridge_fail(task, timeout=None):
    return {"ok": False, "error": "桥接不可达"}


def t1_trigger():
    print("\n[T1] 搜索触发")
    check("T1.1 注册表命中 granite4",
          fsa.registry_lookup("granite4:tiny-h") == ["q_proj", "k_proj", "v_proj", "o_proj"])
    check("T1.2 未知名返回 None", fsa.registry_lookup("totally-unknown-model-xyz") is None)
    check("T1.3 搜索词格式正确",
          fsa.build_search_query("foo/bar") ==
          "HuggingFace foo/bar LoRA target_modules fine-tuning configuration")
    called = []

    def spy(task, timeout=None):
        called.append(task)
        return {"ok": True, "result": "q_proj,k_proj"}

    fsa.search_web("some-unknown-model", bridge=spy)
    check("T1.4 未命中时调用 bridge", len(called) == 1)
    check("T1.5 任务含搜索词",
          "HuggingFace some-unknown-model LoRA target_modules fine-tuning configuration"
          in (called[0] if called else ""))
    out = fsa.search_web("some-unknown-model", bridge=fake_bridge_fail)
    check("T1.6 桥接失败返回空串", out == "")


def t2_extract():
    print("\n[T2] 稳健提取")
    text = "推荐配置：target_modules=[q_proj, k_proj, v_proj, o_proj](建议 lora_r=8)"
    llm = FakeLLM("q_proj,k_proj,v_proj,o_proj")
    mods = fsa.extract_modules(text, "m", llm)
    check("T2.1 大模型提取成功", mods == ["q_proj", "k_proj", "v_proj", "o_proj"], str(mods))
    llm_none = FakeLLM("NONE")
    mods2 = fsa.extract_modules("这段文字里有一点别的信息", "m", llm_none)
    check("T2.2 大模型说 NONE 且无兜底命中 -> None", mods2 is None, str(mods2))
    llm_err = FakeLLM(RuntimeError("模型超时"))
    mods3 = fsa.extract_modules(text, "m", llm_err)
    check("T2.3 大模型异常时字符串兜底仍能提取", bool(mods3) and "q_proj" in mods3, str(mods3))
    check("T2.4 空文本返回 None", fsa.extract_modules("", "m", None) is None)
    check("T2.5 无 llm 时也能兜底",
          (fsa.extract_modules(text, "m", None) or [])[:1] == ["q_proj"])


def t2b_search_failure():
    print("\n[T2b] 搜索结果有效性校验（真机缺陷回归）")
    # 真实场景：DuckDuckGo 网络错误时返回的致歉文本
    apology = ("I can't use DuckDuckGo right now due to the network error, "
               "but I'm ready to help you when that works!")
    check("T2b.1 识别致歉文本为无效", fsa.looks_like_search_failure(apology) is True)
    check("T2b.2 空文本视为无效", fsa.looks_like_search_failure("") is True)
    check("T2b.3 真实配置文本不误判",
          fsa.looks_like_search_failure(
              "target_modules=[q_proj,k_proj,v_proj,o_proj] lora_r=8 config") is False)

    # 词边界：Would 不应命中 Wo
    hits = fsa.extract_modules_from_text("What would you like me to do?")
    check("T2b.4 普通英文句子不误抽模块", hits == [], str(hits))
    hits2 = fsa.extract_modules_from_text("set target_modules to q_proj and v_proj")
    check("T2b.5 独立单词仍可识别",
          "q_proj" in hits2 and "v_proj" in hits2, str(hits2))
    hits3 = fsa.extract_modules_from_text("q_proj_lora is not a module")
    check("T2b.6 粘连标识符不算命中", "q_proj" not in hits3, str(hits3))

    # 端到端：桥接返回致歉文本时，必须判定失败而不是提取出 Wo
    res = fsa.search_finetune_config("unknown-apology", llm=None,
                                     bridge=fake_bridge_ok(apology))
    check("T2b.7 致歉文本端到端返回 None", res is None, str(res))

def t3_assert1():
    print("\n[T3] 断言一 · 存在性")
    arch = fsa._arch_module_names(CONFIG)
    check("T3.1 架构含 q_proj", "q_proj" in arch)
    ok, _ = fsa.assert_modules_exist(["q_proj", "k_proj"], arch)
    check("T3.2 合法模块通过", ok is True)
    ok2, missing = fsa.assert_modules_exist(["q_proj", "not_a_real_module"], arch)
    check("T3.3 错误模块被拦截",
          ok2 is False and missing == ["not_a_real_module"], str(missing))
    ok3, missing3 = fsa.assert_modules_exist(["xyz_fake"], arch)
    check("T3.4 全错模块被拦截", ok3 is False, str(missing3))
    ok4, _ = fsa.assert_modules_exist([], arch)
    check("T3.5 空列表不通过", ok4 is False)

    bad_llm = FakeLLM("q_proj,this_module_does_not_exist")
    orig = fsa.load_arch_info
    fsa.load_arch_info = lambda name: {"source": "test", "config": CONFIG}
    try:
        res = fsa.search_finetune_config(
            "unknown-model-for-test", llm=bad_llm,
            bridge=fake_bridge_ok("q_proj this_module_does_not_exist"))
    finally:
        fsa.load_arch_info = orig
    check("T3.6 端到端：错误模块返回 None", res is None, str(res))


def t4_assert2():
    print("\n[T4] 断言二 · 占比度")
    params, ratio, base = fsa.estimate_module_params(["q_proj"], CONFIG)
    print("     q_proj: params=%d ratio=%.6f%% base=%d" % (params, ratio * 100, base))
    ok, r, p = fsa.assert_module_ratio(["q_proj"], CONFIG)
    check("T4.1 单个 q_proj 占比达标", ok is True, "(%.4f%%)" % (r * 100))
    # 构造真正 < 0.1% 的配置：q_proj 单层 = 4*4 = 16，8 层共 128；
    # base ≈ 500000*4*2 + 8*(4*16 + 2*4*64) ≈ 4.0M -> 占比约 0.003%
    tiny_cfg = dict(CONFIG, hidden_size=4, num_hidden_layers=8,
                    num_attention_heads=2, num_key_value_heads=2,
                    intermediate_size=64, vocab_size=500000)
    params2, ratio2, base2 = fsa.estimate_module_params(["q_proj"], tiny_cfg)
    print("     极小配置: params=%d base=%d ratio=%.8f%%" % (params2, base2, ratio2 * 100))
    ok2, r2, p2 = fsa.assert_module_ratio(["q_proj"], tiny_cfg)
    check("T4.2 占比过低被拦截", ok2 is False, "(%.8f%%)" % (r2 * 100))
    # 阈值本身可调：把阈值降到极低后，同一配置应当通过
    ok2b, _, _ = fsa.assert_module_ratio(["q_proj"], tiny_cfg, min_ratio=0.0)
    check("T4.2b 阈值可配置", ok2b is True)
    ok3, r3, _ = fsa.assert_module_ratio(["q_proj", "k_proj", "v_proj", "o_proj"], CONFIG)
    print("     四投影: %.6f%%" % (r3 * 100))
    check("T4.3 四投影占比更高", r3 > r, "(%.4f%% > %.4f%%)" % (r3 * 100, r * 100))
    orig = fsa.load_arch_info
    fsa.load_arch_info = lambda name: {"source": "test", "config": tiny_cfg}
    try:
        res = fsa.search_finetune_config("unknown-tiny", llm=FakeLLM("q_proj"),
                                         bridge=fake_bridge_ok("q_proj"))
    finally:
        fsa.load_arch_info = orig
    check("T4.4 端到端：极小占比返回 None", res is None, str(res))


def t5_fallback():
    print("\n[T5] 兜底降级")
    res = fsa.search_finetune_config("unknown-a", llm=FakeLLM("q_proj"),
                                     bridge=fake_bridge_fail)
    check("T5.1 搜索失败 -> None", res is None)
    res2 = fsa.search_finetune_config("unknown-b", llm=FakeLLM("NONE"),
                                      bridge=fake_bridge_ok("无关内容"))
    check("T5.2 无法提取 -> None", res2 is None)
    orig = fsa.load_arch_info
    fsa.load_arch_info = lambda name: None
    try:
        res3 = fsa.search_finetune_config("unknown-c", llm=FakeLLM("q_proj"),
                                          bridge=fake_bridge_ok("q_proj"))
    finally:
        fsa.load_arch_info = orig
    check("T5.3 架构信息缺失 -> None", res3 is None)
    check("T5.4 无法映射返回 None", fsa._normalize_to_hf_id("abc-def") is None)


def t6_memory():
    print("\n[T6] 内存稳定性")
    orig = fsa.load_arch_info
    fsa.load_arch_info = lambda name: {"source": "test", "config": CONFIG}
    try:
        tracemalloc.start()
        base_cur, _ = tracemalloc.get_traced_memory()
        for i in range(50):
            fsa.search_finetune_config(
                "unknown-mem-%d" % i, llm=FakeLLM("q_proj,k_proj,v_proj,o_proj"),
                bridge=fake_bridge_ok("q_proj k_proj v_proj o_proj"))
        cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    finally:
        fsa.load_arch_info = orig
    growth_mb = (cur - base_cur) / 1024 / 1024
    peak_mb = peak / 1024 / 1024
    print("     与起始比增长 %.3f MB，峰值 %.3f MB" % (growth_mb, peak_mb))
    check("T6.1 50 次调用内存增长 < 5MB", growth_mb < 5.0, "(%.3f MB)" % growth_mb)
    check("T6.2 峰值 < 20MB", peak_mb < 20.0, "(%.3f MB)" % peak_mb)


def t7_redline():
    print("\n[T7] 红线检查")
    with open(os.path.join(HERE, "finetune_search_adapter.py"), encoding="utf-8") as f:
        src = f.read()
    check("T7.1 无 AutoModel", "AutoModel" not in src)
    check("T7.2 无 AutoConfig", "AutoConfig" not in src)
    check("T7.3 无 transformers import", "import transformers" not in src)
    check("T7.4 无 from_pretrained 全量加载", "from_pretrained" not in src)


def main():
    print("=" * 70)
    print(" 微调配置联网搜索与断言模块 · 验收测试")
    print("=" * 70)
    t1_trigger()
    t2_extract()
    t2b_search_failure()
    t3_assert1()
    t4_assert2()
    t5_fallback()
    t6_memory()
    t7_redline()
    print("\n" + "=" * 70)
    print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print(" 失败项: %s" % FAIL)
    print("=" * 70)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
