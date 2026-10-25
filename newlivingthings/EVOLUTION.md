# 自微调闭环 · 演进说明（EVOLUTION.md）

> AC OS 基因重塑：让熵灵在对话中积累"优质基因"，在空闲时给自己做 LoRA 手术，
> 训练成功则换脑重生，失败则优雅回滚、原大脑照常运行。

## 一、文件分工

| 文件 | 角色 | 说明 |
|---|---|---|
| `main.py` | 主程序 | 原有 `ConsciousnessSystem` 逻辑原样保留，外套生命循环（内分泌 + 基因采集 + 空闲进化 + 交互命令） |
| `self_finetune.py` | 闭环核心 | 三步流水线的编排者：采集 / 触发 / 验收 / 合并 / 热替换 / 回滚 |
| `train_lora.py` | 第二步 LoRA 手术 | 独立子进程运行，只训练适配器；OOM/缺依赖/崩溃写成 `result.json` + 退出码 |
| `merge_export.py` | 第三步融合 | peft 合并 -> GGUF -> Modelfile -> `ollama create entropy_evolved` |
| `evolution_engine.py` | 基因池 / 世代 | 统计基因、记录世代、失败免疫冷却，避免反复烧显存 |
| `test_evolve.py` | 验收测试 | 无 GPU 全流程模拟，含 OOM 回滚专项 |
| `main_orig_20261025.py` | 原版备份 | 改造前的 main.py 完整副本 |

## 二、三步流水线

### 第一步：分泌多巴胺，收集优质基因
```python
# main.py -> EntropyLife.run_cycle()
gene = sf.harvest_gene(user_input, model_output, mood)   # mood = {"dopamine": D, "endorphin": E, ...}
```
- 触发条件：**D > 0.8 或 E > 0.8**（`config.TASTE_D_THRESHOLD / TASTE_E_THRESHOLD`）
- 写入格式：`{"instruction": 用户输入, "output": 模型回答, "dopamine": ..., "endorphin": ..., "ts": ...}`
- 追加到 `finetune_data.jsonl`，只增不改；超过 `MAX_FINETUNE_SAMPLES` 时才滚动裁剪
- **满 20 条（`FINETUNE_TRIGGER_COUNT`）才允许进入第二步**

### 第二步：空闲触发微调（LoRA 手术）
- `IdleWatcher` 后台线程：连续 `IDLE_SECONDS` 秒无交互 -> 判定空闲
- 条件满足即 `subprocess.Popen` 静默拉起 `train_lora.py`（`CREATE_NO_WINDOW`，不抢前台）
- 终端打印：`[系统休眠] 正在根据近期记忆微调 0.8B 大脑...`
- 目标模块：`q_proj / k_proj / v_proj / o_proj / gate_proj / up_proj / down_proj`（适配 Qwen 架构）
- 单实例锁 `run_evolve/finetune.lock` 防止重复训练

### 第三步：基因融合与热替换（换脑重生）
1. `merge_export.py`：`PeftModel.merge_and_unload()` 合并为全量权重
2. 转换 GGUF（`convert_hf_to_gguf.py`，可用 `AC_GGUF_CONVERTER` 指定）
3. 生成 Modelfile 并执行 `ollama create entropy_evolved -f ./Modelfile`
4. 备份 `config.py` 后原子改写 `MODEL_NAME = "entropy_evolved"`
5. `os.execv(sys.executable, [...main.py...])` 强制重启 —— 用上自己训练的新大脑

## 三、容错保命机制

| 故障 | 检测方式 | 处理 |
|---|---|---|
| 显存/内存不足 | 训练异常 `OutOfMemoryError` / 日志关键字 | 写 `result.json`，打印 `[进化失败] 保持原大脑运行` |
| 依赖缺失 | `ModuleNotFoundError` | 同上，冷却 24h |
| 进程崩溃 | 退出码 != 0 | 日志归类为 `crash`，回滚 |
| 训练超时 | `FINETUNE_TIMEOUT_SECONDS` | `taskkill /T` 整棵进程树后回滚 |
| 合并/导出失败 | `merge_export.py` 退出码 | 不写 config，回滚 |
| `os.execv` 失败 | `OSError` | 捕获，原进程继续运行 |

**保证**：失败前后 `config.py` 的 `MODEL_NAME` 不变、内存中 provider 模型名回滚、训练锁释放、后台线程异常隔离。

## 四、运行方式

