# model_provider.py
"""
通用大模型调用接口，支持所有 OpenAI 兼容 API 的服务。
切换模型只需修改 config.py 中的配置。
"""

import json
import os
import re
import urllib.request

from openai import OpenAI
from config import MODEL_NAME, API_BASE_URL, API_KEY, API_EXTRA_HEADERS, validate_config


def _native_root(base_url):
    """从 OpenAI 兼容地址推导出 Ollama 原生 API 根地址。

    http://host:11434/v1  ->  http://host:11434
    """
    if not base_url:
        return None
    return re.sub(r"/v1/?$", "", base_url.rstrip("/"))


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
        self.base_url = API_BASE_URL
        self.native_root = _native_root(API_BASE_URL)
        # 思考型模型（qwen3.5 等）会把 token 全耗在 thinking 上，
        # OpenAI 兼容层拿不到内容 -> 自动切换原生 API + think=false
        self.thinking_unsupported = False

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
        content = self._chat_openai(messages, temperature, max_tokens)
        if content:
            return content
        # 兜底：OpenAI 兼容层返回空（常见于思考型模型把 token 全用在推理上）
        native = self._chat_native(messages, temperature, max_tokens)
        if native:
            if not self.thinking_unsupported:
                self.thinking_unsupported = True
                print("[模型] 兼容层返回空内容，已切换为 Ollama 原生 API（think=off）")
            return native
        return ""

    def _chat_openai(self, messages, temperature, max_tokens):
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

    def _chat_native(self, messages, temperature, max_tokens):
        """直接调用 Ollama /api/chat，并显式关闭思考模式。"""
        if not self.native_root:
            return ""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_predict": max(max_tokens, 256)},
        }
        try:
            req = urllib.request.Request(
                self.native_root + "/api/chat",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read().decode("utf-8"))
            msg = data.get("message", {}) or {}
            text = (msg.get("content") or "").strip()
            return text
        except Exception as e:
            print(f"原生 API 调用失败: {e}")
            return ""


# 全局单例，避免重复创建客户端
_provider_instance = None

def get_provider():
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = ModelProvider()
    return _provider_instance