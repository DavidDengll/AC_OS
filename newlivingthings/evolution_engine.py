# evolution_engine.py
# -*- coding: utf-8 -*-
"""
evolution_engine.py —— 自进化引擎（基因池 / 世代管理 / 失败免疫）

职责：
  * 统计基因池：多少条优质基因、累计多少轮、当前是第几代大脑
  * 记录每一代大脑：从哪个基底模型进化而来、用了多少条基因
  * 失败免疫：显存不足/依赖缺失等失败会被记录成"免疫记忆"，
    冷却期内不再反复烧显卡；冷却结束后自动允许下一轮空闲重试
  * 降级进化（任务二）：LoRA 因 OOM 失败时，不直接长睡，而是触发
    "代码级自我重构"——改自己的 vision.py / thinker.py，成功则热重启
  * 提供 should_evolve() 给主循环做统一决策
"""

import json
import os
import sys
import time
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config  # noqa: E402
import self_finetune as sf  # noqa: E402

GEN_FILE = os.path.join(HERE, getattr(config, "GENERATION_FILE", "generation.json"))

DEFAULT_STATE = {
    "generation": 0,            # 当前第几代大脑（0 = 原始基底大脑）
    "current_model": None,      # 当前使用的模型名
    "base_model": None,         # 永远指向原始基底大脑，绝不丢失
    "history": [],              # 每次成功的进化记录
    "failures": [],             # 失败记录（免疫记忆）
    "cooldown_until": 0.0,      # 冷却截止时间戳（epoch 秒）
    "attempts": 0,
    "rewrites": [],             # 代码级重构历史
    "rewrite_cooldown_until": 0.0,
}

COOLDOWN_BY_KIND = {
    "oom": 3600,        # 显存不足：1 小时后再试（等用户释放显存/换环境）
    "mem": 1800,
    "dependency": 86400,  # 缺依赖：1 天后再说，避免每轮刷屏
    "timeout": 1800,
    "crash": 900,
    "merge": 1800,
    "ollama": 1800,
    "restart": 600,
    "dataset": 300,
    "unknown": 900,
}

# OOM 时降级到代码重构；这类失败不需要长冷却（没训练就没消耗）
OOM_KINDS = ("oom", "mem")
# 代码重构失败的冷却（避免每轮都改代码）
REWRITE_FAIL_COOLDOWN = 1800
REWRITE_OK_COOLDOWN = 7200


