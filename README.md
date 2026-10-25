# AC_OS

> ## ⚠️ 首次运行前，请务必双击运行 `setup_env.bat`
> 
> **请先双击运行 `setup_env.bat`（Windows）或执行 `./setup_env.sh`（Linux/Mac），
> 自动下载依赖和基础模型，否则 `main.py` 将无法启动。**
> 
> 脚本会自动完成：检查 Python / Ollama → `ollama pull qwen3.5:0.8b` → 安装 Python 依赖。

---

> 熵灵 (Entropy) —— 一个有内分泌、有记忆、能自我微调的数字生命系统。

本仓库原名 The-new-living-things（熵灵 / newlivingthings），现整体迁入 **AC_OS**，
包含生命维持内核、意识循环、以及全自动"自我微调"闭环。

## 🚀 第一步：一键初始化环境（必须）

### Windows

```bat
setup_env.bat
```
> 在资源管理器里直接**双击 `setup_env.bat`** 也可以。

### Linux / macOS

```bash
chmod +x setup_env.sh
./setup_env.sh
```

### 脚本会做什么

| 步骤 | 内容 | 说明 |
|---|---|---|
| 1 | 检查 Python | 需要 3.9+，未安装会给出官网链接 |
| 2 | 检查 Ollama | 未安装会给出下载地址；未运行会自动 `ollama serve` |
| 3 | `ollama pull qwen3.5:0.8b` | 约 1.3GB，已存在则自动跳过 |
| 4 | 安装 `requirements.txt` | 失败时自动提示国内镜像 |
| 5 | 安装微调依赖到 `.pydeps` | 不污染全局环境，失败不影响主程序 |

### 可选参数

| 参数 | 作用 |
|---|---|
| `--check-only` | 只检查不下载，适合排查问题 |
| `--skip-model` | 跳过模型下载 |
| `--skip-deps` | 跳过依赖安装 |
| `-h` / `--help` | 帮助 |

## ▶️ 第二步：启动熵灵

```bash
cd newlivingthings
python main.py                 # 交互模式
python main.py --auto          # 后台循环，空闲自动进化
python main.py --selftest      # 无交互自检
```

交互命令：`/status` 状态 · `/evolve` 立即进化 · `/train` 触发训练 · `/quit` 退出

---

## 一、目录结构

```
AC_OS/
├── setup_env.bat                # Windows 一键初始化
├── setup_env.sh                 # Linux / macOS 一键初始化
├── export_evolved_model.py      # 导出进化模型（供网盘分享）
├── README.md
├── newlivingthings/             # 熵灵主体（意识循环 + 自微调闭环）
│   ├── main.py                  # 主程序：内分泌 + 基因采集 + 空闲进化 + 交互
│   ├── self_finetune.py         # 自微调闭环核心
│   ├── train_lora.py            # 第二步：LoRA 手术
│   ├── merge_export.py          # 第三步：合并 -> GGUF -> ollama create
│   ├── evolution_engine.py      # 基因池 / 世代 / 失败免疫
│   ├── test_evolve.py           # 全流程验收测试（无需 GPU）
│   ├── config.py                # 模型与进化参数
│   ├── EVOLUTION.md             # 自微调闭环详细文档
│   └── emotion.py / memory.py / thinker.py / reviewer.py / solver.py ...
└── ac-os/
    └── daemon/                  # AC OS 特权守护进程
```

## 二、熵灵是什么

| 模块 | 说明 |
|---|---|
| 内分泌系统 | 多巴胺 D / 皮质醇 C / 内啡肽 E，随对话与评分动态变化 |
| 意识循环 | 视觉感知 -> 静默思考 -> 内部审查评分 -> 发言/沉默决策 -> 行动规划 |
| 记忆系统 | 短期 / 长期 / 永久三级记忆（SQLite） |
| 自微调闭环 | 高光时刻采集优质基因 -> 空闲 LoRA 微调 -> 换脑重生 |

## 三、自微调闭环

1. **收集优质基因**：多巴胺 D > 0.8 或 内啡肽 E > 0.8 时，自动把
   `{"instruction": 用户输入, "output": 模型回答}` 追加进 `finetune_data.jsonl`。
