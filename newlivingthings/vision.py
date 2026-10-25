# vision.py
import base64
import os
import numpy as np
from config import API_KEY, USE_CLOUD_CLASSIFIER, USE_CLOUD_ENCODER, CLOUD_ENCODER_MODEL
from tokenizer import extract_keywords as local_extract_keywords, get_main_subject as local_get_main_subject

class VisualModel:
    def __init__(self, mode="simulate", description=None, image_path=None, classifier=None):
        self.mode = mode
        self.description = description or "一只橘猫趴在窗台上，阳光照在它身上"
        self.image_path = image_path
        self.classifier = classifier if USE_CLOUD_CLASSIFIER else None
        
        # 本地编码器（仅在非云端模式时加载）
        self.local_encoder = None
        if not USE_CLOUD_ENCODER:
            try:
                from sentence_transformers import SentenceTransformer
                print("⏳ 正在加载本地编码器（首次约需下载 500MB，请耐心等待）...")
                self.local_encoder = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
                print("✅ 本地编码器已加载（可使用 GPU 加速）")
            except ImportError:
                print("未安装 sentence-transformers，本地编码不可用，请运行: pip install sentence-transformers")
            except Exception as e:
                print(f"本地编码器加载失败: {e}")

        # 云端模式需要 model_provider
        if USE_CLOUD_ENCODER:
            from model_provider import get_provider
            self.provider = get_provider()
            print("云端编码模式已启用")

        # 真实视觉模式
        if self.mode == "real":
            if not API_KEY or API_KEY == "你的API-Key":
                raise ValueError("真实模式需要有效的 API_KEY")
            from model_provider import get_provider
            self.provider = get_provider()
            print("✅ 多模态视觉模型已连接（真实模式）")

    def see(self):
        if self.mode == "simulate":
            return self.description
        elif self.mode == "real":
            return self._real_see()
        elif self.mode == "keyboard":
            return self._keyboard_see()
        else:
            raise ValueError(f"未知视觉模式: {self.mode}")

    def _real_see(self):
        if not self.image_path or not os.path.exists(self.image_path):
            raise FileNotFoundError(f"图片不存在: {self.image_path}")
        with open(self.image_path, "rb") as img_file:
            img_base64 = base64.b64encode(img_file.read()).decode('utf-8')
        print(f"🖼️ 正在观察图片: {self.image_path} ...")
        try:
            response = self.provider.client.chat.completions.create(
                model="glm-4v",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "请简单描述这张图片里的主要物体或场景，只返回一句话，不超过15个字。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                ]}],
                temperature=0.3, max_tokens=50
            )
            desc = response.choices[0].message.content
            return desc.strip() if desc else self.description
        except Exception as e:
            print(f"视觉识别失败: {e}")
            return self.description

    def _keyboard_see(self):
        text = input("请输入场景描述：").strip()
        if not text:
            text = self.description
            print(f"使用默认场景: {text}")
        return text

    # ---------- 双模编码方法 ----------
    def encode(self, text):
        """将文本编码成语义向量（根据配置选择云端或本地）"""
        if USE_CLOUD_ENCODER:
            return self._cloud_encode(text)
        else:
            return self._local_encode(text)

    def _local_encode(self, text):
        """本地 GPU/CPU 编码"""
        if self.local_encoder is None:
            raise RuntimeError("本地编码器未加载，请安装 sentence-transformers")
        return self.local_encoder.encode(text)

    def _cloud_encode(self, text):
        """云端大模型编码（将文本转成 JSON 数组表示的向量）"""
        try:
            prompt = f"""请将以下场景描述编码成一个 384 维的语义向量（用 JSON 数组表示），每个元素是浮点数：
场景：{text}
只返回 JSON 数组，不要其他任何内容。"""
            result = self.provider.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=600
            )
            if result:
                import json, re
                # 提取 JSON 数组
                match = re.search(r'\[.*?\]', result, re.DOTALL)
                if match:
                    vec = json.loads(match.group())
                    if len(vec) == 384:
                        return np.array(vec, dtype=np.float32)
                    else:
                        print(f"云端返回的向量维度不是384，而是{len(vec)}，降级到本地")
                else:
                    print("云端返回未包含有效JSON数组，降级到本地")
        except Exception as e:
            print(f"云端编码失败: {e}，降级到本地")

        # 降级到本地
        return self._local_encode(text)

    # ---------- 原有分词方法（兼容旧接口） ----------
    def extract_keywords(self, description):
        if self.classifier and USE_CLOUD_CLASSIFIER:
            try:
                keywords = self.classifier.extract_keywords(description, max_keywords=5)
                if keywords:
                    return keywords
            except Exception as e:
                print(f"云端分类失败，使用本地分词: {e}")
        return local_extract_keywords(description, max_keywords=5)

    def get_main_subject(self, description):
        if self.classifier and USE_CLOUD_CLASSIFIER:
            try:
                return self.classifier.get_main_subject(description)
            except:
                pass
        return local_get_main_subject(description)