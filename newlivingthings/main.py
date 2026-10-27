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
        for k in e:
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
        self._peak_mood = {"dopamine": self.endo["dopamine"], "endorphin": self.endo["endorphin"]}

        output, inner_score, used_scene = self.system.run_once(scene_override=scene)

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
        gene = sf.harvest_gene(used_scene, output, self._highlight_snapshot())
        # 心跳日志：无论交互还是 --auto 后台模式都输出，方便容器里 docker logs 观察
        print("[内分泌] D=%.3f C=%.3f E=%.3f | 基因池 %d/%d%s" % (
            self.endo["dopamine"], self.endo["cortisol"], self.endo["endorphin"],
            gene["total"], int(getattr(config, "FINETUNE_TRIGGER_COUNT", 20)),
            " <- 已采集优质基因" if gene["collected"] else ""), flush=True)
        self.system.emotion.save_state()
        return {"output": output, "score": inner_score, "scene": used_scene,
                "mood": self.mood(), "gene": gene}

    # ---------- 空闲进化 ----------
    def _on_idle(self):
        try:
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
        print("[自检 %02d] score=%s D=%.2f E=%.2f gene=%s" % (
            i + 1, res["score"], res["mood"]["dopamine"], res["mood"]["endorphin"],
            res["gene"]["collected"]), flush=True)
    print(json.dumps(sf.health_check(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selftest" in args:
        n = 20
        for a in args:
            if a.startswith("--rounds="):
                n = int(a.split("=", 1)[1])
        life = EntropyLife(interactive=False)
        try:
            cli_selftest(life, n)
        finally:
            life.close()
    elif "--auto" in args:
        config.AUTO_EVOLVE_ON_IDLE = True
        _write_pid_file()
        life = EntropyLife(interactive=False)
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
