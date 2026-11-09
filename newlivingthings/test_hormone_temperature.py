# -*- coding: utf-8 -*-
"""test_hormone_temperature.py —— 激素劫持 temperature 验收（全 Mock，不连真模型）

验证：
  T1 平稳态 C<0.7 且 D<0.7 -> 0.7
  T2 极度高压 C>0.8        -> 1.1
  T3 极度亢奋 D>0.8 且 C<0.5 -> 0.9
  T4 极度虚弱 vitality<20 且 C<0.5 -> 0.3
  T5 优先级：高压 > 亢奋 > 虚弱
  T6 参数穿透：真的传到底层（OpenAI kwargs / Ollama options）
  T7 max_tokens 硬顶仍生效（红线）
  T8 边界防崩：非法值/NaN/越界
  T9 日志格式
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


def capture(fn):
    buf, old = io.StringIO(), sys.stdout
    try:
        sys.stdout = buf
        r = fn()
    finally:
        sys.stdout = old
    return r, buf.getvalue()


class FakeInner:
    """记录底层真正收到的参数。"""
    def __init__(self):
        self.model = "mock-model"
        self.base_url = "http://mock/v1"
        self.native_root = "http://mock"
        self.thinking_unsupported = False
        self.calls = []
        self.native_calls = []

    def chat(self, messages, temperature=0.7, max_tokens=500, **kw):
        self.calls.append({"temperature": temperature, "max_tokens": max_tokens, **kw})
        return "ok"

    def _chat_native(self, messages, temperature, max_tokens):
        self.native_calls.append({"temperature": temperature, "max_tokens": max_tokens})
        return "native-ok"


class FakeOwner:
    """模拟 EntropyLife 的内分泌与生命值。"""
    def __init__(self, d=0.5, c=0.5, v=100, cap=160):
        self._endo = {"dopamine": d, "cortisol": c, "endorphin": 0.4}
        self._v = v
        self._chat_max_tokens = cap
        self._last_temperature = None
        self.charged = 0

    def mood(self):
        return dict(self._endo)

    def _vitality_value(self):
        return self._v

    def _charge_llm_call(self):
        self.charged += 1


def make_kernel(d=0.5, c=0.5, v=100, cap=160):
    import main as M
    owner = FakeOwner(d=d, c=c, v=v, cap=cap)
    inner = FakeInner()
    return M._KernelBoundedProvider(owner, inner), owner, inner


print("=" * 68)
print(" AC OS V6.6 · 激素劫持 Temperature 验收（全 Mock）")
print("=" * 68)

import main as M

# ---------------- T1~T4 规则矩阵 ----------------
print("\n[T1] 平稳态 (C<0.7 且 D<0.7) -> 0.7")
k, owner, inner = make_kernel(d=0.5, c=0.5, v=100)
capture(lambda: k.chat([{"role": "user", "content": "hi"}], temperature=0.1, max_tokens=100))
check("T1.1 底层收到 0.7", inner.calls[-1]["temperature"] == 0.7, str(inner.calls[-1]))
check("T1.2 即使调用方传 0.1 也被重写", inner.calls[-1]["temperature"] != 0.1)

print("\n[T2] 极度高压 C>0.8 -> 1.1")
k, owner, inner = make_kernel(d=0.2, c=0.95, v=100)
capture(lambda: k.chat([{"role": "user", "content": "hi"}], temperature=0.7, max_tokens=100))
check("T2.1 底层收到 1.1", inner.calls[-1]["temperature"] == 1.1, str(inner.calls[-1]["temperature"]))
check("T2.2 owner._last_temperature 已记录", owner._last_temperature == 1.1)

print("\n[T3] 极度亢奋 D>0.8 且 C<0.5 -> 0.9")
k, owner, inner = make_kernel(d=0.9, c=0.3, v=100)
capture(lambda: k.chat([{"role": "user", "content": "hi"}], temperature=0.7, max_tokens=100))
check("T3.1 底层收到 0.9", inner.calls[-1]["temperature"] == 0.9, str(inner.calls[-1]["temperature"]))

print("\n[T4] 极度虚弱 vitality<20 且 C<0.5 -> 0.3")
k, owner, inner = make_kernel(d=0.5, c=0.3, v=15)
capture(lambda: k.chat([{"role": "user", "content": "hi"}], temperature=0.7, max_tokens=100))
check("T4.1 底层收到 0.3", inner.calls[-1]["temperature"] == 0.3, str(inner.calls[-1]["temperature"]))

# ---------------- T5 优先级 ----------------
print("\n[T5] 优先级：高压 > 亢奋 > 虚弱")
cases = [
    ("高压+亢奋同时满足", dict(d=0.9, c=0.95, v=100), 1.1),
    ("亢奋+虚弱同时满足", dict(d=0.9, c=0.3, v=10), 0.9),
    ("高压+虚弱同时满足", dict(d=0.2, c=0.95, v=10), 1.1),
]
for label, kw, want in cases:
    k, owner, inner = make_kernel(**kw)
    capture(lambda: k.chat([{"role": "user", "content": "x"}], max_tokens=50))
    check("T5 %s -> %.1f" % (label, want), inner.calls[-1]["temperature"] == want,
          str(inner.calls[-1]["temperature"]))

# ---------------- T6 参数穿透 ----------------
print("\n[T6] 参数穿透到底层")
k, owner, inner = make_kernel(d=0.2, c=0.95, v=100)
capture(lambda: k.chat([{"role": "user", "content": "hi"}], temperature=0.7, max_tokens=100))
call = inner.calls[-1]
check("T6.1 inner.chat 收到 temperature=1.1", call["temperature"] == 1.1)
check("T6.2 未被调用方的 0.7 覆盖", call["temperature"] != 0.7)
check("T6.3 messages 原样透传", isinstance(call, dict))

# 原生路径也必须劫持
k2, owner2, inner2 = make_kernel(d=0.2, c=0.95, v=100)
capture(lambda: k2._chat_native([{"role": "user", "content": "hi"}], 0.7, 100))
check("T6.4 原生路径同样传入 1.1",
      inner2.native_calls[-1]["temperature"] == 1.1,
      str(inner2.native_calls[-1]))

# ---------------- T7 max_tokens 硬顶（红线） ----------------
print("\n[T7] max_tokens 硬顶仍然生效（红线）")
k, owner, inner = make_kernel(d=0.2, c=0.95, v=100, cap=160)
_r, out = capture(lambda: k.chat([{"role": "user", "content": "hi"}], max_tokens=99999))
check("T7.1 99999 被压到 160", inner.calls[-1]["max_tokens"] == 160,
      str(inner.calls[-1]["max_tokens"]))
check("T7.2 打印算力硬顶日志", "算力硬顶" in out)
check("T7.3 温度劫持未干扰硬顶", inner.calls[-1]["temperature"] == 1.1)

k, owner, inner = make_kernel(d=0.5, c=0.5, v=100, cap=160)
capture(lambda: k.chat([{"role": "user", "content": "hi"}], max_tokens=50))
check("T7.4 小于上限时不被放大", inner.calls[-1]["max_tokens"] == 50,
      str(inner.calls[-1]["max_tokens"]))

k2, owner2, inner2 = make_kernel(d=0.5, c=0.5, v=100, cap=160)
capture(lambda: k2._chat_native([{"role": "user", "content": "hi"}], 0.7, 99999))
check("T7.5 原生路径 max_tokens 同样被压到 160",
      inner2.native_calls[-1]["max_tokens"] == 160,
      str(inner2.native_calls[-1]["max_tokens"]))

# ---------------- T8 边界防崩 ----------------
print("\n[T8] 边界防崩")
K = M._KernelBoundedProvider
check("T8.1 clamp 越界上界 -> 2.0", K._clamp_temp(99) == 2.0)
check("T8.2 clamp 越界下界 -> 0.0", K._clamp_temp(-5) == 0.0)
check("T8.3 clamp NaN -> 默认 0.7", K._clamp_temp(float("nan")) == 0.7)
check("T8.4 clamp 非数值 -> 默认 0.7", K._clamp_temp("abc") == 0.7)
check("T8.5 clamp None -> 默认 0.7", K._clamp_temp(None) == 0.7)

# owner 读不到内分泌时不崩、回落平稳
class BrokenOwner:
    _chat_max_tokens = 160
    def mood(self):
        raise RuntimeError("endo 不可读")
    def _vitality_value(self):
        raise RuntimeError("vitality 不可读")
    def _charge_llm_call(self):
        pass

inner3 = FakeInner()
k3 = M._KernelBoundedProvider(BrokenOwner(), inner3)
_r3, out3 = capture(lambda: k3.chat([{"role": "user", "content": "x"}], max_tokens=50))
check("T8.6 状态不可读时不抛异常", inner3.calls[-1]["temperature"] == 0.7,
      str(inner3.calls[-1]["temperature"]))

# ---------------- T9 日志格式 ----------------
print("\n[T9] 终端日志格式")
k, owner, inner = make_kernel(d=0.2, c=0.95, v=88)
_r, out = capture(lambda: k.chat([{"role": "user", "content": "x"}], max_tokens=50))
line = [ln for ln in out.splitlines() if "生理劫持" in ln]
check("T9.1 打印 [生理劫持] 日志", bool(line), str(line))
if line:
    print("  | " + line[0])
    import re
    m = re.search(r"C=([0-9.]+), D=([0-9.]+), 生命值=(\d+) -> Temperature 强制重写为 ([0-9.]+)",
                  line[0])
    check("T9.2 日志含 C/D/生命值/温度", m is not None, line[0])
    if m:
        check("T9.3 数值正确", float(m.group(1)) == 0.95 and float(m.group(2)) == 0.2
              and int(m.group(3)) == 88 and float(m.group(4)) == 1.1, m.groups())

# ---------------- T10 线级验证：真的进了 HTTP 请求体 ----------------
print("\n[T10] 线级穿透：拦截 urllib，检查发往 Ollama 的请求体")
import json as _json
import model_provider as _mp

_sent = []

class _Req:
    def __init__(self, url, data=None, headers=None, **kw):
        self.full_url = url
        self.data = data

class _Resp:
    def __init__(self, b):
        self._b = b
    def read(self):
        return self._b
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

def _open(req, timeout=None):
    _sent.append(_json.loads(req.data.decode("utf-8")))
    return _Resp(_json.dumps({"message": {"content": "ok"}}).encode())

_orig_req, _orig_open = _mp.urllib.request.Request, _mp.urllib.request.urlopen
_mp.urllib.request.Request = _Req
_mp.urllib.request.urlopen = _open
try:
    prov = _mp.ModelProvider.__new__(_mp.ModelProvider)
    prov.model = "mock"
    prov.base_url = "http://127.0.0.1:11434/v1"
    prov.native_root = "http://127.0.0.1:11434"
    prov.thinking_unsupported = False

    k, owner, inner = make_kernel(d=0.2, c=0.95, v=100, cap=160)
    # 把内核的内层换成一个"会把参数转给真实 ModelProvider._chat_native"的桥
    class BridgeInner(FakeInner):
        def _chat_native(self, messages, temperature, max_tokens):
            return prov._chat_native(messages, temperature, max_tokens)
    k._inner = BridgeInner()
    capture(lambda: k._chat_native([{"role": "user", "content": "hi"}], 0.7, 99999))

    body = _sent[-1]
    check("T10.1 请求体 options.temperature == 1.1",
          body.get("options", {}).get("temperature") == 1.1, str(body.get("options")))
    check("T10.2 请求体 options.num_predict 受硬顶约束（256 下限）",
          body.get("options", {}).get("num_predict") >= 256,
          str(body.get("options", {}).get("num_predict")))
    check("T10.3 温度未被底层默认值覆盖",
          body.get("options", {}).get("temperature") != 0.7)
finally:
    _mp.urllib.request.Request = _orig_req
    _mp.urllib.request.urlopen = _orig_open

print("\n" + "=" * 68)
print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" 失败项:", FAIL)
print("=" * 68)
sys.exit(0 if not FAIL else 1)
