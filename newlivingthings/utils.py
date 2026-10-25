# utils.py
import re
import json

def clean_and_parse_json(raw_text):
    """
    从 LLM 返回的乱七八糟文本里，干净地提取 JSON。
    支持去掉 ```json ... ``` 标记，也支持直接用 json.loads 解析。
    返回解析后的 Python 对象（dict 或 list），失败则返回 None。
    """
    if not raw_text or not raw_text.strip():
        return None

    # 1. 去掉常见的 Markdown 代码块
    text = raw_text.strip()
    # 去掉 ```json 或 ``` 开头
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    # 去掉 ``` 结尾
    text = re.sub(r'\n?```$', '', text)
    text = text.strip()

    # 2. 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. 如果直接解析失败，用正则尝试捞取第一个完整的 {...} 或 [...]
    # 优先找数组（因为 Review 返回数组更合适）
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if not match:
        match = re.search(r'\{.*\}', text, re.DOTALL)
    
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None
    return None