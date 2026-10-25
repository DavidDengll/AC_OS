# thinker.py
from randomness import true_random_int, true_random_byte, true_random_bool
from config import MEMORY_INFLUENCE_PROB, WORD_INSERT_PROB, MOSAIC_PROB, HINT_USE_PROB
from model_provider import get_provider
import random
import datetime
import re
import numpy as np

class Thinker:
    def __init__(self, memory_system, memory_influence_prob=None, word_insert_prob=None):
        self.memory = memory_system
        self.memory_influence_prob = memory_influence_prob if memory_influence_prob is not None else MEMORY_INFLUENCE_PROB
        self.word_insert_prob = word_insert_prob if word_insert_prob is not None else WORD_INSERT_PROB
        self.provider = get_provider()
        self._search_cache = {}
        
        # 语义编码器（用于查找最近词）
        self.encoder = None
        self.vector_cache = {}
        self._encoder_available = False
        self._load_encoder()

    def _load_encoder(self):
        try:
            from sentence_transformers import SentenceTransformer
            print("⏳ 正在加载语义向量模型（用于词查找）...")
            self.encoder = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            self._encoder_available = True
            print("✅ 语义向量模型已加载")
        except ImportError:
            print("未安装 sentence-transformers，语义查找将使用轻量级回退")
            self._encoder_available = False
        except Exception as e:
            print(f"加载语义向量模型失败: {e}")
            self._encoder_available = False

    def _get_word_vector(self, word):
        if not self._encoder_available or self.encoder is None:
            return None
        if word not in self.vector_cache:
            try:
                self.vector_cache[word] = self.encoder.encode(word)
            except:
                return None
        return self.vector_cache[word]

    def _find_nearest_word(self, vec):
        if not self._encoder_available or self.encoder is None:
            return None
        cursor = self.memory.conn.cursor()
        cursor.execute("SELECT name FROM memories WHERE level IN ('permanent','long')")
        rows = cursor.fetchall()
        if not rows:
            return None
        words = [r[0] for r in rows]
        if not words:
            return None
        try:
            vecs = self.encoder.encode(words)
            sims = np.dot(vecs, vec) / (np.linalg.norm(vecs, axis=1) * np.linalg.norm(vec) + 1e-8)
            best_idx = np.argmax(sims)
            return words[best_idx] if sims[best_idx] > 0.4 else None
        except:
            return None

    def _semantic_random_walk(self, seed_word, steps=3, noise=0.15):
        if not self._encoder_available or self.encoder is None or not seed_word:
            return None
        current_vec = self._get_word_vector(seed_word)
        if current_vec is None:
            return None
        result_word = seed_word
        for _ in range(steps):
            noise_vec = np.random.normal(0, noise, current_vec.shape)
            current_vec = current_vec + noise_vec
            nearest = self._find_nearest_word(current_vec)
            if nearest:
                result_word = nearest
        return result_word

    # 向量版本的随机游走（直接接受向量）
    def _semantic_random_walk_vector(self, seed_vector, steps=3, noise=0.15):
        if seed_vector is None:
            return None
        current_vec = seed_vector.copy().astype(np.float32)
        for _ in range(steps):
            noise_vec = np.random.normal(0, noise, current_vec.shape).astype(np.float32)
            current_vec = current_vec + noise_vec
        return current_vec

    # 从向量生成念头
    def generate_raw_thought_from_vector(self, seed_vector, length=5):
        if seed_vector is None or not self._encoder_available:
            return self.generate_raw_thought(length)
        walked_vec = self._semantic_random_walk_vector(seed_vector)
        nearest = self._find_nearest_word(walked_vec)
        if nearest:
            if len(nearest) >= length:
                return nearest[:length]
            else:
                return nearest + "".join(chr(65 + (true_random_byte() % 26)) for _ in range(length - len(nearest)))
        return self.generate_raw_thought(length)

    # 原有基于词的游走（保留兼容）
    def _bag_of_words_walk(self, seed_word, steps=3):
        try:
            import jieba
        except ImportError:
            return None
        cursor = self.memory.conn.cursor()
        cursor.execute("SELECT name, feature FROM memories WHERE level IN ('permanent','long')")
        rows = cursor.fetchall()
        if not rows:
            return None
        all_words = []
        for name, feature in rows:
            all_words.extend(jieba.lcut(name + " " + feature))
        valid_words = [w for w in all_words if len(w.strip()) >= 1 and w not in {"的","了","在","是"}]
        if not valid_words:
            return None
        current = seed_word
        for _ in range(steps):
            candidates = [w for w in valid_words if w != current and len(w) >= 2]
            if not candidates:
                break
            current = random.choice(candidates)
        return current

    def generate_raw_thought(self, length=5, seed_word=None):
        # 优先语义游走（如果给了种子词）
        if seed_word and self._encoder_available and true_random_bool(0.6):
            result = self._semantic_random_walk(seed_word, steps=random.randint(1,3), noise=0.15)
            if result:
                if len(result) >= length:
                    return result[:length]
                else:
                    chinese_chars = ["思", "考", "念", "想", "记", "忆", "心", "情", "感", "觉"]; return result + "".join(random.choice(chinese_chars) for _ in range(length - len(result)))
        if seed_word and not self._encoder_available:
            result = self._bag_of_words_walk(seed_word, steps=random.randint(1,2))
            if result:
                if len(result) >= length:
                    return result[:length]
                else:
                    chinese_chars = ["思", "考", "念", "想", "记", "忆", "心", "情", "感", "觉"]; return result + "".join(random.choice(chinese_chars) for _ in range(length - len(result)))

        # 回退到碎片拼凑
        if true_random_bool(MOSAIC_PROB):
            mosaic = self._mosaic_generate(length)
            if mosaic:
                return mosaic
        if true_random_bool(self.word_insert_prob):
            fragment = self.memory.get_random_fragment(min_len=2, max_len=6)
            if fragment and len(fragment) >= 2:
                return fragment
        # 终极随机字母
        chars = []
        for _ in range(length):
            if true_random_bool(self.memory_influence_prob):
                fragment = self.memory.get_random_fragment(min_len=1, max_len=1)
                if fragment:
                    chars.append(fragment[0])
                    continue
            chinese_chars = ["思", "考", "念", "想", "记", "忆", "心", "情", "感", "觉"]
            chars.append(random.choice(chinese_chars))
        return "".join(chars)

    def _mosaic_generate(self, length):
        fragments = []
        for _ in range(3):
            frag = self.memory.get_random_fragment(min_len=1, max_len=3)
            if frag:
                fragments.append(frag)
        if not fragments:
            return None
        random.shuffle(fragments)
        mosaic = "".join(fragments)
        if len(mosaic) >= length:
            return mosaic[:length]
        else:
            padding = "".join(chr(65 + (true_random_byte() % 26)) for _ in range(length - len(mosaic)))
            return mosaic + padding

    # 联网搜索（略，与之前相同）
    def _web_search(self, keyword):
        today = datetime.date.today().isoformat()
        if keyword in self._search_cache:
            if self._search_cache[keyword] == today:
                print(f"今日已搜索过「{keyword}」，跳过")
                return []
        print(f"正在联网搜索: {keyword}")
        try:
            from ddgs import DDGS
            results = []
            with DDGS() as ddgs:
                search_results = list(ddgs.text(keyword, max_results=3))
                for r in search_results:
                    body = r.get("body", "")
                    if body:
                        results.append(f"{r.get('title','')}: {body}")
            if results:
                self._search_cache[keyword] = today
                print(f"搜索到 {len(results)} 条结果")
                return results
            else:
                print("搜索无结果")
                return []
        except ImportError:
            print("未安装 ddgs，请运行: pip install ddgs")
            return []
        except Exception as e:
            print(f"搜索失败: {e}")
            return []

    def _learn_and_answer(self, keyword, search_results, question=""):
        if not search_results:
            return {"summary": None, "answer": None}
        print("正在联网学习并解答...")
        search_text = "\n".join(search_results[:3])
        if question and question.strip():
            prompt = f"""我搜索了「{keyword}」，以下是搜索结果：
{search_text}

请完成两个任务：
1. 用一句话（不超过15个字）总结「{keyword}」的核心特征
2. 回答以下问题：{question}

请按以下格式回复：
总结：（你的总结）
答案：（你的答案）"""
        else:
            prompt = f"""我搜索了「{keyword}」，以下是搜索结果：
{search_text}

请用一句话（不超过15个字）总结「{keyword}」的核心特征。

请按以下格式回复：
总结：（你的总结）"""
        try:
            result_text = self.provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500
            )
            if not result_text:
                return {"summary": None, "answer": None}
            summary = ""
            answer = ""
            summary_match = re.search(r'总结[：:]\s*(.*)', result_text)
            answer_match = re.search(r'答案[：:]\s*(.*)', result_text)
            if summary_match:
                summary = summary_match.group(1).strip()
                print(f"📝 学习结果: {summary}")
            if answer_match:
                answer = answer_match.group(1).strip()
                print(f"💡 附带解答: {answer[:120]}...")
            if not summary and not answer:
                summary = result_text[:100]
            return {"summary": summary, "answer": answer}
        except Exception as e:
            print(f"学习解答失败: {e}")
            return {"summary": None, "answer": None}

    def think(self, keyword, visual_summary, hint=None, question="", skip_thoughts=False):
        found = self.memory.search(keyword)
        if found:
            memory_info = f'记得"{keyword}"：{found}'
            thinker_answer = None
        else:
            memory_info = f'不认识"{keyword}"，正在学习...'
            search_results = self._web_search(keyword)
            if search_results:
                result = self._learn_and_answer(keyword, search_results, question)
                summary = result.get("summary")
                thinker_answer = result.get("answer")
                if summary:
                    self.memory.add_short(name=keyword, feature=summary)
                    memory_info = f'学到新知识"{keyword}"：{summary}（来自网络搜索）'
                else:
                    self.memory.add_short(name=keyword, feature=visual_summary)
                    memory_info = f'不认识"{keyword}"，用场景描述暂存'
                    thinker_answer = None
            else:
                self.memory.add_short(name=keyword, feature=visual_summary)
                memory_info = f'不认识"{keyword}"，用场景描述暂存（联网无结果）'
                thinker_answer = None

        if skip_thoughts:
            return {
                "keyword": keyword,
                "memory_info": memory_info,
                "raw_sentences": [],
                "thinker_answer": thinker_answer,
            }

        num_sentences = true_random_int(1, 2)
        sentence_lengths = [true_random_int(3, 8) for _ in range(num_sentences)]
        raw_sentences = []
        for length in sentence_lengths:
            if hint and true_random_bool(HINT_USE_PROB):
                if len(hint) >= length:
                    raw_sentences.append(hint[:length])
                else:
                    padded = hint + "".join(chr(65 + (true_random_byte() % 26)) for _ in range(length - len(hint)))
                    raw_sentences.append(padded)
                continue
            thought = self.generate_raw_thought(length, seed_word=keyword)
            raw_sentences.append(thought)
        return {
            "keyword": keyword,
            "memory_info": memory_info,
            "raw_sentences": raw_sentences,
            "thinker_answer": thinker_answer,
        }