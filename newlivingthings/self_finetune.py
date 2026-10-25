# self_finetune.py
# -*- coding: utf-8 -*-
"""
self_finetune.py —— 全自动"自我微调"闭环（AC OS 基因重塑）

三步自进化流水线：
  第一步  分泌多巴胺，收集优质基因   : D > 0.8 或 E > 0.8 -> 写 finetune_data.jsonl（>=20 才放行）
  第二步  空闲触发微调（LoRA 手术）  : subprocess 后台静默启动 train_lora.py
  第三步  基因融合与热替换（换脑重生）: 合并 LoRA -> GGUF / ollama create -> 改 config.py -> os.execv

容错保命：
  * 显存不足 / 依赖缺失 / 超时 / 崩溃 -> 打印 [进化失败]，恢复 config.py，原大脑继续运行
  * 绝不在失败后删除任何用户数据；数据文件只增不减（超上限时滚动裁剪）
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config  # noqa: E402

# ============================================
# 运行时路径（相对脚本目录，跨平台安全）
# ============================================
DATA_FILE = os.path.join(HERE, getattr(config, "FINETUNE_DATA_FILE", "finetune_data.jsonl"))
# 任务一：微调产物目录也走统一解析（AC_FINETUNE_DIR 优先，且必须可写）
try:
    import cache_paths as _cache_paths
    RUN_DIR = _cache_paths.resolve_finetune_dir() if os.environ.get("AC_FINETUNE_DIR")         else os.path.join(HERE, getattr(config, "RUN_DIR", "run_evolve"))
except Exception:
    RUN_DIR = os.path.join(HERE, getattr(config, "RUN_DIR", "run_evolve"))
LOCK_FILE = os.path.join(RUN_DIR, "finetune.lock")
LOG_FILE = os.path.join(RUN_DIR, "train_lora.log")
RESULT_FILE = os.path.join(RUN_DIR, "result.json")
LATEST_ADAPTER = os.path.join(RUN_DIR, "latest_adapter")
CONFIG_PATH = os.path.join(HERE, "config.py")

GEN_FILE = os.path.join(HERE, getattr(config, "GENERATION_FILE", "generation.json"))
EVO_LOG = os.path.join(HERE, getattr(config, "EVOLUTION_LOG_FILE", "evolution_log.jsonl"))

TRAIN_SCRIPT = os.path.join(HERE, "train_lora.py")
MERGE_SCRIPT = os.path.join(HERE, "merge_export.py")

_LOCK = threading.RLock()
_RUNTIME = {"provider": None, "training": False, "last_attempt": 0.0, "last_error": ""}

# 中文标签
_FAIL_TAGS = {
    "oom": "显存不足",
    "mem": "内存不足",
    "dependency": "依赖缺失",
    "timeout": "训练超时",
    "crash": "训练进程异常退出",
    "dataset": "训练数据为空",
    "merge": "LoRA 合并失败",
    "ollama": "Ollama 注册失败",
    "restart": "热替换失败",
    "unknown": "未知错误",
}


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_dirs():
    os.makedirs(RUN_DIR, exist_ok=True)


def _tag(kind):
    return _FAIL_TAGS.get(kind, kind)


def _short_err(text, limit=260):
    text = (text or "未知错误").strip().replace("\r", "")
    return text[-limit:] if len(text) > limit else text


# ============================================
# 通用：原子写 JSON / JSONL
# ============================================
def _atomic_write_text(path, text):
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_", suffix=".swp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _dump_json(path, data):
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def _append_jsonl(path, record):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def log_evolution(event, **fields):
    """把每一次进化尝试写入 evolution_log.jsonl，永不抛异常。"""
    try:
        rec = {"time": _now(), "event": event}
        rec.update(fields)
        _append_jsonl(EVO_LOG, rec)
    except Exception:
        pass


# ============================================
# 第一步：分泌多巴胺，收集优质基因
# ============================================
def harvest_gene(instruction, output, mood):
    """在主循环中调用。

    当前 多巴胺(D) > 0.8 或 内啡肽(E) > 0.8 时，把
    {"instruction": 用户输入, "output": 模型回答} 追加进 finetune_data.jsonl。

    返回 dict：{"collected": bool, "reason": str, "total": int}
    """
    d = float((mood or {}).get("dopamine", 0.0))
    e = float((mood or {}).get("endorphin", 0.0))
    d_th = float(getattr(config, "TASTE_D_THRESHOLD", 0.8))
    e_th = float(getattr(config, "TASTE_E_THRESHOLD", 0.8))

    if not (d > d_th or e > e_th):
        return {"collected": False, "reason": "情绪未达高光阈值", "total": gene_count()}

    instruction = (instruction or "").strip()
    output = (output or "").strip()
    min_len = int(getattr(config, "HIGH_QUALITY_MIN_LEN", 4))
    if len(instruction) < 1 or len(output) < min_len:
        return {"collected": False, "reason": "内容过短，非优质基因", "total": gene_count()}

    rec = {
        "instruction": instruction,
        "output": output,
        "dopamine": round(d, 4),
        "endorphin": round(e, 4),
        "model": getattr(config, "MODEL_NAME", ""),
        "ts": _now(),
    }
    with _LOCK:
        _append_jsonl(DATA_FILE, rec)
        _enforce_capacity()
        total = gene_count()
    log_evolution("gene_collected", dopamine=rec["dopamine"], endorphin=rec["endorphin"], total=total)
    return {"collected": True, "reason": "D=%.2f E=%.2f 触发分泌" % (d, e), "total": total}


def _enforce_capacity():
    """基因池只保留最新 N 条；只做滚动裁剪，不误删其它文件。"""
    cap = int(getattr(config, "MAX_FINETUNE_SAMPLES", 200))
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        if len(lines) <= cap:
            return
        _atomic_write_text(DATA_FILE, "\n".join(lines[-cap:]) + "\n")
    except Exception:
        pass


def load_genes():
    """读取全部优质基因（非法行自动跳过）。"""
    genes = []
    if not os.path.exists(DATA_FILE):
        return genes
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict) and obj.get("instruction") and obj.get("output"):
                    genes.append(obj)
    except Exception:
        return genes
    return genes


def gene_count():
    return len(load_genes())


def has_enough_genes():
    return gene_count() >= int(getattr(config, "FINETUNE_TRIGGER_COUNT", 20))


def build_sft_dataset(genes=None, path=None):
    """把优质基因整理成 SFT jsonl（messages 格式），供 train_lora.py 消费。"""
    genes = genes if genes is not None else load_genes()
    path = path or os.path.join(RUN_DIR, "sft_dataset.jsonl")
    _ensure_dirs()
    rows = []
    for g in genes:
        text = (
            "<|im_start|>user\n" + str(g["instruction"]).strip() + "<|im_end|>\n"
            "<|im_start|>assistant\n" + str(g["output"]).strip() + "<|im_end|>\n"
        )
        rows.append(json.dumps({"messages": [
            {"role": "user", "content": str(g["instruction"]).strip()},
            {"role": "assistant", "content": str(g["output"]).strip()},
        ], "text": text}, ensure_ascii=False))
    _atomic_write_text(path, "\n".join(rows) + ("\n" if rows else ""))
    return path, len(rows)


# ============================================
# 第二步：空闲触发微调（LoRA 手术）
# ============================================
class _TrainingAlreadyRunning(Exception):
    pass


def _pid_alive(pid):
    if not pid:
        return False
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid), "/NH"],
                                 capture_output=True, text=True, timeout=10,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return str(pid) in (out.stdout or "")
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def acquire_lock():
    """单实例锁：防止重复启动多个训练进程。"""
    _ensure_dirs()
    for _ in range(2):
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "time": time.time()}, f)
            return True
        except FileExistsError:
            try:
                with open(LOCK_FILE, "r", encoding="utf-8") as f:
                    holder = json.load(f).get("pid")
            except Exception:
                holder = None
            if holder and _pid_alive(holder):
                raise _TrainingAlreadyRunning("已有训练进程 PID=%s 在运行" % holder)
            try:
                os.remove(LOCK_FILE)  # 只清理本模块持有的陈腐锁
            except OSError:
                raise _TrainingAlreadyRunning("无法获取训练锁")
    raise _TrainingAlreadyRunning("无法获取训练锁")


def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except OSError:
        pass


def is_training():
    return bool(_RUNTIME.get("training"))


def classify_failure(log_text):
    """把训练日志归类为 oom / mem / dependency / crash / timeout。"""
    t = (log_text or "").lower()
    oom_patterns = [
        "outofmemoryerror", "out of memory", "cuda out of memory",
        "not enough memory", "insufficient memory", "内存不足", "显存不足",
        "defaultcpuallocator can't allocate", "std::bad_alloc",
    ]
    for p in oom_patterns:
        if p in t:
            return "oom"
    dep_patterns = [
        "modulenotfounderror", "no module named", "importerror",
    ]
    for p in dep_patterns:
        if p in t:
            return "dependency"
    if "timeout" in t or "超时" in t:
        return "timeout"
    return "crash"


def _env_for_train():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["HF_ENDPOINT"] = env.get("HF_ENDPOINT", "https://hf-mirror.com")
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    # 任务一：把解析后的可写缓存目录传给子进程，避免子进程再踩一次权限错误
    try:
        import cache_paths as _cp
        env.update(_cp.apply_hf_env())
    except Exception:
        pass
    # 模拟档位：需要显式开启，否则真实训练会尝试加载权重
    for key in ("AC_SIMULATE_TRAIN", "AC_TRAIN_BASE_MODEL"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def start_training(interactive=True):
    """后台静默启动 train_lora.py。返回训练上下文 dict（不阻塞）。

    使用 subprocess.Popen：不抢占前台、不弹窗、不阻塞主循环。
    """
    with _LOCK:
        if is_training():
            raise _TrainingAlreadyRunning("训练已经在进行中")
        if not has_enough_genes():
            return {"started": False, "reason": "优质基因不足 %d 条" %
                    int(getattr(config, "FINETUNE_TRIGGER_COUNT", 20))}

        acquire_lock()
        _runtime_switch_to_training()

        _ensure_dirs()
        dataset_path, rows = build_sft_dataset()
        # 陈旧结果不能冒充本次结果
        if os.path.exists(RESULT_FILE):
            os.replace(RESULT_FILE, RESULT_FILE + ".stale")

        if interactive:
            print("[系统休眠] 正在根据近期记忆微调 0.8B 大脑...", flush=True)

        cmd = [
            sys.executable, TRAIN_SCRIPT,
            "--dataset", dataset_path,
            "--output-dir", LATEST_ADAPTER,
            "--log-file", LOG_FILE,
            "--result-file", RESULT_FILE,
        ]
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | \
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            flags = os.setsid if hasattr(os, "setsid") else 0

        logf = None
        try:
            logf = open(LOG_FILE, "a", encoding="utf-8")
            logf.write("\n===== %s 启动训练 =====\n" % _now())
            logf.flush()
            proc = subprocess.Popen(
                cmd, cwd=HERE, env=_env_for_train(),
                stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                creationflags=flags, start_new_session=(os.name != "nt"),
            )
        except Exception as e:
            release_lock()
            _runtime_switch_back_to_base()
            raise RuntimeError("无法启动训练进程: %s" % e)
        finally:
            try:
                if logf is not None:
                    logf.close()
            except Exception:
                pass

        log_evolution("train_started", pid=proc.pid, samples=rows)
        return {"started": True, "proc": proc, "pid": proc.pid, "samples": rows,
                "dataset": dataset_path}


def _read_log_tail(limit=4000):
    try:
        if not os.path.exists(LOG_FILE):
            return ""
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            return f.read()[-limit:]
    except Exception:
        return ""


def wait_training(ctx, timeout=None, poll=None):
    """等待训练结束并做统一验收。返回 {"ok": bool, "kind": str, "error": str, "adapter": str}"""
    proc = ctx["proc"]
    timeout = timeout if timeout is not None else float(
        getattr(config, "FINETUNE_TIMEOUT_SECONDS", 7200))
    poll = poll if poll is not None else float(getattr(config, "FINETUNE_POLL_SECONDS", 1.0))
    deadline = time.time() + timeout
    result = {"ok": False, "kind": "crash", "error": "", "adapter": ""}
    rc = None

    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                break
            if time.time() > deadline:
                _kill_proc(proc)
                result.update(kind="timeout", error="训练超过 %d 秒未完成" % timeout)
                break
            time.sleep(poll)
    finally:
        # 不管走哪条分支，锁与训练标记必须归位
        release_lock()
        _RUNTIME["training"] = False
        _RUNTIME["last_attempt"] = time.time()

    if result["kind"] == "timeout":
        log_evolution("train_failed", kind="timeout", error=result["error"])
        return result

    res = None
    if os.path.exists(RESULT_FILE):
        try:
            with open(RESULT_FILE, "r", encoding="utf-8") as f:
                res = json.load(f)
        except Exception:
            res = None

    log_text = _read_log_tail()
    ok = bool(res and res.get("status") == "ok") and rc == 0
    if ok:
        adapter = res.get("adapter") or LATEST_ADAPTER
        if not os.path.isdir(adapter) or \
                not os.path.exists(os.path.join(adapter, "adapter_config.json")):
            result.update(kind="merge", error="训练报告成功但 LoRA 权重缺失: %s" % adapter)
        else:
            result.update(ok=True, kind="ok", adapter=adapter)
    else:
        if res and res.get("kind"):
            kind = res.get("kind")
            err = res.get("error") or ""
        else:
            kind = classify_failure(log_text)
            err = "训练退出码 %s\n%s" % (rc, _short_err(log_text))
        result.update(kind=kind, error=err)
    if result["ok"]:
        log_evolution("train_ok", adapter=result["adapter"])
    else:
        log_evolution("train_failed", kind=result["kind"], error=_short_err(result["error"]))
    return result


def _kill_proc(proc):
    try:
        if proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=15)
            else:
                os.killpg(os.getpgid(proc.pid), 9)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def fail_evolution(kind, error, interactive=True):
    """统一失败出口：[进化失败] 保持原大脑运行，绝不死机。"""
    _RUNTIME["last_error"] = "%s: %s" % (_tag(kind), _short_err(error))
    if interactive:
        print("[进化失败] 保持原大脑运行，绝对不死机 (%s)" % _tag(kind), flush=True)
        print("         原因: %s" % _short_err(error, 180), flush=True)
    log_evolution("evolution_failed", kind=kind, error=_short_err(error))
    return False


# ============================================
# 第三步：基因融合与热替换（换脑重生）
# ============================================
def search_replace(text, new_name):
    pat = re.compile(r'(?m)^(MODEL_NAME\s*=\s*)(["\'])(.*?)\2')
    if not pat.search(text):
        raise RuntimeError("config.py 中找不到 MODEL_NAME 定义")
    return pat.sub(lambda m: m.group(1) + m.group(2) + new_name + m.group(2), text, count=1)


def switch_config_model(new_name, config_path=CONFIG_PATH):
    """把 config.py 的 MODEL_NAME 换成新模型；先备份，再原子替换。"""
    with open(config_path, "r", encoding="utf-8") as f:
        text = f.read()
    new_text = search_replace(text, new_name)
    if new_text == text:
        return False
    bak_dir = os.path.join(HERE, "_backup")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(bak_dir, "config_before_switch_%s.py" %
                       datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(config_path, bak)
    _atomic_write_text(config_path, new_text)
    return True


def _decode(data):
    """子进程输出在中文 Windows 上可能是 GBK，统一解码，避免乱码。"""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    for enc in ("utf-8", "gbk", "cp936", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return str(data)


def merge_and_export(adapter, base_model, new_name=None, interactive=True):
    """合并 LoRA -> 导出 GGUF -> ollama create。任一步失败都返回 ok=False（不致命）。"""
    new_name = new_name or getattr(config, "MAX_NEW_MODEL_NAME", "entropy_evolved")
    if not (getattr(config, "AUTO_MERGE_AND_REPLACE", True)):
        return {"ok": False, "kind": "merge", "error": "配置关闭了自动融合"}
    if not os.path.exists(MERGE_SCRIPT):
        return {"ok": False, "kind": "merge", "error": "merge_export.py 不存在"}
    out_dir = os.path.join(RUN_DIR, "merged_hf")
    cmd = [sys.executable, MERGE_SCRIPT, "--adapter", adapter, "--base-model", base_model,
           "--output-dir", out_dir, "--name", new_name]
    if getattr(config, "AUTO_OLLAMA_CREATE", True):
        cmd.append("--ollama-create")
    try:
        proc = subprocess.run(cmd, cwd=HERE, env=_env_for_train(),
                              capture_output=True, timeout=7200)
        out = _decode(proc.stdout)
        err = _decode(proc.stderr)
        log_evolution("merge", rc=proc.returncode, tail=_short_err(out[-500:]))
        if proc.returncode != 0:
            return {"ok": False, "kind": "merge", "error": _short_err(err or out)}
        return {"ok": True}
    except subprocess.TimeoutExpired:
        return {"ok": False, "kind": "timeout", "error": "合并/导出超时"}
    except Exception as e:
        return {"ok": False, "kind": "merge", "error": str(e)}


def hot_replace(new_name):
    """热替换：os.execv 重启进程，让新大脑生效。"""
    argv = [sys.executable] + [os.path.abspath(a) if a.endswith(".py") else a for a in sys.argv]
    if not argv[1:] or not argv[1].endswith(".py"):
        argv = [sys.executable, os.path.join(HERE, "main.py")] + sys.argv[1:]
    log_evolution("hot_replace", model=new_name, argv=argv)
    try:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os.execv(sys.executable, argv)
    except Exception as e:
        log_evolution("hot_replace_failed", error=str(e))
        return fail_evolution("restart", "os.execv 失败: %s" % e)


# ============================================
# 状态机：基底大脑 / 进化大脑
# ============================================
def _runtime_switch_to_training():
    """训练开机时把主服务端切到"影子"模型，避免参数错配。

    只改内存里的 provider.model，不触碰磁盘，失败零风险。
    """
    prov = _RUNTIME.get("provider")
    _RUNTIME["training"] = True
    _RUNTIME["base_model"] = getattr(config, "MODEL_NAME", "")
    if prov is None:
        return
    # 只有显式配置了与基底不同的影子模型时才切换，避免把云端大脑误切成本地小模型
    shadow = getattr(config, "SHADOW_MODEL", None)
    if shadow and shadow != _RUNTIME.get("base_model"):
        try:
            prov.model = shadow
            print("[微调] 训练期间主链路切到影子模型: %s（后台占满算力）" % shadow, flush=True)
        except Exception:
            pass


def _runtime_switch_back_to_base():
    prov = _RUNTIME.get("provider")
    _RUNTIME["training"] = False
    base = _RUNTIME.get("base_model") or getattr(config, "MODEL_NAME", "")
    if prov is not None and base:
        try:
            prov.model = base
        except Exception:
            pass


def switch_runtime_back_to_base():
    _runtime_switch_back_to_base()


def bind_provider(provider):
    """主程序把自己使用的模型客户端注册进来，失败时可安全回滚。"""
    _RUNTIME["provider"] = provider
    return provider


def current_model():
    prov = _RUNTIME.get("provider")
    if prov is not None and getattr(prov, "model", None):
        return prov.model
    return getattr(config, "MODEL_NAME", "")


def health_check():
    """验收用自检：数据/锁/配置/服务端全部可读可写。"""
    checks = {}
    checks["config_model"] = getattr(config, "MODEL_NAME", None)
    checks["gene_count"] = gene_count()
    checks["enough"] = has_enough_genes()
    checks["training"] = is_training()
    checks["lock_exists"] = os.path.exists(LOCK_FILE)
    checks["provider_model"] = current_model()
    checks["config_file_writable"] = os.access(CONFIG_PATH, os.W_OK)
    return checks


# ============================================
# 主循环胶水：空闲检测 + 完整进化编排
# ============================================
class IdleWatcher:
    """后台空闲检测器：在主循环空闲且基因足够时唤醒微调流水线。"""

    def __init__(self, on_idle=None, idle_seconds=None, poll_seconds=None):
        self.idle_seconds = float(idle_seconds or getattr(config, "IDLE_SECONDS", 15))
        self.poll = float(poll_seconds or getattr(config, "IDLE_POLL_SECONDS", 2))
        self.on_idle = on_idle
        self._last_activity = time.time()
        self._stop = threading.Event()
        self._thread = None
        self._fired = False

    def touch(self):
        self._last_activity = time.time()
        self._fired = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return self
        self._thread = threading.Thread(target=self._run, name="idle-watcher", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self.poll):
            try:
                idle_for = time.time() - self._last_activity
                if idle_for < self.idle_seconds or self._fired or is_training():
                    continue
                if not has_enough_genes():
                    continue
                self._fired = True
                log_evolution("idle_trigger", idle_for=round(idle_for, 1),
                              genes=gene_count())
                if self.on_idle:
                    self.on_idle()
            except Exception:
                # 后台线程绝不允许因异常静默死亡
                log_evolution("idle_error", error=traceback.format_exc()[-500:])


def _in_test_mode():
    return os.environ.get("AC_TEST_MODE") == "1"


def run_evolution_cycle(interactive=True):
    """完整一步：触发 -> 训练 -> 验收 -> 合并 -> 热替换，全程异常兜底。"""
    try:
        ctx = start_training(interactive=interactive)
    except _TrainingAlreadyRunning as e:
        return fail_evolution("crash", str(e), interactive)
    except Exception as e:
        release_lock()
        _runtime_switch_back_to_base()
        return fail_evolution(classify_failure(str(e)), str(e), interactive)

    if not ctx.get("started"):
        return fail_evolution("dataset", ctx.get("reason", "无法启动训练"), interactive)

    try:
        result = wait_training(ctx)
    except Exception as e:
        release_lock()
        _RUNTIME["training"] = False
        _runtime_switch_back_to_base()
        return fail_evolution(classify_failure(str(e)), str(e), interactive)

    if not result.get("ok"):
        _runtime_switch_back_to_base()
        return fail_evolution(result["kind"], result["error"], interactive)

    if not getattr(config, "AUTO_MERGE_AND_REPLACE", True):
        switch_runtime_back_to_base()
        return True

    new_name = getattr(config, "MAX_NEW_MODEL_NAME", "entropy_evolved")
    base = getattr(config, "BASE_MODEL_HF_REPO", "Qwen/Qwen3.5-0.8B-Base")
    merged = merge_and_export(result["adapter"], base, new_name, interactive)
    if not merged.get("ok"):
        switch_runtime_back_to_base()
        return fail_evolution(merged.get("kind", "merge"), merged.get("error", "合并失败"),
                              interactive)

    try:
        changed = switch_config_model(new_name)
    except Exception as e:
        switch_runtime_back_to_base()
        return fail_evolution("restart", str(e), interactive)

    if not changed:
        switch_runtime_back_to_base()
        return fail_evolution("restart", "config 中模型名已是 %s" % new_name, interactive)

    log_evolution("evolved", model=new_name, adapter=result["adapter"])
    if _in_test_mode():
        return True
    return hot_replace(new_name)


def restore_config_model(original_name=None):
    """回滚入口：把 config.py 的模型名恢复为基底大脑（保证"原大脑运行"）。"""
    target = original_name or getattr(config, "BASE_MODEL_NAME", "qwen3.5:0.8b")
    if getattr(config, "MODEL_NAME", None) != target:
        switch_config_model(target)
    return target


# ============================================
# 命令行自检（便于验收）
# ============================================
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(health_check(), ensure_ascii=False, indent=2))
    elif cmd == "train":
        ok = run_evolution_cycle(interactive=True)
        print("[进化结果] " + ("成功" if ok else "失败，已保留原大脑"))
        sys.exit(0 if ok else 0)
    else:
        print("用法: python self_finetune.py [status|train]")
