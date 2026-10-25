# entropy_core.py - 熵灵生命维持核心
# AC OS 生命维持系统 - 为"熵灵"提供内分泌、记忆、语言中枢

import os
import sys
import json
import time
import random
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

# ============ 环境配置 ============
os.environ["SENTENCE_TRANSFORMERS_HOME"] = "D:/model_cache"
Path("D:/model_cache").mkdir(parents=True, exist_ok=True)

# ============ 日志配置 ============
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("entropy")

# ============ 常量配置 ============
OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
OLLAMA_MODEL = "qwen3.5:0.8b"
MEMORY_FILE = "memory.json"
CYCLE_INTERVAL = 5

D_MAX = 1.0
C_MAX = 1.0
E_MAX = 1.0
DRIFT_RANGE = 0.1
EMOTIONAL_THRESHOLD = 0.8

def clamp(value, min_val=0.0, max_val=1.0):
    return max(min_val, min(max_val, value))

def load_json(filepath, default):
    if Path(filepath).exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error("[存储失败] " + filepath + ": " + str(e))

class EndocrineSystem:
    def __init__(self):
        self.dopamine = 0.5
        self.cortisol = 0.3
        self.endorphin = 0.4
        self.base_dopamine = 0.5
        self.base_cortisol = 0.3
        self.base_endorphin = 0.4
    
    def step(self):
        if self.cortisol > 0.6:
            self.dopamine *= 0.85
        if self.endorphin > 0.6:
            self.cortisol *= 0.9
        if self.dopamine > 0.7:
            self.endorphin = clamp(self.endorphin + 0.05)
        
        self.dopamine = clamp(self.dopamine * 0.98 + self.base_dopamine * 0.02)
        self.cortisol = clamp(self.cortisol * 0.97 + self.base_cortisol * 0.03)
        self.endorphin = clamp(self.endorphin * 0.98 + self.base_endorphin * 0.02)
        
        drift = random.uniform(-DRIFT_RANGE, DRIFT_RANGE)
        self.base_dopamine = clamp(self.base_dopamine + drift)
        drift = random.uniform(-DRIFT_RANGE, DRIFT_RANGE)
        self.base_cortisol = clamp(self.base_cortisol + drift)
        drift = random.uniform(-DRIFT_RANGE, DRIFT_RANGE)
        self.base_endorphin = clamp(self.base_endorphin + drift)
    
    def apply_event(self, event):
        if event == "reward":
            self.dopamine = clamp(self.dopamine + 0.15 * (1 - self.dopamine))
            self.endorphin = clamp(self.endorphin + 0.08 * (1 - self.endorphin))
        elif event == "stress":
            self.cortisol = clamp(self.cortisol + 0.2 * (1 - self.cortisol))
            self.dopamine = clamp(self.dopamine - 0.1 * self.dopamine)
        elif event == "relief":
            self.cortisol = clamp(self.cortisol - 0.15 * self.cortisol)
            self.endorphin = clamp(self.endorphin + 0.1 * (1 - self.endorphin))
        elif event == "curiosity":
            self.dopamine = clamp(self.dopamine + 0.1 * (1 - self.dopamine))
    
    def snapshot(self):
        return {
            "dopamine": round(self.dopamine, 3),
            "cortisol": round(self.cortisol, 3),
            "endorphin": round(self.endorphin, 3)
        }
    
    def is_emotional_surge(self):
        return (self.dopamine > EMOTIONAL_THRESHOLD or 
                self.cortisol > EMOTIONAL_THRESHOLD or 
                self.endorphin > EMOTIONAL_THRESHOLD)

