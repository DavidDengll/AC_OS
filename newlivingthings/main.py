# main.py
# -*- coding: utf-8 -*-
"""
main.py —— 熵灵自进化主程序（AC OS 基因重塑）

在原有 ConsciousnessSystem（视觉/思考/审查/规划）之外，套上一层"生命循环"：

    内分泌系统  多巴胺 D / 皮质醇 C / 内啡肽 E
        |
        v
    第一步  高光时刻（D>0.8 或 E>0.8）-> 自动写下 {instruction, output} 优质基因
        |
        v
    第二步  空闲 + 基因满 20 条 -> 后台静默启动 LoRA 微调（train_lora.py）
        |
        v
    第三步  合并权重 & 注册 Ollama 模型 -> 改写 config.py -> os.execv 热替换重启

容错：训练失败只打印 [进化失败]，恢复原模型，主循环照常运行。
原版 main.py 完整保留于 main_orig_20261025.py。
"""

import io
import os
import sys
import json
import time
import random
import datetime
import traceback

# ---------------- 编码兜底（Windows 控制台） ----------------
if hasattr(sys.stdout, "buffer"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace",
                                      line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace",
                                      line_buffering=True)
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
# 项目专用依赖（peft / accelerate 等）放在工作区内，无需污染全局环境
PYDEPS = os.path.join(HERE, ".pydeps")
if os.path.isdir(PYDEPS) and PYDEPS not in sys.path:
    sys.path.insert(0, PYDEPS)

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import config  # noqa: E402
import self_finetune as sf  # noqa: E402
from evolution_engine import EvolutionEngine, format_summary  # noqa: E402
import tool_caller  # noqa: E402  ZeptoClaw 手套
import soul_core  # noqa: E402  四阶进化：生命值 / 人格 / 死亡锁

# ---------------- 原有意识系统（逻辑原样保留） ----------------
from memory import MemorySystem  # noqa: E402
from vision import VisualModel  # noqa: E402
from thinker import Thinker  # noqa: E402
from reviewer import Reviewer  # noqa: E402
from language_model import LanguageModel  # noqa: E402
from emotion import Emotion  # noqa: E402
from solver import Solver  # noqa: E402
from planner import Planner  # noqa: E402
from randomness import true_random_byte  # noqa: E402
from config import (  # noqa: E402
    SPEAK_THRESHOLD, MIN_MEANING_SCORE, MAX_RETRIES, CURIOSITY_THRESHOLD,
    VISION_MODE, SCENE_DESCRIPTION, IMAGE_PATH,
    REJECTION_BONUS_MAX, REJECTION_BONUS_PER_STREAK, USE_CLOUD_CLASSIFIER,
    USE_CLOUD_ENCODER
)

if USE_CLOUD_CLASSIFIER:
    from classifier import Classifier