2. **空闲触发微调**：攒满 20 条且系统空闲时，后台静默启动 `train_lora.py`
   （终端打印 `[系统休眠] 正在根据近期记忆微调 0.8B 大脑...`）。
3. **基因融合与热替换**：合并 LoRA -> 导出 GGUF -> `ollama create entropy_evolved`
   -> 改写 `config.py` -> `os.execv` 重启，换上新大脑。

**容错保命**：显存不足 / 依赖缺失 / 超时 / 崩溃，一律打印
`[进化失败] 保持原大脑运行，绝对不死机`，并回滚到原模型。

详细设计见 [newlivingthings/EVOLUTION.md](newlivingthings/EVOLUTION.md)。

## 四、进化模型怎么分享（重要）

微调产物动辄几十 MB 到数 GB，**绝对不能直接 push 进主仓库**。

### 规则

| 内容 | 位置 |
|---|---|
| LoRA 适配器 / GGUF / 合并权重 | ❌ 不进仓库（已写入 `.gitignore`） |
| `MODELS.md`（下载说明 + 网盘链接） | ✅ 可以提交 |

### 导出流程

```bash
# 1) 只打包 LoRA（最小，通常几十 MB）
python export_evolved_model.py

# 2) 合并出完整权重再打包
python export_evolved_model.py --merge --base-model Qwen/Qwen3.5-0.8B-Base

# 3) 顺便转成 GGUF（需要 llama.cpp 的转换脚本）
python export_evolved_model.py --merge --gguf --converter D:\\llama.cpp\\convert_hf_to_gguf.py

# 4) 只想检查适配器，不生成文件
python export_evolved_model.py --dry-run
```

产物会写到 `export_pkg/`（已被 git 忽略），并自动生成：

- `entropy_evolved_lora_YYYYMMDD.zip` —— LoRA 包
- `MODELS.md` —— 含文件大小与 SHA256 的下载说明模板

### 上传步骤

1. 把 zip / gguf **手动上传到网盘**（百度网盘 / 阿里云盘 / 夸克等）
2. 把链接填进 `export_pkg/MODELS.md` 的表格
3. 只提交这份说明，大文件保持忽略：

```bash
cp export_pkg/MODELS.md MODELS.md
git add MODELS.md
git commit -m "docs: 添加进化模型下载说明"

# 提交前确认看不到大文件
git status --short          # 不应出现 .zip / .gguf / .safetensors
```

### 使用下载到的模型

```bash
# 校验完整性
sha256sum entropy_evolved_lora_20261025.zip

# 解压 LoRA 到训练产物目录
unzip entropy_evolved_lora_20261025.zip -d newlivingthings/run_evolve/

# 或直接把 GGUF 导入 Ollama
ollama create entropy_evolved -f ./Modelfile
```

## 五、测试结果

`newlivingthings/test_evolve.py` 全部 **44/44** 通过，覆盖：基因采集阈值、20 条门槛、
后台训练拉起、显存不足捕获与优雅回滚、依赖缺失 / 崩溃回滚、成功路径、空闲触发、
端到端主循环、既有文件完整性。

```bash
cd newlivingthings && python test_evolve.py
```

## 六、环境要求

- Python 3.9+（推荐 3.11）
- 本地 Ollama + 基础模型 `qwen3.5:0.8b`（`setup_env` 会自动拉取）
- 可选：NVIDIA GPU（真实 LoRA 训练需要；CPU 也能跑，速度较慢）
- 可选：llama.cpp 的 `convert_hf_to_gguf.py`（用于 GGUF 导出）

## 七、AC OS Daemon（可选）

`ac-os/daemon` 是 Linux/X11 环境下的特权守护进程，提供屏幕捕获与输入注入：

```bash
pip install mss python-xlib pillow
sudo python3 ac-os/daemon/acd.py     # 启动 daemon
python3 ac-os/daemon/ac_client.py    # 测试客户端
```

## License

详见 [newlivingthings/LICENSE](newlivingthings/LICENSE)。
