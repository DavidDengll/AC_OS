# train_lora.py
# -*- coding: utf-8 -*-
"""
train_lora.py —— 第二步：空闲触发的 LoRA 手术（Qwen 架构）

由 self_finetune.py 通过 subprocess 在后台静默启动：
    python train_lora.py --dataset run_evolve/sft_dataset.jsonl \
                         --output-dir run_evolve/latest_adapter \
                         --log-file run_evolve/train_lora.log \
                         --result-file run_evolve/result.json

设计要点：
  * 只训练 LoRA 适配器（q/k/v/o + gate/up/down），不改动原模型文件
  * 显式捕获显存/内存不足 -> 写 result.json 并退出码 3，主程序优雅回滚
  * 依赖缺失 -> 退出码 4；硬崩溃 -> 非 0 退出码，日志可被主程序归类
  * 支持 --simulate + 环境变量 fail-mode 做无 GPU 环境下的全流程演练
"""

import argparse
import json
import os
import sys
import time
import traceback
import datetime

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

EXIT_OK = 0
EXIT_OOM = 3
EXIT_DEP = 4
EXIT_BAD_ARGS = 2
EXIT_CRASH = 1


def _ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class _Tee:
    """同时写 stderr 与日志文件，保证主程序能读到完整日志。"""

    def __init__(self, path):
        self.path = path
        self.fh = None
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self.fh = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, text):
        try:
            sys.__stderr__.write(text)
            sys.__stderr__.flush()
        except Exception:
            pass
        if self.fh:
            try:
                self.fh.write(text)
                self.fh.flush()
            except Exception:
                pass

    def flush(self):
        if self.fh:
            try:
                self.fh.flush()
            except Exception:
                pass

    def close(self):
        try:
            if self.fh:
                self.fh.close()
        except Exception:
            pass


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Qwen 架构 LoRA 自我微调")
    p.add_argument("--dataset", required=True, help="SFT 数据 jsonl")
    p.add_argument("--output-dir", required=True, help="LoRA 适配器输出目录")
    p.add_argument("--log-file", default=None)
    p.add_argument("--result-file", default=None)
    p.add_argument("--base-model", default=None,
                   help="HF 仓库或本地目录；缺省读 config.BASE_MODEL_HF_REPO")
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--max-seq-len", type=int, default=512)
    p.add_argument("--lora-r", type=int, default=8)
    p.add_argument("--lora-alpha", type=int, default=16)
    p.add_argument("--simulate", action="store_true",
                   help="不加载权重，用纯 Python 循环模拟训练（演练/CI 用）")
    p.add_argument("--steps", type=int, default=30, help="simulate 模式下每轮步数")
    return p.parse_args(argv)


def write_result(path, payload):
    if not path:
        return
    payload = dict(payload)
    payload.setdefault("time", _ts())
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def count_samples(path):
    n = 0
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    json.loads(line)
                    n += 1
                except Exception:
                    continue
    return n


def is_oom(exc):
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "outofmemory" in name or "out of memory" in text:
        return True
    if "cuda" in text and "memory" in text:
        return True
    if "can't allocate" in text or "bad_alloc" in text:
        return True
    if "内存不足" in text or "显存不足" in text:
        return True
    return False


