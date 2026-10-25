# export_evolved_model.py
# -*- coding: utf-8 -*-
"""
export_evolved_model.py —— 把熵灵"进化出来的大脑"打包成可分享的资料

背景
----
微调产物 (LoRA 适配器 / 合并后的完整权重) 动辄几十 MB 到数 GB,
绝对不能 push 进主仓库. 正确做法:

    主仓库  ->  只放代码 + 本脚本 + 下载说明
    网盘    ->  放合并后的模型包 (手动上传, 手动下载)

本脚本做的事:
  1. 定位 LoRA 适配器 (默认 newlivingthings/run_evolve/latest_adapter)
  2. 可选: 合并进基础模型, 导出完整权重
  3. 可选: 转换为 GGUF (供 Ollama 直接使用)
  4. 打赢包 zip + 生成 SHA256 校验清单
  5. 生成 MODELS.md 下载说明模板 (含网盘链接占位符)

用法
----
    python export_evolved_model.py --adapter newlivingthings/run_evolve/latest_adapter
    python export_evolved_model.py --merge --base-model Qwen/Qwen3.5-0.8B-Base
    python export_evolved_model.py --merge --gguf --converter D:\\llama.cpp\\convert_hf_to_gguf.py

安全约定:
  * 只读源目录, 所有产物写到 export_pkg/ (该目录已在 .gitignore 中)
  * 不会自动上传, 不会自动 git add
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYDEPS = os.path.join(HERE, "newlivingthings", ".pydeps")
if os.path.isdir(PYDEPS) and PYDEPS not in sys.path:
    sys.path.insert(0, PYDEPS)

DEFAULT_ADAPTER = os.path.join(HERE, "newlivingthings", "run_evolve", "latest_adapter")
DEFAULT_OUT = os.path.join(HERE, "export_pkg")


def log(msg):
    print(msg, flush=True)


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f GB" % n


def sha256_of(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def collect_adapter_files(adapter_dir):
    """只收集 LoRA 相关文件, 跳过训练中间产物."""
    wanted = []
    for name in ("adapter_config.json", "adapter_model.safetensors", "adapter_model.bin",
                 "README.md", "tokenizer_config.json", "tokenizer.json",
                 "special_tokens_map.json"):
        p = os.path.join(adapter_dir, name)
        if os.path.isfile(p):
            wanted.append(p)
    if not any(os.path.basename(p).startswith("adapter_model") for p in wanted):
        raise RuntimeError("适配器目录里没有 adapter_model.* , 不是有效的 LoRA 目录: %s" % adapter_dir)
    return wanted


def check_adapter(adapter_dir):
    if not os.path.isdir(adapter_dir):
        raise RuntimeError("找不到 LoRA 适配器目录: %s\n"
                           "提示: 先让熵灵完成一次进化, 或指定 --adapter 路径." % adapter_dir)
    cfg = os.path.join(adapter_dir, "adapter_config.json")
    if not os.path.isfile(cfg):
        raise RuntimeError("缺少 adapter_config.json: %s" % adapter_dir)
    with open(cfg, "r", encoding="utf-8") as f:
        info = json.load(f)
    if info.get("simulated"):
        log("[提醒] 该适配器来自模拟训练 (simulated=true), 只用于演示, 不是真实模型.")
    if not info.get("base_model_name_or_path"):
        # 模拟产物或早期训练可能没记录基底模型, 补一个可追溯的默认值
        info["base_model_name_or_path"] = "Qwen/Qwen3.5-0.8B-Base (未记录, 按默认基底标注)"
    return info


def merge_lora(base_model, adapter_dir, out_dir):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    import torch

    os.makedirs(out_dir, exist_ok=True)
    log("[合并] 加载基础模型: %s" % base_model)
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        base_model, torch_dtype=torch.float32, trust_remote_code=True, low_cpu_mem_usage=True)
    log("[合并] 加载 LoRA: %s" % adapter_dir)
    model = PeftModel.from_pretrained(model, adapter_dir)
    log("[合并] merge_and_unload ...")
    model = model.merge_and_unload()
    model.save_pretrained(out_dir, safe_serialization=True)
    tokenizer.save_pretrained(out_dir)
    log("[合并] 完成: %s (%s)" % (out_dir, human(dir_size(out_dir))))
    return out_dir


def convert_gguf(hf_dir, out_file, converter):
    if not converter or not os.path.exists(converter):
        raise RuntimeError("未找到 convert_hf_to_gguf.py, 请用 --converter 指定")
    cmd = [sys.executable, converter, hf_dir, "--outfile", out_file, "--outtype", "q8_0"]
    log("[GGUF] " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out_file):
        raise RuntimeError("GGUF 转换失败: %s" % (r.stderr or r.stdout)[-400:])
    log("[GGUF] 完成: %s (%s)" % (out_file, human(os.path.getsize(out_file))))
    return out_file


def build_zip(files, zip_path):
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, os.path.basename(p))
    log("[打包] %s (%s)" % (zip_path, human(os.path.getsize(zip_path))))
    return zip_path


def write_manifest(out_dir, artifacts, meta):
    rows = ["# 熵灵进化模型 · 下载说明", ""]
    rows.append("> 本文件由 `export_evolved_model.py` 自动生成.")
    rows.append(">")
    rows.append("> **大模型文件不放在主仓库里.** 请从下面的网盘链接手动下载.")
    rows.append("")
    rows.append("## 版本信息")
    rows.append("")
    rows.append("| 项 | 值 |")
    rows.append("|---|---|")
    for k, v in meta.items():
        rows.append("| %s | %s |" % (k, v))
    rows.append("")
    rows.append("## 网盘链接 (请手动填写)")
    rows.append("")
    rows.append("| 文件 | 大小 | 下载链接 | SHA256 |")
    rows.append("|---|---|---|---|")
    for name, size, digest in artifacts:
        rows.append("| `%s` | %s | _（粘贴网盘链接）_ | `%s` |" % (name, size, digest))
    rows.append("")
    rows.append("## 下载后的使用方法")
    rows.append("")
    rows.append("```bash")
    rows.append("# 1) 校验完整性")
    rows.append("sha256sum <下载的文件>")
    rows.append("")
    rows.append("# 2) 解压 LoRA, 放进训练产物目录")
    rows.append("unzip entropy_evolved_lora.zip -d newlivingthings/run_evolve/")
    rows.append("")
    rows.append("# 3) 或者直接导入 GGUF 到 Ollama")
    rows.append("ollama create entropy_evolved -f ./Modelfile")
    rows.append("```")
    rows.append("")
    path = os.path.join(out_dir, "MODELS.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows))
    log("[清单] %s" % path)
    return path


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="打包熵灵进化模型用于网盘分享")
    p.add_argument("--adapter", default=DEFAULT_ADAPTER, help="LoRA 适配器目录")
    p.add_argument("--out", default=DEFAULT_OUT, help="产物输出目录")
    p.add_argument("--merge", action="store_true", help="合并成完整权重再打包")
    p.add_argument("--base-model", default="Qwen/Qwen3.5-0.8B-Base")
    p.add_argument("--gguf", action="store_true", help="额外转换 GGUF")
    p.add_argument("--converter", default=os.environ.get("AC_GGUF_CONVERTER", ""))
    p.add_argument("--no-zip", dest="zip", action="store_false")
    p.add_argument("--dry-run", action="store_true", help="只检查, 不生成文件")
    p.set_defaults(zip=True)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    log("=" * 60)
    log(" 熵灵进化模型导出")
    log("=" * 60)

    try:
        info = check_adapter(args.adapter)
    except Exception as e:
        log("[失败] %s" % e)
        return 2

    lora_files = collect_adapter_files(args.adapter)
    total = sum(os.path.getsize(f) for f in lora_files)
    log("[信息] 适配器: %s" % args.adapter)
    log("[信息] LoRA 参数: r=%s, alpha=%s" % (info.get("r"), info.get("lora_alpha")))
    log("[信息] 体积: %s (%d 个文件)" % (human(total), len(lora_files)))
    log("[信息] 基底模型: %s" % info.get("base_model_name_or_path"))

    if args.dry_run:
        log("[dry-run] 不生成任何文件.")
        return 0

    os.makedirs(args.out, exist_ok=True)
    stamp = time.strftime("%Y%m%d")
    artifacts = []

    lora_dir = os.path.join(args.out, "entropy_evolved_lora")
    if os.path.isdir(lora_dir):
        shutil.rmtree(lora_dir, ignore_errors=True)
    os.makedirs(lora_dir, exist_ok=True)
    for f in lora_files:
        shutil.copy2(f, os.path.join(lora_dir, os.path.basename(f)))
    if args.zip:
        zpath = build_zip(lora_files, os.path.join(args.out, "entropy_evolved_lora_%s.zip" % stamp))
        artifacts.append((os.path.basename(zpath), human(os.path.getsize(zpath)), sha256_of(zpath)))

    if args.merge:
        merged_dir = os.path.join(args.out, "merged_hf")
        try:
            merge_lora(args.base_model, args.adapter, merged_dir)
        except ImportError as e:
            log("[失败] 缺少依赖: %s (pip install --target .pydeps peft accelerate)" % e)
            return 4
        except Exception as e:
            log("[失败] 合并出错: %s: %s" % (type(e).__name__, e))
            return 1
        if args.gguf:
            gguf_out = os.path.join(args.out, "entropy_evolved_%s.gguf" % stamp)
            try:
                gguf_path = convert_gguf(merged_dir, gguf_out, args.converter)
                artifacts.append((os.path.basename(gguf_path), human(os.path.getsize(gguf_path)),
                                  sha256_of(gguf_path)))
            except Exception as e:
                log("[警告] GGUF 转换失败: %s" % e)

    meta = {
        "版本": "entropy_evolved_%s" % stamp,
        "导出时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "LoRA r/alpha": "%s / %s" % (info.get("r"), info.get("lora_alpha")),
        "基底模型": info.get("base_model_name_or_path"),
        "是否模拟产物": info.get("simulated", False),
    }
    write_manifest(args.out, artifacts, meta)

    log("")
    log("=" * 60)
    log(" 导出完成, 产物在: %s" % args.out)
    for name, size, digest in artifacts:
        log("   %s  (%s)" % (name, size))
        log("   SHA256 %s" % digest)
    log("")
    log(" 下一步 (重要):")
    log("   1. 把上面列出的 zip / gguf 手动上传到网盘")
    log("   2. 把网盘链接填进 export_pkg/MODELS.md 的表格")
    log("   3. 只把 MODELS.md 复制进仓库, 大文件不要提交:")
    log("        git add MODELS.md")
    log("   4. 确认 git status 里看不到 zip/gguf/safetensors")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