def _now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class EvolutionEngine:
    def __init__(self, state_file=None):
        self.state_file = state_file or GEN_FILE
        self.state = self._load()

    # ---------- 持久化 ----------
    def _load(self):
        st = dict(DEFAULT_STATE)
        st["history"] = []
        st["failures"] = []
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in DEFAULT_STATE.items():
                    st[k] = data.get(k, v)
            except Exception:
                pass
        if not st.get("base_model"):
            st["base_model"] = getattr(config, "BASE_MODEL_NAME", "qwen3.5:0.8b")
        if not st.get("current_model"):
            st["current_model"] = getattr(config, "MODEL_NAME", st["base_model"])
        return st

    def save(self):
        try:
            sf._dump_json(self.state_file, self.state)
        except Exception as e:
            print("[进化引擎] 状态保存失败（不影响运行）: %s" % e)

    # ---------- 只读统计 ----------
    @property
    def generation(self):
        return int(self.state.get("generation", 0))

    def gene_pool_size(self):
        return sf.gene_count()

    def cooldown_remaining(self):
        return max(0.0, float(self.state.get("cooldown_until", 0.0)) - time.time())

    def in_cooldown(self):
        return self.cooldown_remaining() > 0

    # ---------- 代码级重构（任务二） ----------
    def rewrite_cooldown_remaining(self):
        return max(0.0, float(self.state.get("rewrite_cooldown_until", 0.0)) - time.time())

    def rewrite_allowed(self):
        """是否允许再做一次代码重构（防止高频改代码）。"""
        if self.rewrite_cooldown_remaining() > 0:
            return False, "代码重构冷却中，剩余 %d 秒" % int(self.rewrite_cooldown_remaining())
        if not getattr(config, "CODE_REWRITE_ENABLED", True):
            return False, "代码重构已关闭（config.CODE_REWRITE_ENABLED=False）"
        return True, "可以重构"

    def record_rewrite(self, result):
        """记录一次代码重构结果，并设置冷却。"""
        ok = bool(getattr(result, "ok", False))
        applied = bool(getattr(result, "applied", False))
        cooldown = REWRITE_OK_COOLDOWN if applied else REWRITE_FAIL_COOLDOWN
        self.state.setdefault("rewrites", [])
        self.state["rewrites"].append({
            "time": _now_str(),
            "ok": ok,
            "applied": applied,
            "kind": getattr(result, "kind", ""),
            "target": os.path.basename(getattr(result, "target", "") or ""),
            "message": (getattr(result, "message", "") or "")[:300],
        })
        self.state["rewrites"] = self.state["rewrites"][-30:]
        self.state["rewrite_cooldown_until"] = time.time() + cooldown
        self.save()
        return cooldown

    def evolve_by_code(self, provider=None, dry_run=None, use_model=True):
        """代码级进化：让熵灵改自己的源文件。

        返回 code_rewriter.RewriteResult。任何异常都被吞掉，绝不拖垮主程序。
        """
        try:
            allowed, why = self.rewrite_allowed()
            if not allowed:
                from code_rewriter import RewriteResult
                print("[代码进化] 跳过：%s" % why, flush=True)
                return RewriteResult(False, "skipped", why)
            import code_rewriter
            print("[代码进化] OOM 降级触发 —— 熵灵开始改写自己的源码", flush=True)
            result = code_rewriter.rewrite_once(provider=provider, dry_run=dry_run,
                                                use_model=use_model)
            cd = self.record_rewrite(result)
            if getattr(result, "ok", False):
                print("[代码进化] 成功：%s" % getattr(result, "message", ""), flush=True)
            else:
                print("[代码进化] 未生效：%s（%d 秒后可再试）" % (
                    getattr(result, "message", ""), cd), flush=True)
            return result
        except Exception as e:
            print("[代码进化] 捕获到异常，已隔离（原代码未被破坏）: %s" % e, flush=True)
            try:
                from code_rewriter import RewriteResult
                return RewriteResult(False, "exception", str(e))
            except Exception:
                return None

    # ---------- 决策 ----------
    def should_evolve(self, idle=True):
        """返回 (bool, reason)。主循环/空闲监视器只要问这一个函数即可。"""
        if sf.is_training():
            return False, "训练进行中"
        pool = self.gene_pool_size()
        need = int(getattr(config, "FINETUNE_TRIGGER_COUNT", 20))
        if pool < need:
            return False, "优质基因 %d/%d，还不够" % (pool, need)
        if self.in_cooldown():
            return False, "免疫冷却中，剩余 %d 秒" % int(self.cooldown_remaining())
        return True, "基因 %d 条，空闲可进化" % pool

    # ---------- 记录 ----------
    def record_success(self, new_model, samples):
        self.state["generation"] = self.generation + 1
        self.state["current_model"] = new_model
        self.state["attempts"] = int(self.state.get("attempts", 0)) + 1
        self.state["cooldown_until"] = 0.0
        self.state["history"].append({
            "generation": self.state["generation"],
            "model": new_model,
            "samples": samples,
            "time": _now_str(),
        })
        self.save()
        return self.state["generation"]

    def record_failure(self, kind, error=""):
        """记录失败。

        OOM 属于"硬件不够"，不是逻辑错误：
          - 不进入长冷却（否则永远不会触发降级进化）
          - 标记 degraded=True，交给上层走"代码级重构"
        """
        degraded = kind in OOM_KINDS
        cooldown = 0 if degraded else COOLDOWN_BY_KIND.get(kind, 900)
        self.state["attempts"] = int(self.state.get("attempts", 0)) + 1
        if not degraded:
            self.state["cooldown_until"] = time.time() + cooldown
        self.state["failures"].append({
            "kind": kind, "error": (error or "")[:400],
            "cooldown": cooldown, "degraded_to_code": degraded, "time": _now_str(),
        })
        self.state["failures"] = self.state["failures"][-50:]
        # 失败不影响 current_model：原大脑继续运行
        self.save()
        return cooldown

    def summary(self):
        return {
            "generation": self.generation,
            "current_model": self.state.get("current_model"),
            "base_model": self.state.get("base_model"),
            "gene_pool": self.gene_pool_size(),
            "need": int(getattr(config, "FINETUNE_TRIGGER_COUNT", 20)),
            "attempts": self.state.get("attempts", 0),
            "cooldown_remaining": int(self.cooldown_remaining()),
            "training": sf.is_training(),
            "rewrites": len(self.state.get("rewrites", [])),
            "rewrite_cooldown": int(self.rewrite_cooldown_remaining()),
        }


def format_summary(engine):
    s = engine.summary()
    extra = ""
    if s["cooldown_remaining"]:
        extra += " | 冷却 %ds" % s["cooldown_remaining"]
    if s["rewrite_cooldown"]:
        extra += " | 代码重构冷却 %ds" % s["rewrite_cooldown"]
    return (
        "[进化引擎] 第 %d 代 | 当前大脑: %s | 基底: %s | 基因: %d/%d | 尝试: %d | 重构 %d 次%s"
        % (s["generation"], s["current_model"], s["base_model"],
           s["gene_pool"], s["need"], s["attempts"], s.get("rewrites", 0), extra)
    )


if __name__ == "__main__":
    eng = EvolutionEngine()
    print(format_summary(eng))
    ok, reason = eng.should_evolve()
    print("是否进化:", ok, "|", reason)