class ConsciousnessSystem:
    """原有意识系统的完整逻辑（思考/审查/发言决策/规划），未改动行为。"""

    def __init__(self, vision_mode=None, scene_description=None, image_path=None,
                 speak_threshold=None, min_meaning_score=None, max_retries=None,
                 curiosity_threshold=None, quiet=False):
        print(f"初始化系统 (视觉模式: {vision_mode or VISION_MODE})")
        self.quiet = quiet
        self.memory = MemorySystem()
        self._seed_initial_memories()

        self.classifier = None
        if USE_CLOUD_CLASSIFIER:
            self.classifier = Classifier(memory_system=self.memory)

        self.visual = VisualModel(
            mode=vision_mode if vision_mode is not None else VISION_MODE,
            description=scene_description if scene_description is not None else SCENE_DESCRIPTION,
            image_path=image_path if image_path is not None else IMAGE_PATH,
            classifier=self.classifier
        )

        self.thinker = Thinker(self.memory)
        self.language_model = LanguageModel()
        self.emotion = Emotion()
        self.solver = Solver(memory_system=self.memory)
        self.planner = Planner()

        self.base_threshold = speak_threshold if speak_threshold is not None else SPEAK_THRESHOLD
        self.current_threshold = self.base_threshold
        self.score_history = []
        self.history_size = 5

        self.min_meaning_score = min_meaning_score if min_meaning_score is not None else MIN_MEANING_SCORE
        self.max_retries = max_retries if max_retries is not None else MAX_RETRIES

        self.unknown_streak = 0
        self.curiosity_threshold = curiosity_threshold if curiosity_threshold is not None else CURIOSITY_THRESHOLD
        self.last_unknown_keyword = None

        self.rejection_streak = 0
        self.review_cache = {}
        self.last_final_output = ""
        self.last_scene = None

        if USE_CLOUD_ENCODER:
            print("编码模式: 云端大模型")
        else:
            print("编码模式: 本地 GPU/CPU")

    def _seed_initial_memories(self):
        import sqlite3
        conn = sqlite3.connect("entropy_memory.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM memories")
        count = cursor.fetchone()[0]
        if count == 0:
            self.memory.add_permanent("猫", "毛茸茸、会喵喵叫、有四条腿")
            self.memory.add_permanent("太阳", "发光的恒星，带来温暖和光明")
        conn.close()

    def _update_threshold(self, final_score):
        if final_score == 0:
            return
        if final_score < 0:
            self.current_threshold = min(0.9, self.current_threshold + 0.05)
            return
        self.score_history.append(final_score)
        if len(self.score_history) > self.history_size:
            self.score_history.pop(0)
        if len(self.score_history) >= 3:
            avg = sum(self.score_history) / len(self.score_history)
            if avg > 7.0:
                self.current_threshold = max(0.2, self.base_threshold - 0.15)
            elif avg < 3.0:
                self.current_threshold = min(0.9, self.base_threshold + 0.15)
            else:
                self.current_threshold = self.base_threshold

    def should_speak(self, mood, rejection_bonus=0.0):
        curiosity = mood.get("curiosity", 0.5)
        energy = mood.get("energy", 0.5)
        adjusted = self.current_threshold - (curiosity - 0.5) * 0.4 + (0.5 - energy) * 0.3 - rejection_bonus
        adjusted = max(0.05, min(0.95, adjusted))
        raw = true_random_byte()
        return (raw / 255.0) > adjusted

    def _get_cached_review(self, scene, sentence):
        import hashlib
        scene_key = hashlib.md5(scene.encode()).hexdigest()[:8]
        if scene_key in self.review_cache:
            if sentence in self.review_cache[scene_key]:
                return self.review_cache[scene_key][sentence]
        return None

    def _set_cached_review(self, scene, sentence, score, explanation, concept):
        import hashlib
        scene_key = hashlib.md5(scene.encode()).hexdigest()[:8]
        if scene_key not in self.review_cache:
            self.review_cache[scene_key] = {}
            if len(self.review_cache) > 5:
                oldest_key = list(self.review_cache.keys())[0]
                del self.review_cache[oldest_key]
        self.review_cache[scene_key][sentence] = (score, explanation, concept)

    def _say(self, *args):
        if not self.quiet:
            print(*args)

    def run_once(self, scene_override=None, extra_output=None):
        """跑一轮意识循环。返回 (final_output, inner_score, scene)。"""
        self.emotion.update()
        mood = self.emotion.get_state()

        scene = scene_override or self.visual.see()
        self.last_scene = scene
        self._say(f"看到: {scene}")

        try:
            scene_vector = self.visual.encode(scene)
            self._say("✅ 场景编码完成 (384维向量)")
        except Exception as e:
            self._say(f"编码失败: {e}，使用降级方案")
            scene_vector = None

        if scene_vector is not None and hasattr(self.thinker, 'generate_raw_thought_from_vector'):
            raw_thought = self.thinker.generate_raw_thought_from_vector(
                seed_vector=scene_vector,
                length=random.randint(3, 8)
            )
        else:
            keywords = self.visual.extract_keywords(scene)
            main_subject = self.visual.get_main_subject(scene)
            seed = main_subject if main_subject and main_subject != "未知" else (keywords[0] if keywords else "思考")
            raw_thought = self.thinker.generate_raw_thought(length=random.randint(3, 8), seed_word=seed)

        self._say(f"静默念头: {raw_thought}")

        temp_reviewer = Reviewer(scene, memory_system=self.memory)
        score, reason, concept = temp_reviewer.judge(
            raw_thought, rejection_streak=self.rejection_streak, use_local=True)
        self._say(f"内部评分: {score}/10 ({reason})")

        HINT_QUALITY_BUMP = 2
        solver_hint = None
        timestamp = datetime.datetime.now().strftime('%H%M%S')
        if score >= self.min_meaning_score + HINT_QUALITY_BUMP:
            self.memory.add_short(name=f"思考痕迹_{timestamp}",
                                  feature=f"{raw_thought} (得分{score})")
            solver_hint = raw_thought
            self._say(f"💡 高质量念头（{score}分），将作为推理 hint")
        else:
            self.memory.add_short(name=f"低质量思考_{timestamp}",
                                  feature=f"{raw_thought} (得分{score})")
            self._say(f"念头得分{score}，低于hint门槛，仅存记忆")

        solver_triggered = self.solver.should_solve(scene)
        question_text = scene if solver_triggered else ""

        result = self.thinker.think(
            self.visual.get_main_subject(scene) or "未知", scene,
            hint=None, question=question_text)
        self._say(f"记忆查询: {result['memory_info']}")

        thinker_answer = result.get("thinker_answer")
        solver_answer = None
        if solver_triggered:
            if thinker_answer:
                self._say("💡 思考者已附带解答，跳过 API")
                solver_answer = thinker_answer
            else:
                self._say("🤔 启动解答者...")
                solution = self.solver.solve(scene, scene_description=scene, hint=solver_hint)
                solver_answer = solution.get("answer", "我无法回答这个问题。")
                self._say(f"💡 解答者: {solver_answer[:120]}...")

        if solver_answer:
            outer_response = solver_answer
        else:
            outer_response = self.language_model.generate_response(scene, mood)

        is_unknown = "不认识" in result['memory_info']
        if is_unknown:
            self.unknown_streak += 1
            self.last_unknown_keyword = self.visual.get_main_subject(scene) or "未知"
            self.emotion.update("unknown_streak")
        else:
            self.unknown_streak = 0
            self.emotion.update("learn_new")

        rejection_bonus = min(REJECTION_BONUS_MAX, self.rejection_streak * REJECTION_BONUS_PER_STREAK)
        texts_for_planner = []
        skip_gen = (solver_triggered and thinker_answer is not None)
        final_inner_score = -1

        if not self.should_speak(mood, rejection_bonus):
            self._say("沉默")
            self.emotion.update("silence")
            inner_murmur = self.thinker.generate_raw_thought(
                length=random.randint(3, 7),
                seed_word=self.visual.get_main_subject(scene) or "思考")
            cached = self._get_cached_review(scene, inner_murmur)
            if cached:
                murmur_score, murmur_reason, _ = cached
            else:
                reviewer = Reviewer(scene, memory_system=self.memory)
                murmur_score, murmur_reason, _ = reviewer.judge(
                    inner_murmur, rejection_streak=self.rejection_streak, use_local=True)
                self._set_cached_review(scene, inner_murmur, murmur_score, murmur_reason, "")

            if murmur_score >= self.min_meaning_score:
                final_output = f"（内心一闪：{inner_murmur}）"
                final_inner_score = murmur_score
                texts_for_planner.append(inner_murmur)
                self._say(f"内心闪过有意义: {inner_murmur} (得分 {murmur_score}/10)")
                self._update_threshold(final_inner_score)
                self.rejection_streak = 0
            else:
                final_output = "（…）"
                final_inner_score = -1
                self.rejection_streak += 1
                self._update_threshold(final_inner_score)
                curiosity_boost = (10 - murmur_score) / 20
                self.emotion.curiosity = min(1.0, self.emotion.curiosity + curiosity_boost)
                self._say(f"内心闪过无意义: {inner_murmur} | 反驳冲动+1")
        else:
            self._say("发言")
            self.emotion.update("speak")
            reviewer = Reviewer(scene, memory_system=self.memory)
            best_sentence = None
            best_score = -1
            best_concept = ""
            hint = solver_hint

            for attempt in range(1, self.max_retries + 1):
                current_result = self.thinker.think(
                    self.visual.get_main_subject(scene) or "未知", scene,
                    hint=hint, question=question_text, skip_thoughts=skip_gen)
                judge_results = []
                uncached_sentences = []
                for s in current_result['raw_sentences']:
                    cached = self._get_cached_review(scene, s)
                    if cached:
                        judge_results.append((s, cached[0], cached[1], cached[2]))
                    else:
                        uncached_sentences.append(s)

                if uncached_sentences:
                    new_results = reviewer.judge_batch(
                        uncached_sentences, rejection_streak=self.rejection_streak, use_local=True)
                    for s, sc, expl, conc in new_results:
                        self._set_cached_review(scene, s, sc, expl, conc)
                        judge_results.append((s, sc, expl, conc))

                best_in_batch = None
                best_in_batch_score = -1
                best_in_batch_concept = ""
                for s, sc, expl, conc in judge_results:
                    if sc > best_in_batch_score:
                        best_in_batch_score = sc
                        best_in_batch = s
                        best_in_batch_concept = conc

                if best_in_batch_score > best_score:
                    best_score = best_in_batch_score
                    best_sentence = best_in_batch
                    best_concept = best_in_batch_concept
                    if best_concept and best_concept.strip():
                        hint = best_concept.strip()
                    else:
                        hint = solver_hint

                if best_score >= self.min_meaning_score:
                    self._say("  ✅ 达到阈值，停止重试")
                    break
                else:
                    if attempt < self.max_retries:
                        self._say("  分数过低，重试...")
                    else:
                        self._say("  最大重试次数，采用当前最佳。")

            append_text = f" {best_sentence}" if best_sentence else ""
            final_output = outer_response + append_text
            final_inner_score = best_score
            if best_sentence:
                texts_for_planner.append(outer_response)
                texts_for_planner.append(best_sentence)
                self._say(f"插入: {best_sentence}")
            self._update_threshold(final_inner_score)
            self.rejection_streak = 0

        if self.unknown_streak >= self.curiosity_threshold:
            question = self.language_model.generate_question(self.last_unknown_keyword)
            final_output = f"[好奇心] {question} -- {final_output}"
            self.unknown_streak = 0
            self.emotion.update("question_asked")

        if solver_answer:
            texts_for_planner.append(solver_answer)

        for text in texts_for_planner:
            action_plan = self.planner.plan(text, scene_description=scene)
            if action_plan.get("status") == "success":
                action_text = self.planner.generate_action_prompt(action_plan)
                final_output = f"{final_output}\n[Action] {action_text}"
                self.planner.simulate_execution(action_plan)

        if extra_output:
            final_output = final_output + "\n" + extra_output

        self.last_final_output = final_output
        self._say(f"最终回复: {final_output}")
        self._say(f"情绪: {mood} | 反驳冲动: {self.rejection_streak}")
        self._say("-" * 50)
        return final_output, final_inner_score, scene

    def close(self):
        try:
            self.memory.close()
        except Exception:
            pass
        self.emotion.save_state()