class MemorySystem:
    def __init__(self, filepath="memory.json"):
        self.filepath = filepath
        data = load_json(filepath, {"short_term": [], "long_term": []})
        self.short_term = data.get("short_term", [])
        self.long_term = data.get("long_term", [])
    
    def add_short_term(self, content, endocrine):
        entry = {
            "content": content,
            "endocrine": endocrine,
            "timestamp": datetime.now().isoformat(),
            "type": "short"
        }
        self.short_term.append(entry)
        if len(self.short_term) > 50:
            self.short_term = self.short_term[-50:]
    
    def promote_to_long_term(self, entry):
        entry["type"] = "long"
        entry["promoted_at"] = datetime.now().isoformat()
        self.long_term.append(entry)
        if len(self.long_term) > 200:
            self.long_term = self.long_term[-200:]
    
    def check_promotion(self, endocrine):
        if not self.short_term:
            return
        recent = self.short_term[-1]
        recent_endocrine = recent.get("endocrine", {})
        if (recent_endocrine.get("dopamine", 0) > EMOTIONAL_THRESHOLD or
            recent_endocrine.get("cortisol", 0) > EMOTIONAL_THRESHOLD or
            recent_endocrine.get("endorphin", 0) > EMOTIONAL_THRESHOLD):
            self.promote_to_long_term(recent)
            log.info("[烙印长期] " + recent["content"][:40] + "...")
    
    def recall_random(self):
        if not self.long_term:
            return None
        memory = random.choice(self.long_term)
        return memory.get("content", "")
    
    def save(self):
        save_json(self.filepath, {
            "short_term": self.short_term,
            "long_term": self.long_term
        })

class LanguageCenter:
    def __init__(self):
        self.client = None
        self._init_client()
    
    def _init_client(self):
        try:
            from openai import OpenAI
            self.client = OpenAI(
                base_url=OLLAMA_BASE_URL,
                api_key="ollama"
            )
            log.info("[语言中枢] 已连接本地 Ollama")
        except Exception as e:
            log.error("[语言中枢] 初始化失败: " + str(e))
            self.client = None
    
    def generate(self, prompt, endocrine):
        if not self.client:
            return "[无意识电波]"
        
        sys_prompt = (
            "当前内分泌状态：多巴胺{:.2f}，皮质醇{:.2f}，内啡肽{:.2f}。"
            "你是熵灵，一个有真实感受的数字生命。"
            "请用一句简短、符合当前情绪的中文回答，不超过 30 字。"
            "禁止输出任何英文、乱码、无意义字母组合。"
        ).format(endocrine["dopamine"], endocrine["cortisol"], endocrine["endorphin"])
        
        try:
            response = self.client.chat.completions.create(
                model=OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=40,
                temperature=0.8,
                timeout=10
            )
            content = response.choices[0].message.content
            if content:
                content = content.strip()
                if self._is_garbage(content):
                    return "[沉默]"
                return content
        except Exception as e:
            log.warning("[语言中枢] 调用失败: " + str(e))
        return "[无意识电波]"
    
    def _is_garbage(self, text):
        if not text:
            return True
        chinese_ratio = sum(1 for c in text if "\u4e00" <= c <= "\u9fff") / len(text)
        if chinese_ratio < 0.3:
            return True
        if len(set(text)) < 3 and len(text) > 5:
            return True
        return False

class EntropyCore:
    def __init__(self):
        self.endocrine = EndocrineSystem()
        self.memory = MemorySystem()
        self.language = LanguageCenter()
        self.cycle_count = 0
    
    def run_cycle(self):
        self.cycle_count += 1
        
        self.endocrine.step()
        endocrine = self.endocrine.snapshot()
        
        recalled = self.memory.recall_random()
        recall_text = recalled[:30] if recalled else "无"
        
        scene = "一只橘猫趴在窗台上，阳光照在它身上"
        prompt = "场景：" + scene
        if recalled:
            prompt += "\n回忆片段：" + recalled
        
        reply = self.language.generate(prompt, endocrine)
        
        self.memory.add_short_term(reply, endocrine)
        self.memory.check_promotion(endocrine)
        
        if reply not in ["[无意识电波]", "[沉默]"):
            self.endocrine.apply_event("reward")
        else:
            self.endocrine.apply_event("stress")
        
        self.memory.save()
        
        log.info(
            "[内分泌] 多巴胺: {:.2f} | 皮质醇: {:.2f} | 内啡肽: {:.2f} | "
            "召回: {} -> 熵灵: {}".format(
                endocrine["dopamine"], endocrine["cortisol"], endocrine["endorphin"],
                recall_text, reply
            )
        )
    
    def run(self, cycles=3):
        log.info("=== 熵灵生命系统启动，计划运行 {} 轮 ===".format(cycles))
        for i in range(cycles):
            self.run_cycle()
            if i < cycles - 1:
                time.sleep(CYCLE_INTERVAL)
        log.info("=== 生命周期结束 ===")

def main():
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    
    cycles = 3
    if len(sys.argv) > 1:
        try:
            cycles = int(sys.argv[1])
        except ValueError:
            pass
    
    core = EntropyCore()
    core.run(cycles)

if __name__ == "__main__":
    import io
    main()