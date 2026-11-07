# finetune_search_adapter.py
# -*- coding: utf-8 -*-
"""
finetune_search_adapter.py —— 微调配置的联网搜索与双重断言模块（独立模块）

职责：
  1. 本地注册表里没有该模型 -> 通过 ZeptoClaw 发起 web_search
  2. 让大模型从网页结果里提取可能的 LoRA target_modules（字符串兜底）
  3. 双重断言（只读 config，绝不加载权重）：
       断言一 · 存在性：模块名必须能在架构信息里找到
       断言二 · 占比度：按 num_hidden_layers / hidden_size 纯数学估算参数量占比，
                        低于 0.1% 视为挂错位置
  4. 任何一步失败 -> 返回 None 并提示使用本地默认配置

【红线】
  - 严禁任何会加载模型权重的 transformers 高层接口（只读 config.json / HfApi 元数据）
  - 严禁用复杂正则硬抠网页
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# ---- 可通过环境变量调整的阈值 ----
MIN_MODULE_RATIO = float(os.environ.get("FT_MIN_MODULE_RATIO", "0.001"))  # 0.1%
SEARCH_TIMEOUT = int(os.environ.get("FT_SEARCH_TIMEOUT", "120"))
LLM_MAX_TOKENS = int(os.environ.get("FT_LLM_MAX_TOKENS", "200"))

TAG = "[微调适配]"

# 常见且明确支持 LoRA 的目标模块；命中即视为"本地注册表有配置"
LOCAL_REGISTRY = {
    "qwen3.5": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "qwen2.5": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "llama": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "mistral": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "gemma": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "granite": ["q_proj", "k_proj", "v_proj", "o_proj"],
}

# 常见的注意力 / MLP 线性层名，供"简单字符串查找"兜底使用
_COMMON_MODULES = (
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
    "query_key_value", "dense", "fc1", "fc2",
    "Wqkv", "Wo", "w1", "w2", "w3",
)

_ARCH_LAYER_NAMES = (
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
    "query_key_value", "dense", "fc1", "fc2",
    "Wqkv", "Wo", "w1", "w2", "w3",
)


def _log(msg):
    try:
        print("%s %s" % (TAG, msg), flush=True)
    except Exception:
        pass


def _dedupe(seq):
    out, seen = [], set()
    for x in seq or []:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


# ============================================================
# 一、搜索触发与执行
# ============================================================
def registry_lookup(model_name):
    """本地注册表查询：按模型名做包含匹配。返回模块列表或 None。"""
    try:
        key = str(model_name or "").strip().lower()
        if not key:
            return None
        for name, modules in LOCAL_REGISTRY.items():
            if name in key:
                return list(modules)
        return None
    except Exception:
        return None


# 搜索工具的网络/权限失败时，常以"成功"的形式返回一段致歉文本。
# 这类文本绝不能当成网页内容去提取模块。
_SEARCH_FAILURE_MARKERS = (
    "network error", "can't use", "cannot use", "could not", "couldn't",
    "i'm unable", "i am unable", "unable to", "not able to",
    "api key", "unauthorized", "forbidden", "rate limit", "quota",
    "no results", "didn't find", "did not find", "sorry",
    "抱歉", "无法访问", "搜索失败", "无权访问", "网络错误",
)


def looks_like_search_failure(text):
    """判断搜索结果是否是"搜索工具失败"的致歉文本，而非真实网页内容。"""
    try:
        t = str(text or "").strip()
        if not t:
            return True
        low = t.lower()
        # 致歉式短文本：命中失败标记且没有出现任何模块名特征
        has_marker = any(mk in low for mk in _SEARCH_FAILURE_MARKERS)
        has_module_hint = ("target_modules" in low or "_proj" in low
                           or "lora" in low and "config" in low)
        if has_marker and not has_module_hint:
            return True
        # 极短且无模块特征，也视为无效
        if len(t) < 40 and not has_module_hint:
            return True
        return False
    except Exception:
        return True


def build_search_query(model_name):
    return "HuggingFace %s LoRA target_modules fine-tuning configuration" % model_name


def search_web(model_name, bridge=None):
    """通过 ZeptoClaw 发起 web_search。返回文本结果，失败返回空串。"""
    try:
        if bridge is None:
            import tool_caller
            bridge = tool_caller.call_bridge
        task = "请在网络上搜索：%s ，把包含 target_modules 配置的页面正文摘录出来" % (
            build_search_query(model_name))
        _log("本地无该模型配置，发起联网搜索：%s" % build_search_query(model_name))
        res = bridge(task, timeout=SEARCH_TIMEOUT) or {}
        if isinstance(res, dict):
            if not res.get("ok"):
                _log("搜索失败：%s" % str(res.get("error"))[:160])
                return ""
            out = str(res.get("result") or "")
        else:
            out = str(res or "")
        if looks_like_search_failure(out):
            _log("搜索结果无效（疑似搜索工具失败）：%s" % out.strip()[:120].replace(chr(10), " "))
            return ""
        return out
    except Exception as e:
        _log("搜索异常：%s" % e)
        return ""


# ============================================================
# 二、稳健提取（大模型优先，简单字符串查找兜底）
# ============================================================
_EXTRACT_PROMPT = (
    "下面是一段关于 HuggingFace 模型 %s 的 LoRA 微调网页摘录。\n"
    "请只提取其中提到的 target_modules（要挂载 LoRA 的模块名），\n"
    "用逗号分隔输出，例如：q_proj,k_proj,v_proj,o_proj\n"
    "如果摘录里没有相关信息，只输出：NONE\n\n"
    "=== 网页摘录开始 ===\n%s\n=== 网页摘录结束 ==="
)


def _clean_module_token(tok):
    """把单个候选模块名清洗成合法标识符；不合法返回 None。"""
    try:
        t = str(tok).strip().strip(chr(34) + chr(39) + "[](){},;:" + chr(96))
        t = t.strip()
        if not t or len(t) > 64:
            return None
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", t):
            return None
        return t
    except Exception:
        return None


def extract_modules_from_text(text):
    """简单字符串查找兜底：在文本里找常见模块名。

    必须按"词边界"匹配：早期版本用裸子串，导致英文句子里的 "Would"
    命中了模块名 "Wo"，把一个道歉句当成了微调配置。
    """
    try:
        blob = str(text or "")
        hits = []
        for m in _COMMON_MODULES:
            # 前后必须是分隔符或首尾，才算独立的模块名
            pat = r"(?<![A-Za-z0-9_])" + re.escape(m) + r"(?![A-Za-z0-9_])"
            if re.search(pat, blob):
                hits.append(m)
        return _dedupe(hits)
    except Exception:
        return []


def extract_modules(text, model_name="", llm=None):
    """优先让大模型提取；解析失败再用字符串查找。无法提取返回 None。"""
    try:
        html = str(text or "")
        if not html.strip():
            return None
        # ---- 1) 大模型提取 ----
        if llm is not None:
            try:
                prompt = _EXTRACT_PROMPT % (model_name, html[:4000])
                reply = llm.chat([{"role": "user", "content": prompt}],
                                 temperature=0.0, max_tokens=LLM_MAX_TOKENS) or ""
                reply = str(reply).strip()
                if reply and not reply.upper().startswith("NONE"):
                    cand = _dedupe([_clean_module_token(tok)
                                    for tok in re.split(r"[,，\s]+", reply)])
                    if cand:
                        _log("大模型提取到模块：%s" % ",".join(cand))
                        return cand
            except Exception as e:
                _log("大模型提取失败，改用字符串查找：%s" % e)
        # ---- 2) 字符串查找兜底 ----
        hits = extract_modules_from_text(html)
        if hits:
            _log("字符串查找得到模块：%s" % ",".join(hits))
            return hits
        return None
    except Exception:
        return None


# ============================================================
# 三、架构信息（只读 config，绝不加载权重）
# ============================================================
def _normalize_to_hf_id(model_name):
    """把 granite4:tiny-h 这类 ollama 名尽量映射成 HF 仓库 id。"""
    try:
        m = str(model_name or "").strip()
        if not m:
            return None
        if "/" in m:
            return m
        base = m.split(":")[0].strip().lower()
        mapping = {
            "granite4": "ibm-granite/granite-4.0-tiny-preview",
            "granite": "ibm-granite/granite-3.1-2b-instruct",
            "qwen3.5": "Qwen/Qwen3.5-0.8B-Base",
            "qwen2.5": "Qwen/Qwen2.5-0.5B",
            "llama": "meta-llama/Llama-3.2-1B",
            "mistral": "mistralai/Mistral-7B-v0.1",
            "gemma": "google/gemma-2-2b",
        }
        for k, v in mapping.items():
            if base.startswith(k):
                return v
        return None
    except Exception:
        return None


def _find_local_config_json(model_name):
    """在本地常见位置寻找该模型的 config.json（只读文件，不加载权重）。"""
    try:
        cands = []
        env_dir = os.environ.get("FT_MODEL_CONFIG_DIR")
        if env_dir:
            cands.append(env_dir)
        cands += [
            os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub"),
            os.path.join(HERE, ".model_cache", "huggingface", "hub"),
        ]
        slug = str(model_name or "").replace("/", "--").lower()
        for base in cands:
            if not os.path.isdir(base):
                continue
            for name in os.listdir(base):
                if slug and slug in name.lower():
                    for root, _dirs, files in os.walk(os.path.join(base, name)):
                        if "config.json" in files:
                            return os.path.join(root, "config.json")
        return None
    except Exception:
        return None


def load_arch_info(model_name):
    """只读获取架构信息。优先本地 config.json，否则用 HfApi 轻量下载 config。"""
    try:
        local = _find_local_config_json(model_name)
        if local:
            with open(local, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict) and cfg:
                _log("已读取本地 config.json：%s" % local)
                return {"source": "local_config.json", "config": cfg}

        hf_id = _normalize_to_hf_id(model_name)
        if not hf_id:
            _log("无法把 %s 映射为 HuggingFace 仓库 id" % model_name)
            return None
        try:
            from huggingface_hub import hf_hub_download, HfApi
        except Exception as e:
            _log("huggingface_hub 不可用：%s" % e)
            return None
        _log("通过 HfApi 获取轻量架构信息：%s" % hf_id)
        # 只下载 config.json（几 KB），绝不触碰权重文件
        path = hf_hub_download(repo_id=hf_id, filename="config.json")
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return {"source": "hf_hub_config.json", "config": cfg, "hf_id": hf_id}
    except Exception as e:
        _log("架构信息获取失败：%s" % e)
        return None


def _arch_module_names(cfg):
    """从 config 推导出架构里确实存在的线性层名集合（纯配置推导）。"""
    names = set()
    if not isinstance(cfg, dict):
        return names
    for key in ("target_modules", "modules_to_save", "lora_target_modules"):
        v = cfg.get(key)
        if isinstance(v, list):
            names.update(str(x) for x in v)
    archs = []
    for key in ("architectures", "model_type", "model_name"):
        v = cfg.get(key)
        if isinstance(v, str):
            archs.append(v.lower())
        elif isinstance(v, list):
            archs.extend(str(x).lower() for x in v)
    blob = " ".join(archs)
    if any(k in blob for k in ("qwen", "llama", "mistral", "granite", "gemma", "phi")):
        names.update(["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj"])
    if any(k in blob for k in ("bert", "roberta", "deberta", "electra")):
        names.update(["query", "key", "value", "dense"])
    if "chatglm" in blob:
        names.update(["query_key_value", "dense", "fc1", "fc2"])
    if "bloom" in blob:
        names.update(["query_key_value", "dense_h_to_4h", "dense_4h_to_h"])
    if not names:
        names.update(_ARCH_LAYER_NAMES)
    return names


def _to_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


def estimate_module_params(modules, cfg):
    """纯数学估算：这些模块的参数量与占全模型百分比。返回 (params, ratio, base)。"""
    try:
        cfg = cfg or {}
        hidden = _to_int(cfg.get("hidden_size") or cfg.get("n_embd")
                         or cfg.get("d_model") or cfg.get("model_dim"))
        layers = _to_int(cfg.get("num_hidden_layers") or cfg.get("n_layer")
                         or cfg.get("num_layers"))
        inter = _to_int(cfg.get("intermediate_size") or cfg.get("n_inner")
                        or cfg.get("ffn_dim"))
        heads = _to_int(cfg.get("num_attention_heads") or cfg.get("n_head"))
        kv = _to_int(cfg.get("num_key_value_heads")) or heads
        vocab = _to_int(cfg.get("vocab_size"))
        if hidden <= 0 or layers <= 0:
            return 0, 0.0, 0
        if inter <= 0:
            inter = hidden * 4
        if heads <= 0:
            heads = 1
        if kv <= 0:
            kv = heads
        head_dim = max(1, hidden // heads)
        kv_dim = head_dim * kv
        per_layer = {
            "q_proj": hidden * hidden,
            "k_proj": hidden * kv_dim,
            "v_proj": hidden * kv_dim,
            "o_proj": hidden * hidden,
            "gate_proj": hidden * inter,
            "up_proj": hidden * inter,
            "down_proj": inter * hidden,
            "query_key_value": hidden * (hidden + 2 * kv_dim),
            "dense": hidden * hidden,
            "fc1": hidden * inter,
            "fc2": inter * hidden,
        }
        base = vocab * hidden * 2 if vocab else hidden * hidden * 2
        base += layers * (4 * hidden * hidden + 2 * hidden * inter)
        if not vocab:
            base += hidden * hidden
        total = 0
        for m in modules or []:
            total += per_layer.get(str(m), 0) * layers
        if total <= 0 or base <= 0:
            return total, 0.0, base
        return total, float(total) / float(base), base
    except Exception:
        return 0, 0.0, 0


def assert_modules_exist(modules, arch_names):
    """断言一 · 存在性。返回 (ok, 缺失列表)。"""
    try:
        if not modules:
            return False, []
        missing = [m for m in modules if str(m) not in arch_names]
        return (len(missing) == 0), missing
    except Exception:
        return False, list(modules or [])


def assert_module_ratio(modules, cfg, min_ratio=None):
    """断言二 · 占比度。返回 (ok, ratio, params)。"""
    try:
        threshold = MIN_MODULE_RATIO if min_ratio is None else float(min_ratio)
        params, ratio, _base = estimate_module_params(modules, cfg)
        return (ratio >= threshold), ratio, params
    except Exception:
        return False, 0.0, 0


# ============================================================
# 四、主入口
# ============================================================
def _fail():
    _log("搜索或验证失败，请使用本地默认配置。")
    return None


def search_finetune_config(model_name, llm=None, bridge=None):
    """微调配置联网搜索与双重断言。成功返回模块列表，任何一步失败返回 None。"""
    try:
        local = registry_lookup(model_name)
        if local:
            _log("本地注册表命中 %s -> %s" % (model_name, ",".join(local)))
            return local

        text = search_web(model_name, bridge=bridge)
        if not str(text or "").strip():
            return _fail()

        modules = extract_modules(text, model_name=model_name, llm=llm)
        if not modules:
            _log("未能从搜索结果中提取到 target_modules")
            return _fail()

        arch = load_arch_info(model_name)
        if not arch or not arch.get("config"):
            _log("无法获取架构信息（只读 config 失败）")
            return _fail()
        cfg = arch["config"]
        arch_names = _arch_module_names(cfg)

        ok1, missing = assert_modules_exist(modules, arch_names)
        if not ok1:
            _log("断言一失败：以下模块在架构中不存在 %s" % ",".join(missing))
            return _fail()

        ok2, ratio, params = assert_module_ratio(modules, cfg)
        _log("断言二：估算参数量 %d，占比 %.6f%%" % (params, ratio * 100))
        if not ok2:
            _log("占比过低，可能挂错位置。")
            return _fail()

        _log("双重断言通过 -> %s" % ",".join(modules))
        return _dedupe(modules)
    except Exception as e:
        _log("未预期异常：%s" % e)
        return _fail()