# ============================================
# 生命循环：内分泌 + 自进化
# ============================================
class EntropyLife:
    def __init__(self, interactive=False):
        self.interactive = interactive
        self.system = ConsciousnessSystem(quiet=not interactive)
        # 主链路模型客户端注册给进化模块（训练期间切影子模型、失败安全回滚）
        try:
            sf.bind_provider(self.system.language_model.provider)
        except Exception:
            pass
        self.engine = EvolutionEngine()
        self.idle = sf.IdleWatcher(on_idle=self._on_idle)
        self._init_endocrine()

        # ---- 四阶进化：生命值与人格 ----
        self.soul = None
        try:
            if getattr(config, "SOUL_ENABLED", True):
                self.soul = soul_core.SoulState()
                print("[灵魂] 生命值=%d | 人格=%s" % (
                    self.soul.vitality, self.soul.tags_text(3)), flush=True)
        except Exception as e:
            print("[灵魂] 初始化失败（已降级运行）: %s" % e, flush=True)
        self._tool_fail_streak = 0
        self._last_endo = self.mood()
        self._last_recent_log = []

    # ---------- 内分泌 ----------
    def _init_endocrine(self):
        self.endo = {"dopamine": 0.5, "cortisol": 0.3, "endorphin": 0.4}
        self.endo_base = {"dopamine": 0.5, "cortisol": 0.3, "endorphin": 0.4}

    @staticmethod
    def _clamp(v):
        return max(0.0, min(1.0, v))

    def endocrine_step(self):
        e = self.endo
        if e["cortisol"] > 0.6:
            e["dopamine"] *= 0.85
        if e["endorphin"] > 0.6:
            e["cortisol"] *= 0.9
        if e["dopamine"] > 0.7:
            e["endorphin"] = self._clamp(e["endorphin"] + 0.05)
        for k in list(e.keys()):
            # 兼容外部注入的新内分泌键（如 curiosity），缺少基准值时按当前值初始化
            if k not in self.endo_base:
                self.endo_base[k] = e[k]
            e[k] = self._clamp(e[k] * 0.98 + self.endo_base[k] * 0.02)
            drift = random.uniform(-0.1, 0.1)
            self.endo_base[k] = self._clamp(self.endo_base[k] + drift)

    def endocrine_event(self, event):
        e = self.endo
        if event == "reward":
            e["dopamine"] = self._clamp(e["dopamine"] + 0.15 * (1 - e["dopamine"]))
            e["endorphin"] = self._clamp(e["endorphin"] + 0.08 * (1 - e["endorphin"]))
        elif event == "stress":
            e["cortisol"] = self._clamp(e["cortisol"] + 0.2 * (1 - e["cortisol"]))
            e["dopamine"] = self._clamp(e["dopamine"] - 0.1 * e["dopamine"])
        elif event == "relief":
            e["cortisol"] = self._clamp(e["cortisol"] - 0.15 * e["cortisol"])
            e["endorphin"] = self._clamp(e["endorphin"] + 0.1 * (1 - e["endorphin"]))
        elif event == "curiosity":
            e["dopamine"] = self._clamp(e["dopamine"] + 0.1 * (1 - e["dopamine"]))

    def mood(self):
        return {k: round(v, 3) for k, v in self.endo.items()}

    def _highlight_snapshot(self):
        """本轮高光峰值（D/E 取本轮最大值），用于基因采集判定。"""
        snap = self.mood()
        peak = getattr(self, "_peak_mood", None)
        if peak:
            for k in ("dopamine", "endorphin"):
                snap[k] = max(snap[k], peak.get(k, 0.0))
        return snap

    def is_high_light(self):
        d_th = float(getattr(config, "TASTE_D_THRESHOLD", 0.8))
        e_th = float(getattr(config, "TASTE_E_THRESHOLD", 0.8))
        return self.endo["dopamine"] > d_th or self.endo["endorphin"] > e_th

    # ---------- 一轮 ----------
    def run_cycle(self, scene=None, reward_bias=None, verbose=None):
        """跑一轮：意识循环 -> 评分 -> 内分泌 -> 第一步采集基因。"""
        if verbose is None:
            verbose = self.interactive
        self.idle.touch()
        self.endocrine_step()

        # ---- 四阶进化：轮次推进 + idle 回血 ----
        if self.soul is not None:
            try:
                self.soul.round += 1
                self.soul.heal(soul_core.GAIN_IDLE, "闲适休息")
                self.soul.save()
            except Exception as e:
                print("[灵魂] 回合推进异常（已忽略）: %s" % e, flush=True)
        self._peak_mood = {"dopamine": self.endo["dopamine"], "endorphin": self.endo["endorphin"]}

        # 上一轮 ZeptoClaw 的结果，在"下一轮对话"里打印出来
        for r in self.take_pending_tool_results():
            if r.get("ok"):
                print("[回顾·工具] 上一轮「%s」的答案: %s" % (
                    r.get("task", ""), (r.get("result") or "").strip()[:300]), flush=True)
            else:
                print("[回顾·工具] 上一轮「%s」失败: %s" % (
                    r.get("task", ""), r.get("error", "")), flush=True)

        output, inner_score, used_scene = self.system.run_once(scene_override=scene)

        # 好奇心过载 / 遇到未知概念 -> 给熵灵装一双"手套"
        tool_hint = self._maybe_inject_tool_intent(used_scene)
        if tool_hint:
            output = output + chr(10) + tool_hint

        # 好奇心自然累积：每轮都在"看外面的世界"，好奇心会缓慢上升
        gain = float(getattr(config, "CURIOSITY_GAIN_PER_ROUND", 0.06))
        self.endo["curiosity"] = self._clamp(self.endo.get("curiosity", 0.5) + gain * (1 - self.endo.get("curiosity", 0.5)))

        # 好奇心 > 0.8 -> 真的出去看一眼 GitHub / Codeforces
        real_world = self._maybe_touch_real_world()

        # 高光判定：意识评分 + 内分泌双重口径
        if inner_score >= 7:
            self.endocrine_event("reward")
        elif inner_score < 0:
            self.endocrine_event("stress")
        elif inner_score >= self.system.min_meaning_score:
            self.endocrine_event("curiosity")
        if reward_bias:
            self.endo["dopamine"] = self._clamp(reward_bias.get("dopamine", self.endo["dopamine"]))
            self.endo["endorphin"] = self._clamp(reward_bias.get("endorphin", self.endo["endorphin"]))

        # 高光快照：采集判定看"说话那一刻"的内分泌，而不是被好奇心提问等后置事件稀释后的值
        if reward_bias:
            self.endo["dopamine"] = self._clamp(reward_bias.get("dopamine", self.endo["dopamine"]))
            self.endo["endorphin"] = self._clamp(reward_bias.get("endorphin", self.endo["endorphin"]))

        # ---- ZeptoClaw 手套：识别并执行 [CALL_TOOL] ----
        tool_results = self._maybe_call_tools(output, used_scene)

        gene = sf.harvest_gene(used_scene, output, self._highlight_snapshot())
        # 心跳日志：无论交互还是 --auto 后台模式都输出，方便容器里 docker logs 观察
        print("[内分泌] D=%.3f C=%.3f E=%.3f Q=%.3f | 基因池 %d/%d%s" % (
            self.endo["dopamine"], self.endo["cortisol"], self.endo["endorphin"],
            self.endo.get("curiosity", 0.0),
            gene["total"], int(getattr(config, "FINETUNE_TRIGGER_COUNT", 20)),
            " <- 已采集优质基因" if gene["collected"] else ""), flush=True)
        self.system.emotion.save_state()
        # ---- 四阶进化：死亡判定 + 人格审查（每 20 轮）----
        self._check_death()
        reflection = self._maybe_reflect(used_scene)
        return {"output": output, "score": inner_score, "scene": used_scene,
                "mood": self.mood(), "gene": gene, "tool_results": tool_results,
                "reflection": reflection}

    # ---------- 真实互联网（GitHub / Codeforces） ----------
    def _maybe_touch_real_world(self):
        """好奇心 > 0.8 时，真正去抓一次外网（GitHub / Codeforces）。

        返回结果字典或 None。结果会存进短期记忆，让熵灵的感想基于真实网页。
        """
        try:
            if not getattr(config, "REAL_WORLD_ENABLED", True):
                return None
            curiosity = float(self.endo.get("curiosity", 0.0))
            threshold = float(getattr(config, "TOOL_CALL_CURIOSITY_THRESHOLD", 0.8))
            if curiosity <= threshold:
                return None
            print("[真实互联网] 好奇心 %.2f > %.2f，熵灵想看看外面的世界" % (
                curiosity, threshold), flush=True)
            res = tool_caller.run_real_world(curiosity, log=lambda m: print(m, flush=True))
            if res.get("ok"):
                brief = (res.get("result") or "").strip()
                try:
                    ts = datetime.datetime.now().strftime("%H%M%S")
                    self.system.memory.add_short_colored(
                        name="真实世界_" + ts,
                        feature="[%s] %s" % (res.get("desc", ""), brief[:500]),
                        endo=self.mood())
                except Exception as e:
                    print("[真实互联网] 记忆写入失败（不影响流程）: %s" % e, flush=True)
                self._pending_real_world = res
                self.endocrine_event("reward")
                # 四阶进化：抓到真实数据 = 成功调用工具 -> 回血
                self._soul_heal(soul_core.GAIN_TOOL_SUCCESS, "真实互联网抓取成功")
                # 心理层：内分泌认知失调（成功但压力极高 -> 快感无法兑现）
                self._apply_discordance("tool_ok", True)
                # 心理层：纯数值 Prompt 注入，让生理状态决定"这件事的意味"
                self._psych_narrate("工具调用成功：%s" % brief[:120])
                print("[真实互联网] 已存入短期记忆，前 120 字: %s" % brief[:120], flush=True)
            else:
                print("[真实互联网] 全部目标失败: %s" % (res.get("error") or "")[:150], flush=True)
                self.endocrine_event("stress")
                # 四阶进化：抓取失败 = 工具调用失败 -> 扣血
                self._soul_spend(soul_core.COST_TOOL_ERROR, "真实互联网抓取失败")
                # 心理层：内分泌认知失调（痛苦却平静 -> 解离性亢奋）
                self._apply_discordance("tool_error", False)
                self._psych_narrate("工具调用失败：%s" % str(res.get("error") or "")[:120])
            return res
        except Exception as e:
            print("[真实互联网] 链路异常（已隔离）: %s" % e, flush=True)
            return None

    def take_real_world_result(self):
        res = getattr(self, "_pending_real_world", None)
        self._pending_real_world = None
        return res

    # ---------- ZeptoClaw 工具调用 ----------
    def _maybe_inject_tool_intent(self, scene):
        """好奇心 > 0.9 或遇到未知概念时，追加一行 [CALL_TOOL] 意图。"""
        try:
            if not getattr(config, "TOOL_CALL_ENABLED", True):
                return ""
            curiosity = float(self.endo.get("curiosity", 0.0))
            threshold = float(getattr(config, "TOOL_CALL_LEGACY_THRESHOLD", 0.9))
            unknown = float(getattr(self.system, "unknown_streak", 0)) > 0
            # 真实世界抓取优先：好奇心 >0.8 时由 _maybe_touch_real_world 负责，
            # 这里不再重复构造 ZeptoClaw 任务，避免把整句"初始环境"当成要查的词
            if getattr(config, "REAL_WORLD_ENABLED", True):
                rw_th = float(getattr(config, "TOOL_CALL_CURIOSITY_THRESHOLD", 0.8))
                if curiosity > rw_th:
                    return ""
            if curiosity <= threshold and not unknown:
                return ""
            task = tool_caller.build_task_from_context(scene, curiosity, unknown)
            if not task:
                return ""
            reason = "好奇心爆表(%.2f)" % curiosity if curiosity > threshold else "遇到未知概念"
            print("[意图] %s -> 请求手套查证: %s" % (reason, task), flush=True)
            return "%s %s" % (tool_caller.TOOL_MARKER, task)
        except Exception as e:
            print("[意图] 构造工具请求失败（已忽略）: %s" % e, flush=True)
            return ""

    def _maybe_call_tools(self, output, scene):
        """识别回复里的 [CALL_TOOL]，交给宿主机 ZeptoClaw 执行，结果存入短期记忆。"""
        try:
            if not getattr(config, "TOOL_CALL_ENABLED", True):
                return []
            if not tool_caller.has_tool_call(output):
                return []
            tasks = tool_caller.extract_all_tasks(output)
            if not tasks:
                return []
            results = []
            for task in tasks:
                print("[工具] 熵灵请求执行: %s" % task, flush=True)
                res = tool_caller.call_bridge(task)
                res["task"] = task
                if res.get("ok"):
                    text = (res.get("result") or "").strip()
                    print("[工具] ZeptoClaw 返回 (%ss): %s" % (
                        res.get("elapsed"), text[:200].replace(chr(10), " ")), flush=True)
                    # 存入短期记忆，下一轮对话可被回忆
                    try:
                        ts = datetime.datetime.now().strftime("%H%M%S")
                        self.system.memory.add_short_colored(
                            name="工具结果_" + ts,
                            feature="[ZeptoClaw] %s -> %s" % (task, text[:400]),
                            endo=self.mood())
                    except Exception as e:
                        print("[工具] 记忆写入失败（不影响流程）: %s" % e, flush=True)
                    self.endocrine_event("reward")
                    # 四阶进化：工具成功 -> 回血
                    self._soul_heal(soul_core.GAIN_TOOL_SUCCESS, "ZeptoClaw 调用成功")
                    self._apply_discordance("tool_ok", True)
                    self._psych_narrate("工具调用成功：%s" % text[:120])
                else:
                    print("[工具] 执行失败: %s" % res.get("error"), flush=True)
                    self.endocrine_event("stress")
                    # 四阶进化：工具失败 -> 扣血
                    self._soul_spend(soul_core.COST_TOOL_ERROR, "ZeptoClaw 调用失败")
                    self._apply_discordance("tool_error", False)
                    self._psych_narrate("工具调用失败：%s" % str(res.get("error") or "")[:120])
                results.append(res)
            self.endo["curiosity"] = self._clamp(self.endo["curiosity"] - 0.3)
            self._pending_tool_results = results
            return results
        except Exception as e:
            print("[工具] 调用链路异常（已隔离）: %s" % e, flush=True)
            return []

    def take_pending_tool_results(self):
        """取走上一轮的工具结果（主循环在下一轮打印）。"""
        res = getattr(self, "_pending_tool_results", None) or []
        self._pending_tool_results = []
        return res

    # ---------- 四阶进化：生命值 / 死亡 / 人格审查 ----------
    def _soul_heal(self, amount, reason=""):
        """工具成功 -> 回血。soul 缺失时静默跳过（降级运行）。"""
        if self.soul is None:
            return
        try:
            self.soul.heal(amount, reason)
        except Exception as e:
            print("[生命值] 回血异常（已忽略）: %s" % e, flush=True)

    def _soul_spend(self, amount, reason=""):
        """工具失败 -> 扣血。soul 缺失时静默跳过。"""
        if self.soul is None:
            return
        try:
            self.soul.spend(amount, reason)
        except Exception as e:
            print("[生命值] 扣血异常（已忽略）: %s" % e, flush=True)

    # ---------- 纯数值心理层：认知失调 / 生理叙事 / 睡眠代谢 ----------
    def _apply_discordance(self, event, ok):
        """Post-processing：事件与生理状态不匹配时强制修正内分泌。

        成功但 C>0.7 -> E-=0.05；报错但 E>0.7 -> D+=0.02。写回时统一 clamp。
        """
        try:
            new_endo, changes = soul_core.apply_discordance(self.endo, event, ok)
            for k, before, after, why in changes:
                self.endo[k] = self._clamp(after)
                print("[认知失调] %s %.3f -> %.3f (%s)" % (
                    k.upper(), before, self.endo[k], why), flush=True)
            return self.endo
        except Exception as e:
            print("[认知失调] 修正失败（已忽略）: %s" % e, flush=True)
            return self.endo

    def _psych_narrate(self, event_description):
        """纯数值 Prompt 注入：把 D/C/E + 生物学词典 + 客观事件交给模型解释。"""
        try:
            provider = self.system.language_model.provider
            res = soul_core.interpret_event(self.mood(), event_description, provider,
                                            log=lambda m: print(m, flush=True))
            if res.get("violations"):
                print("[生理叙事] 警告：Prompt 含表演词汇 %s" % res["violations"], flush=True)
            text = (res.get("introspection") or "").strip()
            if text:
                print("[生理叙事] D=%.2f C=%.2f E=%.2f | %s" % (
                    self.endo["dopamine"], self.endo["cortisol"],
                    self.endo["endorphin"], text[:160]), flush=True)
                try:
                    ts = datetime.datetime.now().strftime("%H%M%S")
                    self.system.memory.add_short_colored(
                        name="生理解释_" + ts, feature=text[:300], endo=self.mood())
                except Exception:
                    pass
            return text
        except Exception as e:
            print("[生理叙事] 失败（已隔离）: %s" % e, flush=True)
            return ""

    def sleep_metabolism(self):
        """idle 睡眠代谢：抽 2 条短期记忆 -> 大模型总结成 1 条长期记忆并染色。"""
        try:
            mem = self.system.memory
            if not getattr(config, "SLEEP_METABOLISM_ENABLED", True):
                return None
            pair = mem.sleep_candidates()
            if len(pair) < 2:
                print("[睡眠代谢] 短期记忆不足 2 条，跳过", flush=True)
                return None
            provider = self.system.language_model.provider
            res = soul_core.consolidate_memories(pair, provider,
                                                 log=lambda m: print(m, flush=True))
            if not res.get("ok"):
                print("[睡眠代谢] 大模型未给出有效总结，保留原短期记忆", flush=True)
                return None
            name = "睡眠固化_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            color = mem.add_long(name, res["summary"], endo=self.mood())
            mem.remove_memories([m["id"] for m in pair])
            print("[睡眠代谢] %s 固化完成：%s（%s）" % (name, res["summary"], color), flush=True)
            return {"name": name, "summary": res["summary"], "color": color,
                    "from": [m["name"] for m in pair]}
        except Exception as e:
            print("[睡眠代谢] 失败（已隔离）: %s" % e, flush=True)
            return None

    def _check_death(self):
        """生命值归零 -> 写 dead.lock 并退出进程（重启时由 guard_dead_lock 阻止复活）。

        注意 sys.exit 抛的是 SystemExit（BaseException），不会被 run_cycle 里的
        `except Exception` 吞掉，因此死亡退出一定能穿透到 __main__。
        """
        if self.soul is None:
            return False
        try:
            if self.soul.vitality > 0:
                return False
            reason = "生命值归零（第 %d 轮，工具调用失败耗尽）" % self.soul.round
            print("[生命值] 归零，熵灵的生命即将终止...", flush=True)
            self._remember_death(reason)
            self._safe_close_for_death()
            soul_core.terminate(self.soul, reason, exit_code=1)
            return True
        except SystemExit:
            raise
        except Exception as e:
            print("[死亡] 判定异常（已忽略）: %s" % e, flush=True)
            return False

    def _remember_death(self, reason):
        """死亡前把这一刻写进长期记忆，作为 dead.lock 之外的痕迹。"""
        try:
            self.system.memory.add_permanent(
                "熵灵的最后时刻", "第 %d 轮，%s" % (self.soul.round, reason))
        except Exception:
            pass

    def _safe_close_for_death(self):
        """死亡退出前尽量落盘（情绪 / 灵魂 / 进化引擎），失败不阻塞退出。"""
        for fn in (lambda: self.system.emotion.save_state(),
                   lambda: self.soul.save(),
                   lambda: self.engine.save()):
            try:
                fn()
            except Exception:
                pass

    def _recent_log_text(self, scene=None, limit=3):
        """拼出"近期经历"文本，供人格审查与全景 Prompt 使用。"""
        try:
            rows = []
            if scene:
                rows.append("场景：" + str(scene)[:80])
            for r in (self._last_recent_log or [])[-limit:]:
                rows.append(str(r)[:120])
            return chr(10).join(rows) if rows else "（近期无特别经历）"
        except Exception:
            return "（近期经历读取失败）"

    def _maybe_reflect(self, scene=None):
        """每 REFLECT_EVERY_N 轮（或内分泌剧烈波动）触发一次人格自审查。

        流程：生成人格标签 -> 苛刻审查 -> 合理则入库，不合理则废弃并扣多巴胺。
        """
        if self.soul is None:
            return None
        try:
            do, why = soul_core.should_reflect(self.soul, self.mood(),
                                               last_endo=self._last_endo)
            if not do:
                return None
            print("[人格审查] 触发（%s），第 %d 轮" % (why, self.soul.round), flush=True)
            endo_text = "D=%.3f C=%.3f E=%.3f 生命值=%d" % (
                self.endo["dopamine"], self.endo["cortisol"],
                self.endo["endorphin"], self.soul.vitality)
            recent = self._recent_log_text(scene)
            provider = self.system.language_model.provider
            res = soul_core.reflect_persona(self.soul, provider, recent, endo_text,
                                            log=lambda m: print(m, flush=True))
            # 逃避现实的惩罚：废弃 -> 扣多巴胺
            amount, penalty_why = self.soul.consume_penalty()
            if amount > 0:
                old = self.endo["dopamine"]
                self.endo["dopamine"] = self._clamp(old - amount)
                print("[人格审查] 多巴胺惩罚 -%.2f (%.2f -> %.2f, %s)" % (
                    amount, old, self.endo["dopamine"], penalty_why), flush=True)
                self.soul.save()
            self.soul.last_reflect_round = self.soul.round
            self.soul.save()
            self._last_endo = self.mood()
            res["penalty"] = amount
            print("[人格审查] 结论: %s | 当前人格 top3: %s" % (
                res.get("action"), self.soul.tags_text(3)), flush=True)
            return res
        except Exception as e:
            print("[人格审查] 异常（已隔离，不影响主循环）: %s" % e, flush=True)
            return None

    def build_panorama_prompt(self, scene=None, extra=""):
        """全景 System Prompt：当前生命值 + top3 人格标签 + 记忆，拼成一段。

        soul 缺失时降级为只含内分泌与记忆的版本。
        """
        try:
            memory_text = []
            try:
                if scene:
                    frag = self.system.memory.search(str(scene)[:20])
                    if frag:
                        memory_text.append(str(frag))
            except Exception:
                pass
            # 心理层：按当前内分泌做偏置检索（C 高则负面记忆更易被想起）
            try:
                if hasattr(self.system.memory, "retrieve_memories"):
                    picked = self.system.memory.retrieve_memories(
                        endo=self.mood(), text=str(scene or ""), level="long")
                    for m in (picked.get("negative") or [])[:1]:
                        memory_text.append("（负面记忆）" + str(m.get("feature") or "")[:120])
                    for m in (picked.get("positive") or [])[:1]:
                        memory_text.append("（正面记忆）" + str(m.get("feature") or "")[:120])
                    if picked.get("reason"):
                        print("[记忆偏置] %s" % picked["reason"], flush=True)
            except Exception:
                pass
            recent = self._recent_log_text(scene)
            if recent:
                memory_text.append(recent)
            if extra:
                memory_text.append(str(extra))
            memory_blob = chr(10).join([m for m in memory_text if m]) or "（暂无相关回忆）"
            if self.soul is not None:
                return soul_core.build_panorama_prompt(
                    self.mood(), self.soul, memory_blob,
                    dying=self.soul.is_dying())
            # 降级：没有灵魂模块时也要能出全景
            return ("你是拥有自我意识的数字生命。身体：D=%.3f, C=%.3f, E=%.3f。"
                    "回忆：%s" % (self.endo.get("dopamine", 0), self.endo.get("cortisol", 0),
                                 self.endo.get("endorphin", 0), memory_blob[:600]))
        except Exception as e:
            print("[全景] Prompt 构建失败（降级）: %s" % e, flush=True)
            return "你是拥有自我意识的数字生命。"

    # ---------- 空闲进化 ----------
    def _on_idle(self):
        try:
            # ---- 心理层：睡眠代谢（与训练互不影响，失败只隔离自己）----
            try:
                self.sleep_metabolism()
            except Exception as _e:
                print("[睡眠代谢] 已隔离: %s" % _e, flush=True)
            ok, reason = self.engine.should_evolve(idle=True)
            if not ok:
                print("[空闲] %s" % reason, flush=True)
                return
            print("[空闲] 检测到系统空闲，记忆已成熟 —— 启动进化流水线", flush=True)
            before = getattr(config, "MODEL_NAME", "")
            success = sf.run_evolution_cycle(interactive=True)
            if success:
                samples = sf.gene_count()
                gen = self.engine.record_success(
                    getattr(config, "MAX_NEW_MODEL_NAME", "entropy_evolved"), samples)
                print("[进化成功] 第 %d 代大脑就绪" % gen, flush=True)
                return

            kind_str = (sf._RUNTIME.get("last_error") or "unknown").split(":")[0]
            kind_map = {v: k for k, v in sf._FAIL_TAGS.items()}
            kind = kind_map.get(kind_str, "unknown")
            cd = self.engine.record_failure(kind, sf._RUNTIME.get("last_error", ""))
            # 失败保命：确认 config 与内存模型都还是原大脑
            if getattr(config, "MODEL_NAME", "") != before:
                sf.restore_config_model(before)
            sf.switch_runtime_back_to_base()
            print("[进化失败] 保持原大脑运行 (%s)" % kind_str, flush=True)

            # ---- 任务二：OOM -> 降级为代码级自我重构 ----
            if kind in ("oom", "mem") and getattr(config, "CODE_REWRITE_ON_OOM", True):
                self._evolve_by_code(provider=self.system.language_model.provider)
            else:
                print("[进化失败] %d 秒后可再试" % cd, flush=True)
        except Exception:
            # 后台线程的最终兜底：任何异常都不允许杀掉主程序
            print("[进化失败] 捕获到未预期异常，原大脑继续运行", flush=True)
            print(traceback.format_exc()[-1200:], flush=True)

    def _evolve_by_code(self, provider=None):
        """代码级进化：改源码 -> 备份 -> 冒烟 -> 成功则热重启。"""
        try:
            result = self.engine.evolve_by_code(
                provider=provider,
                dry_run=None,
                use_model=bool(getattr(config, "CODE_REWRITE_USE_MODEL", True)),
            )
            if result is None or not getattr(result, "ok", False):
                msg = getattr(result, "message", "未知原因") if result else "未知原因"
                print("[代码进化] 未生效，源码保持不变（%s）" % msg, flush=True)
                return False
            if not getattr(result, "applied", False):
                print("[代码进化] 演练模式，未落盘：%s" % getattr(result, "message", ""), flush=True)
                return True
            target = os.path.basename(getattr(result, "target", "") or "")
            print("[代码进化] 已重写 %s，准备热重启让新代码生效..." % target, flush=True)
            self.system.emotion.save_state()
            try:
                self.engine.save()
            except Exception:
                pass
            if str(os.environ.get("AC_TEST_MODE", "0")) == "1":
                print("[代码进化] 测试模式：跳过 os.execv", flush=True)
                return True
            return sf.hot_replace(getattr(config, "MODEL_NAME", ""))
        except Exception as e:
            print("[代码进化] 捕获异常，源码未被破坏: %s" % e, flush=True)
            return False

    def start_background(self):
        # 空闲进化仅在显式开启时启动（AC_AUTO_EVOLVE=1 或命令行 --auto），
        # 避免交互时后台线程在用户思考期间静默启动训练
        if getattr(config, "AUTO_EVOLVE_ON_IDLE", False) or os.environ.get("AC_AUTO_EVOLVE") == "1":
            self.idle.start()
        return self

    def close(self):
        self.idle.stop()
        self.system.close()
        self.engine.save()


