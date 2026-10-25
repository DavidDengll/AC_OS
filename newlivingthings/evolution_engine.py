# evolution_engine.py
# -*- coding: utf-8 -*-
"""
evolution_engine.py —— 自进化引擎（基因池 / 世代管理 / 失败免疫）

职责：
  * 统计基因池：多少条优质基因、累计多少轮、当前是第几代大脑
  * 记录每一代大脑：从哪个基底模型进化而来、用了多少条基因
  * 失败免疫：显存不足/依赖缺失等失败会被记录成"免疫记忆"，
    冷却期内不再反复烧显卡；冷却结束后自动允许下一轮空闲重试
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
        cooldown = COOLDOWN_BY_KIND.get(kind, 900)
        self.state["attempts"] = int(self.state.get("attempts", 0)) + 1
        self.state["cooldown_until"] = time.time() + cooldown
        self.state["failures"].append({
            "kind": kind, "error": (error or "")[:400],
            "cooldown": cooldown, "time": _now_str(),
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
        }


def format_summary(engine):
    s = engine.summary()
    return (
        "[进化引擎] 第 %d 代 | 当前大脑: %s | 基底: %s | 基因: %d/%d | 尝试: %d%s"
        % (s["generation"], s["current_model"], s["base_model"],
           s["gene_pool"], s["need"], s["attempts"],
           " | 冷却 %ds" % s["cooldown_remaining"] if s["cooldown_remaining"] else "")
    )


if __name__ == "__main__":
    eng = EvolutionEngine()
    print(format_summary(eng))
    ok, reason = eng.should_evolve()
    print("是否进化:", ok, "|", reason)
