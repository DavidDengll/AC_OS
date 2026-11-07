# -*- coding: utf-8 -*-
"""V6.5 对外回话高压提示词验收（全程 Mock，不联网、不调模型）"""
import io, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


class MockProvider:
    """记录请求的假大模型。"""
    def __init__(self):
        self.calls = []

    def chat(self, messages, temperature=0.7, max_tokens=500, **kw):
        self.calls.append(messages)
        sys_prompt = ""
        for m in messages:
            if m.get("role") == "system":
                sys_prompt = m.get("content") or ""
        if "强令警告" in sys_prompt:
            return "好累。别靠近我。"
        return "窗外的光落在桌面上。"


def make_lm(endo):
    import language_model as LM
    lm = LM.LanguageModel.__new__(LM.LanguageModel)   # 跳过 get_provider()
    lm.provider = MockProvider()
    lm.endo_provider = lambda: dict(endo)
    lm.fallback_templates = ["兜底"]
    lm._response_cache = {}
    return lm, lm.provider


print("=" * 66)
print(" AC OS V6.5 · 对外回话高压提示词验收")
print("=" * 66)

# T1 高压态（C=0.9）启用强令警告
print("\n[T1] 高压态 C=0.9 -> 强令警告")
lm, prov = make_lm({"dopamine": 0.1, "cortisol": 0.9, "endorphin": 0.4})
out = lm.generate_response("窗外的风景")
sysp = [m for m in prov.calls[-1] if m.get("role") == "system"][0]["content"]
check("T1.1 使用了【强令警告】", "【强令警告】" in sysp)
check("T1.2 文案精确匹配", sysp == lm.PRESSURE_PROMPT, sysp[:60])
check("T1.3 不再包含观察者提示词", "你是一个观察者" not in sysp)
check("T1.4 返回高压回复", out == "好累。别靠近我。", out)

# T2 正常态（C=0.3）保持观察者
print("\n[T2] 正常态 C=0.3 -> 观察者（不得改变原行为）")
lm2, prov2 = make_lm({"dopamine": 0.5, "cortisol": 0.3, "endorphin": 0.4})
out2 = lm2.generate_response("窗外的风景")
sysp2 = [m for m in prov2.calls[-1] if m.get("role") == "system"][0]["content"]
check("T2.1 仍为观察者提示词", sysp2 == lm2.OBSERVER_PROMPT, sysp2[:50])
check("T2.2 不含强令警告", "强令警告" not in sysp2)
check("T2.3 观察者文案与原版一致",
      sysp2.startswith("你是一个观察者，会用简洁、生动的一句话描述你所看到的情景。"))
check("T2.4 正常态正常返回", out2 == "窗外的光落在桌面上。", out2)

# T3 边界 C=0.7 不触发（必须 > 0.7）
print("\n[T3] 边界 C=0.7")
lm3, prov3 = make_lm({"cortisol": 0.7, "dopamine": 0.3})
lm3.generate_response("景色")
sysp3 = [m for m in prov3.calls[-1] if m.get("role") == "system"][0]["content"]
check("T3.1 C=0.7 不触发（严格大于）", sysp3 == lm3.OBSERVER_PROMPT)
lm4, prov4 = make_lm({"cortisol": 0.71, "dopamine": 0.3})
lm4.generate_response("景色")
sysp4 = [m for m in prov4.calls[-1] if m.get("role") == "system"][0]["content"]
check("T3.2 C=0.71 触发", sysp4 == lm4.PRESSURE_PROMPT)

# T4 缓存隔离
print("\n[T4] 缓存隔离")
lm5, prov5 = make_lm({"cortisol": 0.3})
lm5.generate_response("同一场景")
n1 = len(prov5.calls)
lm5.generate_response("同一场景")
check("T4.1 正常态命中缓存（不重复请求）", len(prov5.calls) == n1, "calls=%d" % len(prov5.calls))

lm5.endo_provider = lambda: {"cortisol": 0.9}
lm5.generate_response("同一场景")
check("T4.2 高压态绕过缓存（重新请求）", len(prov5.calls) == n1 + 1,
      "calls=%d" % len(prov5.calls))
sysp5 = [m for m in prov5.calls[-1] if m.get("role") == "system"][0]["content"]
check("T4.3 高压请求确实用强令警告", sysp5 == lm5.PRESSURE_PROMPT)

lm5.endo_provider = lambda: {"cortisol": 0.3}
back = lm5.generate_response("同一场景")
check("T4.4 高压回复未污染正常态缓存", back == "窗外的光落在桌面上。", back)

# T5 异常降级
print("\n[T5] 异常降级")
def boom():
    raise RuntimeError("内分泌读取失败")
lm6, prov6 = make_lm({})
lm6.endo_provider = boom
out6 = lm6.generate_response("景色")
sysp6 = [m for m in prov6.calls[-1] if m.get("role") == "system"][0]["content"]
check("T5.1 读取失败降级为观察者", sysp6 == lm6.OBSERVER_PROMPT)
check("T5.2 不抛异常", out6 == "窗外的光落在桌面上。", out6)

# T6 显式传入 endo 优先
print("\n[T6] 显式 endo 参数优先")
lm7, prov7 = make_lm({"cortisol": 0.1})
lm7.generate_response("景色", endo={"cortisol": 0.95})
sysp7 = [m for m in prov7.calls[-1] if m.get("role") == "system"][0]["content"]
check("T6.1 显式传 endo 覆盖内部状态", sysp7 == lm7.PRESSURE_PROMPT)

print("\n" + "=" * 66)
print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL: print(" 失败项:", FAIL)
print("=" * 66)
sys.exit(0 if not FAIL else 1)
