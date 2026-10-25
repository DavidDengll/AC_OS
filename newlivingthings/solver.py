# solver.py
from model_provider import get_provider
import json
import re
import jieba

class Solver:
    def __init__(self, memory_system=None):
        self.provider = get_provider()
        self.memory_system = memory_system

    def solve(self, question, scene_description="", hint=None):
        # 清理 hint（如果为空或太短，则丢弃）
        if hint and isinstance(hint, str):
            hint = hint.strip()
            if len(hint) < 2:
                hint = None
        else:
            hint = None

        print(f"🤔 解答者正在思考: {question}")
        if hint:
            print(f"💡 带着 hint 推理: {hint}")

        related_memories = self._retrieve_related_memories(question, scene_description)

        if len(related_memories) < 2:
            print("📡 记忆不足，尝试联网搜索...")
            web_knowledge = self._web_search_if_needed(question)
            if web_knowledge:
                related_memories.append({"name": "网络知识", "feature": " ".join(web_knowledge[:2])})

        answer = self._generate_with_analogies(question, related_memories, scene_description, hint)
        if not answer.get("answer") or not answer["answer"].strip():
            answer["answer"] = "抱歉，我暂时无法解答这个问题。"
            answer["analogies"] = answer.get("analogies", [])
            answer["confidence"] = "低"
        return answer

    def _retrieve_related_memories(self, question, scene_description=""):
        if not self.memory_system:
            return []
        cursor = self.memory_system.conn.cursor()
        cursor.execute("SELECT name, feature, level FROM memories LIMIT 50")
        rows = cursor.fetchall()
        if not rows:
            return []
        q_words = set(jieba.lcut(f"{question} {scene_description}"))
        skip_words = {"的", "了", "在", "是", "有", "它", "这", "那", "什么", "怎么", "为什么", "吗", "呢", "吧", "啊"}
        q_words = {w for w in q_words if w not in skip_words and len(w.strip()) >= 1}
        candidates = []
        for r in rows:
            name, feature = r[0], r[1]
            mem_words = set(jieba.lcut(f"{name} {feature}"))
            overlap = q_words & mem_words
            if overlap:
                candidates.append({"name": name, "feature": feature, "level": r[2], "score": len(overlap)})
        candidates.sort(key=lambda x: x["score"], reverse=True)
        related = [{"name": c["name"], "feature": c["feature"], "level": c["level"]} for c in candidates[:5]]
        print(f"🧠 快速检索: 找到 {len(related)} 个相关概念")
        return related

    def _web_search_if_needed(self, question):
        try:
            from ddgs import DDGS
            print(f"🌐 正在联网搜索: {question}")
            results = []
            with DDGS(headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }) as ddgs:
                search_results = list(ddgs.text(question, max_results=3))
                for r in search_results:
                    body = r.get("body", "")
                    if body:
                        results.append(body)
            return results
        except ImportError:
            print("未安装 ddgs，跳过联网搜索")
            return []
        except Exception as e:
            print(f"联网搜索失败: {e}")
            return []

    def _generate_with_analogies(self, question, related_memories, scene_description="", hint=None):
        memory_text = ""
        if related_memories:
            lines = []
            for m in related_memories[:5]:
                feature_short = m['feature'][:50]
                lines.append(f"- {m['name']}：{feature_short}")
            memory_text = "相关知识：\n" + "\n".join(lines)

        scene_text = f"当前场景：{scene_description}\n" if scene_description else ""
        hint_text = f"\n【内部念头提示】{hint}\n" if hint else ""

        prompt_body = f"""{scene_text}{memory_text}{hint_text}
问题：{question}"""

        estimated_prompt_tokens = len(prompt_body) // 2
        dynamic_max_tokens = min(800, max(300, estimated_prompt_tokens + 400))

        prompt = f"""你是一个善于通过类比来解答问题的思考者。

{prompt_body}

请按以下步骤思考并回答：
1. 从已知概念中找出与问题最相似的2~3个概念，说明相似点
2. 基于这些相似点进行类比推理
3. 给出最终答案

请严格按以下JSON格式返回（不要其他内容）：
{{"analogies":[{{"source":"概念名","similarity":"相似点","insight":"启发"}}],"answer":"完整解答（含推理过程）","confidence":"高/中/低"}}"""

        try:
            result_text = self.provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=dynamic_max_tokens
            )
            if not result_text:
                return {"answer": "抱歉，我暂时无法解答这个问题。", "analogies": [], "confidence": "低"}

            result_text = self._clean_json_text(result_text)
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                analogies = result.get("analogies", [])
                answer_text = result.get("answer", "")
                if len(analogies) >= 2:
                    confidence = "高"
                elif len(analogies) == 1:
                    confidence = "中"
                else:
                    confidence = "低"
                if not answer_text or not answer_text.strip():
                    answer_text = "抱歉，我暂时无法解答这个问题。"
                    confidence = "低"
                print(f"🔗 构建了 {len(analogies)} 条类比链 | 置信度: {confidence}")
                return {"answer": answer_text, "analogies": analogies, "confidence": confidence}

            print(f"JSON 解析失败，使用原始文本")
            return {"answer": result_text, "analogies": [], "confidence": "低"}
        except Exception as e:
            print(f"❌ 生成失败: {e}")
            return {"answer": "抱歉，我暂时无法解答这个问题。", "analogies": [], "confidence": "低"}

    def _clean_json_text(self, text):
        if not text:
            return ""
        text = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
        text = re.sub(r'\n?```$', '', text)
        return text.strip()

    def should_solve(self, text):
        if not text or not text.strip():
            return False
        question_keywords = {"为什么", "怎么", "如何", "什么是", "是什么", "会不会", "能不能", "怎么回事", "怎么样", "?", "？", "吗", "呢"}
        if any(kw in text for kw in question_keywords):
            return True
        request_patterns = {"帮我", "教我", "告诉我", "解释一下", "说一下", "讲讲", "能不能", "可以吗", "行不行", "好吗", "好不好"}
        if any(pattern in text for pattern in request_patterns):
            return True
        statement_patterns = {"我看到", "输入场景", "一只", "今天天气", "你好", "再见"}
        if any(pattern in text for pattern in statement_patterns):
            return False
        return False