def simulate_training(args, log):
    """无 GPU 环境下的确定性演练：校验数据 -> 生成 LoRA 产物 -> 按 fail-mode 失败。"""
    n = count_samples(args.dataset)
    log.write("[simulate] 目标模型: %s\n" % (args.base_model or "(config)"))
    log.write("[simulate] 样本数: %d\n" % n)
    if n <= 0:
        raise RuntimeError("训练数据为空，无法微调")
    if n < 20:
        raise RuntimeError("优质基因不足 20 条（当前 %d），拒绝启动微调" % n)

    fail_mode = os.environ.get("AC_SIMULATE_FAIL", "")
    log.write("[simulate] LoRA r=%d alpha=%d epochs=%d lr=%g\n"
              % (args.lora_r, args.lora_alpha, args.epochs, args.lr))
    total_steps = max(1, args.steps)
    for step in range(1, total_steps + 1):
        if step == max(1, total_steps // 3):
            log.write("[simulate] loss=2.4310 it/s=3.2（预热完毕）\n")
        if fail_mode == "oom" and step == max(1, total_steps * 2 // 3):
            log.write("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 512.00 MiB "
                      "(GPU 0; 0.00 MiB already allocated)\n")
            raise MemoryError("CUDA out of memory. Tried to allocate 512.00 MiB")
        if fail_mode == "crash" and step == max(1, total_steps * 2 // 3):
            log.write("RuntimeError: 训练进程内部崩溃（模拟）\n")
            raise RuntimeError("训练进程内部崩溃（模拟）")
        time.sleep(0.02)
    log.write("[simulate] loss=0.8213，收敛\n")

    if fail_mode == "dep":
        log.write("ModuleNotFoundError: No module named 'peft'\n")
        raise ImportError("No module named 'peft'")

    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(args.output_dir, "adapter_config.json"), "w", encoding="utf-8") as f:
        json.dump({"peft_type": "LORA", "task_type": "CAUSAL_LM", "r": args.lora_r,
                   "lora_alpha": args.lora_alpha, "target_modules": [
                       "q_proj", "k_proj", "v_proj", "o_proj",
                       "gate_proj", "up_proj", "down_proj"],
                   "base_model_name_or_path": args.base_model,
                   "simulated": True}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.output_dir, "adapter_model.safetensors"), "wb") as f:
        f.write(b"SIMULATED-LORA-WEIGHTS\n")
    return n


def real_training(args, log):
    """真实 LoRA 训练（需要 torch + transformers + peft + 可下载/已缓存的权重）。"""
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from transformers import TrainingArguments, Trainer
        from transformers import DataCollatorForLanguageModeling
        from peft import LoraConfig, get_peft_model
    except Exception as e:
        log.write("ModuleNotFoundError: 缺少微调依赖 -> %s\n" % e)
        raise ImportError(str(e))

    base = args.base_model
    if not base:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import config
            base = getattr(config, "BASE_MODEL_HF_REPO", "Qwen/Qwen3.5-0.8B-Base")
        except Exception:
            base = "Qwen/Qwen3.5-0.8B-Base"

    records = []
    with open(args.dataset, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    if not records:
        raise RuntimeError("训练数据为空，无法微调")
    log.write("[数据] %d 条优质基因\n" % len(records))

    torch.set_num_threads(max(1, (os.cpu_count() or 4) - 2))
    log.write("[加载] %s\n" % base)
    tokenizer = AutoTokenizer.from_pretrained(base, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    dtype = torch.float32
    if torch.cuda.is_available():
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        base, torch_dtype=dtype, trust_remote_code=True, low_cpu_mem_usage=True)

    lora_cfg = LoraConfig(
        r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_cfg)
    model.print_trainable_parameters()

    def encode(rec):
        text = rec.get("text")
        if not text:
            text = ("<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n%s<|im_end|>\n"
                    % (rec.get("messages", [{}, {}])[0].get("content", ""),
                       rec.get("messages", [{}, {}])[1].get("content", "")))
        ids = tokenizer(text, truncation=True, max_length=args.max_seq_len)["input_ids"]
        return {"input_ids": ids, "labels": list(ids), "attention_mask": [1] * len(ids)}

    dataset = [encode(r) for r in records]
    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    use_cuda = torch.cuda.is_available()
    training_args = TrainingArguments(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        logging_steps=1,
        save_strategy="no",
        report_to=[],
        fp16=(use_cuda and dtype == torch.float16),
        bf16=(use_cuda and dtype == torch.bfloat16),
        use_cpu=not use_cuda,
        dataloader_pin_memory=False,
    )
    trainer = Trainer(model=model, args=training_args, train_dataset=dataset,
                      data_collator=collator)
    trainer.train()
    os.makedirs(args.output_dir, exist_ok=True)
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    return len(dataset)


def train_main(args):
    log = _Tee(args.log_file)
    sys.stderr = log
    started = time.time()
    log.write("\n[训练] %s 开始 LoRA 手术\n" % _ts())
    write_result(args.result_file, {"status": "running", "pid": os.getpid()})

    try:
        if args.simulate or os.environ.get("AC_SIMULATE_TRAIN") == "1":
            n = simulate_training(args, log)
        else:
            n = real_training(args, log)

        elapsed = round(time.time() - started, 2)
        adapter_ok = os.path.exists(os.path.join(args.output_dir, "adapter_config.json"))
        write_result(args.result_file, {
            "status": "ok" if adapter_ok else "error",
            "kind": "" if adapter_ok else "merge",
            "adapter": os.path.abspath(args.output_dir),
            "samples": n, "elapsed": elapsed,
            "error": "" if adapter_ok else "未生成 adapter_config.json",
        })
        log.write("[训练] %s 完成，样本 %d，耗时 %.2fs\n" % (_ts(), n, elapsed))
        log.close()
        return EXIT_OK if adapter_ok else EXIT_CRASH

    except MemoryError as e:
        _fail(args, log, "oom", "显存/内存不足: %s" % e, EXIT_OOM)
        return EXIT_OOM
    except (ImportError, ModuleNotFoundError) as e:
        _fail(args, log, "dependency", "缺少微调依赖: %s" % e, EXIT_DEP)
        return EXIT_DEP
    except Exception as e:
        kind = "oom" if is_oom(e) else "crash"
        _fail(args, log, kind, "%s: %s" % (type(e).__name__, e), EXIT_OOM if kind == "oom" else EXIT_CRASH)
        log.write(traceback.format_exc() + "\n")
        return EXIT_OOM if kind == "oom" else EXIT_CRASH


def _fail(args, log, kind, message, code):
    log.write("[训练失败:%s] %s\n" % (kind, message))
    write_result(args.result_file, {
        "status": "failed", "kind": kind, "error": message,
        "adapter": os.path.abspath(args.output_dir),
        "adapter_exists": os.path.exists(os.path.join(args.output_dir, "adapter_config.json")),
        "exit_code": code,
    })
    try:
        log.close()
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(train_main(parse_args()))
