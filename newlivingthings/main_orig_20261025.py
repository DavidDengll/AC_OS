# main.py
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from memory import MemorySystem
from vision import VisualModel
from thinker import Thinker
from reviewer import Reviewer
from language_model import LanguageModel
from emotion import Emotion
from solver import Solver
from planner import Planner
from randomness import true_random_byte
from config import (
    SPEAK_THRESHOLD, MIN_MEANING_SCORE, MAX_RETRIES, CURIOSITY_THRESHOLD,
    VISION_MODE, SCENE_DESCRIPTION, IMAGE_PATH,
    REJECTION_BONUS_MAX, REJECTION_BONUS_PER_STREAK, USE_CLOUD_CLASSIFIER,
    USE_CLOUD_ENCODER
)
import random
import datetime

if USE_CLOUD_CLASSIFIER:
    from classifier import Classifier

class ConsciousnessSystem:
    def __init__(self, vision_mode=None, scene_description=None, image_path=None,
                 speak_threshold=None, min_meaning_score=None, max_retries=None,
                 curiosity_threshold=None):
        print(f"初始化系统 (视觉模式: {vision_mode or VISION_MODE})")
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

        # 打印编码模式
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

    def run_once(self):
        self.emotion.update()
        mood = self.emotion.get_state()

        scene = self.visual.see()
        print(f"看到: {scene}")

        # ----- 双模编码 -----
        try:
            scene_vector = self.visual.encode(scene)
            print(f"✅ 场景编码完成 (384维向量)")
        except Exception as e:
            print(f"编码失败: {e}，使用降级方案")
            scene_vector = None

        # 静默思考阶段（优先用向量，否则用关键词）
        if scene_vector is not None and hasattr(self.thinker, 'generate_raw_thought_from_vector'):
            raw_thought = self.thinker.generate_raw_thought_from_vector(
                seed_vector=scene_vector,
                length=random.randint(3, 8)
            )
        else:
            # 降级：用关键词作为种子
            keywords = self.visual.extract_keywords(scene)
            main_subject = self.visual.get_main_subject(scene)
            seed = main_subject if main_subject and main_subject != "未知" else (keywords[0] if keywords else "思考")
            raw_thought = self.thinker.generate_raw_thought(length=random.randint(3, 8), seed_word=seed)

        print(f"静默念头: {raw_thought}")

        # 本地审查
        temp_reviewer = Reviewer(scene, memory_system=self.memory)
        score, reason, concept = temp_reviewer.judge(
            raw_thought,
            rejection_streak=self.rejection_streak,
            use_local=True
        )
        print(f"内部评分: {score}/10 ({reason})")

        # 质量门槛
        HINT_QUALITY_BUMP = 2
        solver_hint = None
        timestamp = datetime.datetime.now().strftime('%H%M%S')
        if score >= self.min_meaning_score + HINT_QUALITY_BUMP:
            self.memory.add_short(
                name=f"思考痕迹_{timestamp}",
                feature=f"{raw_thought} (得分{score})"
            )
            solver_hint = raw_thought
            print(f"💡 高质量念头（{score}分），将作为推理 hint")
        else:
            self.memory.add_short(
                name=f"低质量思考_{timestamp}",
                feature=f"{raw_thought} (得分{score})"
            )
            print(f"念头得分{score}，低于hint门槛，仅存记忆")

        # 判断是否触发解答者
        solver_triggered = self.solver.should_solve(scene)
        question_text = scene if solver_triggered else ""

        result = self.thinker.think(
            self.visual.get_main_subject(scene) or "未知",
            scene,
            hint=None,
            question=question_text
        )
        print(f"记忆查询: {result['memory_info']}")

        thinker_answer = result.get("thinker_answer")

        solver_answer = None
        if solver_triggered:
            if thinker_answer:
                print("💡 思考者已附带解答，跳过 API")
                solver_answer = thinker_answer
            else:
                print("🤔 启动解答者...")
                solution = self.solver.solve(scene, scene_description=scene, hint=solver_hint)
                solver_answer = solution.get("answer", "我无法回答这个问题。")
                print(f"💡 解答者: {solver_answer[:120]}...")

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

        # 发言决策
        if not self.should_speak(mood, rejection_bonus):
            print("沉默")
            self.emotion.update("silence")
            inner_murmur = self.thinker.generate_raw_thought(
                length=random.randint(3, 7),
                seed_word=self.visual.get_main_subject(scene) or "思考"
            )
            cached = self._get_cached_review(scene, inner_murmur)
            if cached:
                murmur_score, murmur_reason, _ = cached
            else:
                reviewer = Reviewer(scene, memory_system=self.memory)
                murmur_score, murmur_reason, _ = reviewer.judge(
                    inner_murmur,
                    rejection_streak=self.rejection_streak,
                    use_local=True
                )
                self._set_cached_review(scene, inner_murmur, murmur_score, murmur_reason, "")

            if murmur_score >= self.min_meaning_score:
                final_output = f"（内心一闪：{inner_murmur}）"
                final_inner_score = murmur_score
                texts_for_planner.append(inner_murmur)
                print(f"内心闪过有意义: {inner_murmur} (得分 {murmur_score}/10)")
                self._update_threshold(final_inner_score)
                self.rejection_streak = 0
            else:
                final_output = "（…）"
                final_inner_score = -1
                self.rejection_streak += 1
                self._update_threshold(final_inner_score)
                curiosity_boost = (10 - murmur_score) / 20
                self.emotion.curiosity = min(1.0, self.emotion.curiosity + curiosity_boost)
                print(f"内心闪过无意义: {inner_murmur} | 反驳冲动+1")
        else:
            print("发言")
            self.emotion.update("speak")
            reviewer = Reviewer(scene, memory_system=self.memory)
            best_sentence = None
            best_score = -1
            best_concept = ""
            hint = solver_hint

            for attempt in range(1, self.max_retries + 1):
                current_result = self.thinker.think(
                    self.visual.get_main_subject(scene) or "未知",
                    scene,
                    hint=hint,
                    question=question_text,
                    skip_thoughts=skip_gen
                )
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
                        uncached_sentences,
                        rejection_streak=self.rejection_streak,
                        use_local=True
                    )
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
                    print(f"  ✅ 达到阈值，停止重试")
                    break
                else:
                    if attempt < self.max_retries:
                        print("  分数过低，重试...")
                    else:
                        print("  最大重试次数，采用当前最佳。")

            append_text = f" {best_sentence}" if best_sentence else ""
            final_output = outer_response + append_text
            final_inner_score = best_score
            if best_sentence:
                texts_for_planner.append(outer_response)
                texts_for_planner.append(best_sentence)
                print(f"插入: {best_sentence}")
            self._update_threshold(final_inner_score)
            self.rejection_streak = 0

        # 好奇心提问
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

        self.last_final_output = final_output
        print(f"最终回复: {final_output}")
        print(f"情绪: {mood} | 反驳冲动: {self.rejection_streak}")
        print("-" * 50)

    def close(self):
        self.memory.close()
        self.emotion.save_state()

if __name__ == "__main__":
    system = ConsciousnessSystem()
    print("=== 熵灵系统启动 ===\n")
    try:
        for i in range(50):
            print(f"第 {i+1} 轮:")
            system.run_once()
    except KeyboardInterrupt:
        print("\n中断")
    finally:
        system.close()