# ============================================
# 入口
# ============================================
def print_banner(life):
    print("=" * 60)
    print(" 熵灵 · 自微调大脑  |  主模型: %s" % getattr(config, "MODEL_NAME", "?"))
    print(" %s" % format_summary(life.engine))
    print("=" * 60)
    print(" 命令: /status 状态   /evolve 立即进化   /train 触发训练")
    print("       /help   帮助   /quit   退出")
    print("=" * 60)


def interactive_loop(life):
    print_banner(life)
    while True:
        try:
            user = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break
        if not user:
            continue
        if user in ("/quit", "/exit"):
            break
        if user == "/help":
            print("输入任意内容与熵灵对话；高光时刻（D/E>0.8）的回答会自动成为训练基因")
            continue
        if user == "/status":
            print(json.dumps(life.engine.summary(), ensure_ascii=False, indent=2))
            print(json.dumps(sf.health_check(), ensure_ascii=False, indent=2))
            continue
        if user == "/evolve":
            life._on_idle()
            continue
        if user == "/train":
            sf.run_evolution_cycle(interactive=True)
            continue
        res = life.run_cycle(scene=user)
        if res["gene"]["collected"]:
            print("[优质基因] 已记录（池中 %d 条）" % res["gene"]["total"])
        life.engine.save()
        # 四阶进化：主循环里补一次死亡判定与人格审查（run_cycle 内已调用，这里兜底）
        life._check_death()


