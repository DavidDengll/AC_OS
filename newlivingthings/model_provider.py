# model_provider.py
"""
通用大模型调用接口，支持所有 OpenAI 兼容 API 的服务。
切换模型只需修改 config.py 中的配置。
"""

from openai import OpenAI
from config import MODEL_NAME, API_BASE_URL, API_KEY, API_EXTRA_HEADERS, validate_config


class ModelProvider:
    """统一的模型调用客户端"""

    def __init__(self):
        # 【新增】启动时立刻校验 Key
        validate_config()

        kwargs = {"api_key": API_KEY}

        if API_BASE_URL:
            kwargs["base_url"] = API_BASE_URL
            kwargs["base_url"] = API_BASE_URL
        if API_EXTRA_HEADERS:
            kwargs["default_headers"] = API_EXTRA_HEADERS
            kwargs["default_headers"] = API_EXTRA_HEADERS

        self.client = OpenAI(**kwargs)
        self.model = MODEL_NAME

    def chat(self, messages, temperature=0.7, max_tokens=500):
        """
        调用大模型进行对话。
        参数:
            messages: [{"role": "user", "content": "..."}, ...]
            temperature: 温度
            max_tokens: 最大输出 token 数
        返回:
            str: 模型回复的内容，失败时返回空字符串
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            content = response.choices[0].message.content
            return content.strip() if content else ""
        except Exception as e:
            print(f"模型调用失败: {e}")
            return ""


# 全局单例，避免重复创建客户端
_provider_instance = None

def get_provider():
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = ModelProvider()
    return _provider_instance