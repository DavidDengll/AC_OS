# reviewer.py
from model_provider import get_provider
from config import REJECTION_LENIENT_THRESHOLD
from utils import clean_and_parse_json
import random
import numpy as np

class Reviewer:
    def __init__(self, visual_summary, memory_system=None):
        self.visual_summary = visual_summary
        self.memory_system = memory_system
        self.provider = get_provider()
        self.encoder = None
        self._encoder_available = False
        self._load_encoder()

    def _load_encoder(self):
        """尝试加载语义模型，失败则标记不可用"""
        try:
            from sentence_transformers import SentenceTransformer
            self.encoder = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            self._encoder_available = True
        except Exception as e:
            print(f"加载语义模型失败（将使用词袋回退）: {e}")
            self._encoder_available = False

    def _local_semantic_score(self, sentence, context):
        """
        本地打分：优先使用语义向量相似度，若不可用则使用 jieba 词袋重叠度
        """
        # 如果语义模型可用，使用向量相似度
        if self._encoder_available and self.encoder is not None:
            try:
                sent_vec = self.encoder.encode(sentence)
                ctx_vec = self.encoder.encode(context)
                sim = np.dot(sent_vec, ctx_vec) / (np.linalg.norm(sent_vec) * np.linalg.norm(ctx_vec) + 1e-8)
                score = int(sim * 10)
                return max(0, min(10, score))
            except Exception:
                pass  # 失败则继续降级

        # 降级：使用 jieba 词袋重叠度
        try:
            import jieba
            sent_words = set(jieba.lcut(sentence))
            ctx_words = set(jieba.lcut(context))
            if not sent_words or not ctx_words:
                return 5
            overlap = sent_words & ctx_words
            # 用重叠词数 / 总词数 映射到 0-10
            total = max(len(sent_words), len(ctx_words))
            score = int(len(overlap) / total * 10) if total > 0 else 5
            return max(0, min(10, score))
        except ImportError:
            return 5  # 终极回退

    def judge_batch(self, raw_sentences, rejection_streak=0, use_local=False):
        if not raw_sentences:
            return []

        # 本地模式或 API 不可用
        if use_local:
            print(f"使用本地语义评分 {len(raw_sentences)} 个念头...")
            results = []
            for s in raw_sentences:
                score = self._local_semantic_score(s, self.visual_summary)
                if rejection_streak >= REJECTION_LENIENT_THRESHOLD:
                    score = min(10, score + random.randint(1, 2))
                results.append((s, score, "本地语义评分", ""))
            return results

        # ---- API 审查（原逻辑） ----
        memory_context = ""
        if self.memory_system:
            keywords = [w.strip() for w in self.visual_summary.replace("，", " ").replace("。", " ").split() if len(w.strip()) >= 1]
            related_memories = []
            for kw in keywords[:3]:
                cursor = self.memory_system.conn.cursor()
                cursor.execute(
                    "SELECT name, feature FROM memories WHERE (name LIKE ? OR feature LIKE ?) AND level IN ('permanent','long') LIMIT 3",
                    (f"%{kw}%", f"%{kw}%")
                )
                rows = cursor.fetchall()
                for r in rows:
                    if r not in related_memories:
                        related_memories.append(r)
            if related_memories:
                memory_context = "相关的已知概念：\n" + "\n".join([f"- {r[0]}：{r[1]}" for r in related_memories[:8]])

        sentences_text = "\n".join([f"{i+1}. {s}" for i, s in enumerate(raw_sentences)])

        rejection_hint = ""
        if rejection_streak >= REJECTION_LENIENT_THRESHOLD:
            rejection_hint = f"注意：发言者已连续被否定 {rejection_streak} 次，可能带有反驳或证明自己的情绪。请对边缘分数稍微宽容（+1分范围内）。"
        elif rejection_streak >= 1:
            rejection_hint = f"注意：发言者已连续被否定 {rejection_streak} 次。"

        system_prompt = f"""你是一个严格但公正的语义审查官。
你的任务是批量判断多个"内心念头"是否和当前看到的场景有语义关联。

评分标准：
- 0分：完全无关，纯随机乱码
- 1~3分：有微弱关联
- 4~6分：有一定关联
- 7~9分：明确相关
- 10分：完美契合

{rejection_hint}

{memory_context}

【严格要求】请只返回一个 JSON 数组，不要包含任何其他文字、注释或 Markdown 标记。
数组中的每个元素对应一个念头的审查结果，顺序与输入的念头顺序一致。
格式如下：
[
  {{"score": 分数(整数), "explanation": "解释", "concept": "最相关概念"}},
  ...
]
"""

        user_prompt = f"当前场景：{self.visual_summary}\n待审查的念头：\n{sentences_text}"

        print(f"批量审查 {len(raw_sentences)} 个念头（API）...")

        try:
            result_text = self.provider.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0,
                max_tokens=800
            )
            if not result_text:
                print("❌ API 返回空，降级到本地评分")
                return self.judge_batch(raw_sentences, rejection_streak, use_local=True)

            parsed = clean_and_parse_json(result_text)
            if parsed and isinstance(parsed, list):
                results = []
                for i, item in enumerate(parsed):
                    if i >= len(raw_sentences):
                        break
                    score = item.get("score", 0)
                    if not isinstance(score, (int, float)):
                        score = 0
                    score = max(0, min(10, int(score)))
                    explanation = item.get("explanation", "解析成功")
                    concept = item.get("concept", "")
                    results.append((raw_sentences[i], score, explanation, concept))
                while len(results) < len(raw_sentences):
                    results.append((raw_sentences[len(results)], 0, "数据缺失", ""))
                return results
            else:
                print(f"解析 JSON 失败，降级到本地评分")
                return self.judge_batch(raw_sentences, rejection_streak, use_local=True)
        except Exception as e:
            print(f"❌ API 审查异常: {e}，降级到本地评分")
            return self.judge_batch(raw_sentences, rejection_streak, use_local=True)

    def judge(self, raw_sentence, rejection_streak=0, use_local=False):
        results = self.judge_batch([raw_sentence], rejection_streak, use_local)
        if results:
            _, score, explanation, concept = results[0]
            print(f"审查结果: {score}/10 - {explanation} | 关联概念: {concept}")
            return score, explanation, concept
        return 0, "审查失败", ""