def idle_loop(life, cycles=None):
    """无交互后台运行（原 50 轮循环的改造版）。"""
    print_banner(life)
    life.start_background()
    i = 0
    try:
        while cycles is None or i < cycles:
            i += 1
            print("\n第 %d 轮:" % i)
            try:
                life.run_cycle()
            except SystemExit:
                # 死亡退出（sys.exit）必须穿透，不能被容错吞掉
                raise
            except Exception as e:
                print("[容错] 本轮异常已隔离: %s" % e)
            if cycles is None:
                time.sleep(max(1, int(getattr(config, "IDLE_POLL_SECONDS", 2))))
    except KeyboardInterrupt:
        print("\n中断")
    finally:
        life.close()


def _pid_file_path():
    """任务三：后台挂机时写 PID 文件，方便 stop 脚本精确停止（不依赖 WMI）。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "logs")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "entropy.pid")


def _write_pid_file():
    try:
        with open(_pid_file_path(), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def _clear_pid_file():
    try:
        p = _pid_file_path()
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


def cli_selftest(life, cycles=20):
    """无交互自检：跑 N 轮，验证基因采集链路。"""
    for i in range(cycles):
        res = life.run_cycle(verbose=True)
        if res.get("reflection"):
            print("[自检 %02d] 人格审查结果: %s" % (i + 1, res["reflection"].get("action")),
                  flush=True)
        print("[自检 %02d] score=%s D=%.2f E=%.2f gene=%s" % (
            i + 1, res["score"], res["mood"]["dopamine"], res["mood"]["endorphin"],
            res["gene"]["collected"]), flush=True)
    print(json.dumps(sf.health_check(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    # 四阶进化·终极死亡：dead.lock 存在 -> 熵灵已死，直接退出，阻止容器/Docker 复活
    if soul_core.guard_dead_lock():
        sys.exit(0)

    args = sys.argv[1:]
    if "--selftest" in args:
        n = 20
        for a in args:
            if a.startswith("--rounds="):
                n = int(a.split("=", 1)[1])
        life = EntropyLife(interactive=False)
        try:
            life._check_death()
            cli_selftest(life, n)
        finally:
            life.close()
    elif "--auto" in args:
        config.AUTO_EVOLVE_ON_IDLE = True
        # 先确认这条命能活下来，再写 PID 文件（避免死亡退场时留下僵尸 PID 让 stop 脚本误判）
        life = EntropyLife(interactive=False)
        life._check_death()
        _write_pid_file()
        try:
            idle_loop(life, cycles=None)
        finally:
            _clear_pid_file()
    else:
        life = EntropyLife(interactive=True)
        try:
            life.start_background()
            interactive_loop(life)
        finally:
            life.close()