```bash
cd newlivingthings

# (可选) 安装微调依赖到工作区内，不污染全局环境
python -m pip install --target ./.pydeps peft accelerate

# 交互模式（可与熵灵对话，高光时刻自动采基因）
python main.py

# 后台循环模式（原 50 轮循环的改造版，无限循环）
python main.py --auto

# 无交互自检：跑 N 轮，观察基因采集链路
python main.py --selftest --rounds=20

# 查看进化状态
python self_finetune.py status
python evolution_engine.py

# 全流程验收（无需 GPU）
python test_evolve.py
```

交互命令：`/status` 状态 · `/evolve` 立即进化 · `/train` 触发训练 · `/quit` 退出

## 五、无 GPU 环境演练

```bash
# 模拟训练成功（不加载权重）
AC_SIMULATE_TRAIN=1 python self_finetune.py train

# 模拟显存不足，验证优雅回滚
AC_SIMULATE_TRAIN=1 AC_SIMULATE_FAIL=oom python self_finetune.py train
# -> [系统休眠] ...
# -> [进化失败] 保持原大脑运行，绝对不死机 (显存不足)
```

## 六、产物目录

```
run_evolve/
├── sft_dataset.jsonl     # 由优质基因整理出的 SFT 数据
├── train_lora.log        # 训练日志（子进程 stdout/stderr）
├── result.json           # 训练结果协议（status / kind / adapter / error）
├── latest_adapter/       # LoRA 适配器
└── merged_hf/            # 合并后的全量权重 + GGUF + Modelfile
finetune_data.jsonl       # 优质基因池
generation.json           # 世代 / 失败免疫记忆
evolution_log.jsonl       # 每次进化尝试的审计日志
```

## 七、已知限制

- 本机无 NVIDIA GPU（torch 为 CPU 版），真实 LoRA 训练会极慢；生产建议 GPU 环境。
- Ollama 中的 `qwen3.5:0.8b` 为 Q8_0 量化的 vision 模型，而 LoRA 训练需要原始 safetensors：
  `BASE_MODEL_HF_REPO` 默认 `Qwen/Qwen3.5-0.8B-Base`，首次训练会自动下载约 1.75GB。
- GGUF 转换依赖 llama.cpp 的 `convert_hf_to_gguf.py`；找不到时给出明确错误提示，不会误改 config。

## 八、真实环境生效前的准备（重要）

本机验证结果为 **44/44 全绿**（模拟档位）。要让"真实微调 + 换脑"跑通，还需解决以下**环境**问题（代码已就绪，失败会优雅回滚）：

1. **HuggingFace 缓存目录不可写**
   现象：`PermissionError at C:\Users\David\.cache\huggingface`。
   解决：设置可写缓存目录后再训练，例如
   ```powershell
   $env:HF_HOME = "D:\hf_cache"; New-Item -ItemType Directory -Force $env:HF_HOME
   ```

2. **原始权重约 1.75GB**
   `Qwen/Qwen3.5-0.8B-Base` 首次训练需下载（Ollama 里的 qwen3.5:0.8b 是 Q8_0 量化件，不能直接用于 LoRA）。
   可用 `$env:HF_ENDPOINT="https://hf-mirror.com"` 加速。

3. **无 NVIDIA GPU**
   当前 torch 为 CPU 版（`2.13.0+cpu`）。真实 LoRA 在 CPU 上可跑但很慢；生产建议 GPU + 安装 CUDA 版 torch。

4. **GGUF 转换器**
   需要 llama.cpp 的 `convert_hf_to_gguf.py`，或设置
   `$env:AC_GGUF_CONVERTER = "D:\llama.cpp\convert_hf_to_gguf.py"`。

5. **依赖**
   本项目把 peft / accelerate 装在工作区内的 `.pydeps`（不污染全局）：
   ```powershell
   python -m pip install --target .\.pydeps --no-deps -i https://pypi.tuna.tsinghua.edu.cn/simple peft accelerate
   ```
   `main.py` / `train_lora.py` 会自动把 `.pydeps` 加入 `sys.path`。

### 一次真实进化的最短路径
```powershell
cd newlivingthings
$env:HF_HOME="D:\hf_cache"; $env:HF_ENDPOINT="https://hf-mirror.com"
$env:AC_GGUF_CONVERTER="D:\llama.cpp\convert_hf_to_gguf.py"   # 可选
# 攒满 20 条优质基因后：
python self_finetune.py train
# 成功则会：合并 LoRA -> GGUF -> ollama create entropy_evolved -> 改 config.py -> os.execv 重启
```
