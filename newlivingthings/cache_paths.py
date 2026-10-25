# cache_paths.py
# -*- coding: utf-8 -*-
"""
cache_paths.py —— 统一的缓存路径解析（任务一：环境固化与防呆）

目标：
  * 尊重用户已设置的环境变量：HF_HOME / HF_HUB_CACHE / TRANSFORMERS_CACHE /
    SENTENCE_TRANSFORMERS_HOME / TORCH_HOME / AC_MODEL_CACHE / AC_FINETUNE_DIR
  * 如果这些目录不可写，绝不崩溃、绝不抛权限错误，而是自动降级到可写目录
  * 把"目录不可写"的事实记录到日志，方便排查

优先级（从高到低）：
  1. 显式环境变量（如 HF_HOME=D:\hf_cache）
  2. 用户主目录下的标准位置
  3. 项目内 .model_cache / run_evolve
所有候选目录都会先做"真实写入探测"，只有能写入的才会被采用。
"""

import os
import tempfile

_PROBE = ".ac_write_probe"


def _env(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return os.path.expanduser(os.path.expandvars(v))
    return None


def is_writable(path):
    """真实写入探测：能创建并删除一个临时文件才算可写."""
    if not path:
        return False
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, _PROBE + str(os.getpid()))
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def first_writable(candidates, label=""):
    """返回第一个可写的候选目录；全部不可写时退回系统临时目录."""
    seen = set()
    for c in candidates:
        if not c:
            continue
        try:
            c = os.path.abspath(os.path.expanduser(str(c)))
        except Exception:
            continue
        if c in seen:
            continue
        seen.add(c)
        if is_writable(c):
            return c
        _warn_once(label, c)
    fallback = os.path.join(tempfile.gettempdir(), "ac_os_cache")
    try:
        os.makedirs(fallback, exist_ok=True)
        return fallback
    except Exception:
        return tempfile.gettempdir()


_WARNED = set()


def _warn_once(label, path):
    key = (label, path)
    if key in _WARNED:
        return
    _WARNED.add(key)
    try:
        print("[缓存] %s 不可写，已自动跳过: %s" % (label or "目录", path), flush=True)
    except Exception:
        pass


def project_root():
    return os.path.dirname(os.path.abspath(__file__))


def resolve_hf_home():
    """HuggingFace 主缓存目录."""
    cands = [
        _env("HF_HOME"),
        os.path.join(os.path.expanduser("~"), ".cache", "huggingface"),
        os.path.join(project_root(), ".model_cache", "huggingface"),
    ]
    return first_writable(cands, "HF_HOME")


def resolve_hf_hub_cache():
    """模型权重缓存（HF_HUB_CACHE 优先，否则 $HF_HOME/hub）."""
    explicit = _env("HF_HUB_CACHE")
    cands = [explicit]
    if not explicit:
        cands.append(os.path.join(resolve_hf_home(), "hub"))
    cands.append(os.path.join(project_root(), ".model_cache", "hub"))
    return first_writable(cands, "HF_HUB_CACHE")


def resolve_sentence_transformers_home():
    cands = [
        _env("SENTENCE_TRANSFORMERS_HOME", "AC_MODEL_CACHE"),
        os.path.join(resolve_hf_home(), "sentence_transformers"),
        os.path.join(project_root(), ".model_cache", "sentence_transformers"),
    ]
    return first_writable(cands, "SENTENCE_TRANSFORMERS_HOME")


def resolve_torch_home():
    cands = [
        _env("TORCH_HOME"),
        os.path.join(resolve_hf_home(), "torch"),
        os.path.join(project_root(), ".model_cache", "torch"),
    ]
    return first_writable(cands, "TORCH_HOME")


def resolve_finetune_dir():
    """微调产物目录（LoRA / 合并权重 / GGUF）."""
    cands = [
        _env("AC_FINETUNE_DIR"),
        os.path.join(project_root(), "run_evolve"),
    ]
    return first_writable(cands, "微调产物目录")


def apply_hf_env():
    """把解析结果写回环境变量，确保 transformers / datasets / huggingface_hub 都遵守."""
    hf_home = resolve_hf_home()
    os.environ["HF_HOME"] = hf_home
    os.environ["HF_HUB_CACHE"] = resolve_hf_hub_cache()
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = resolve_sentence_transformers_home()
    os.environ["TORCH_HOME"] = resolve_torch_home()
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    return {"HF_HOME": os.environ["HF_HOME"],
            "HF_HUB_CACHE": os.environ["HF_HUB_CACHE"],
            "SENTENCE_TRANSFORMERS_HOME": os.environ["SENTENCE_TRANSFORMERS_HOME"]}


def describe():
    """自检：返回所有关键目录及其可写状态，不修改任何环境变量."""
    def d(env_name, path, writable):
        return {"env": env_name, "value": path, "writable": writable, "exists": os.path.isdir(path)}

    wanted = [
        ("HF_HOME", _env("HF_HOME")),
        ("HF_HUB_CACHE", _env("HF_HUB_CACHE")),
        ("SENTENCE_TRANSFORMERS_HOME", _env("SENTENCE_TRANSFORMERS_HOME")),
        ("AC_FINETUNE_DIR", _env("AC_FINETUNE_DIR")),
    ]
    rows = []
    for name, val in wanted:
        if val:
            rows.append(d(name, val, is_writable(val)))
        else:
            rows.append(d(name, "(未设置，使用默认)", None))
    rows.append(d("resolved HF_HOME", resolve_hf_home(), True))
    rows.append(d("resolved HF_HUB_CACHE", resolve_hf_hub_cache(), True))
    rows.append(d("resolved 微调目录", resolve_finetune_dir(), True))
    return rows


if __name__ == "__main__":
    print("=== 缓存路径自检 ===")
    for row in describe():
        state = "可写" if row["writable"] else ("不可写" if row["writable"] is False else "-")
        print("  %-28s %-14s %s" % (row["env"], state, row["value"]))
    print("")
    print("apply_hf_env() 结果:")
    for k, v in apply_hf_env().items():
        print("  %s = %s" % (k, v))
