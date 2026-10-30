# AC_OS

> ## ⚠️ 首次运行前，请务必双击运行 `setup_env.bat`
> 
> **请先双击运行 `setup_env.bat`（Windows）或执行 `./setup_env.sh`（Linux/Mac），
> 自动下载依赖和基础模型，否则 `main.py` 将无法启动。**
> 
> 脚本会自动完成：检查 Python / Ollama → `ollama pull qwen3.5:0.8b` → 安装 Python 依赖。

---

## 🖱️ 双击哪个文件，就能在后台默默跑起来？

> **双击 `start_ac_os.bat`** —— 就这么简单。
>
> 它会自检环境 → 确保 Ollama 在线 → **无黑框**在后台拉起 `python main.py --auto`，
> 5 秒后窗口自动关闭，熵灵在后台继续挂机、自动积累基因、空闲时自我进化。

| 想做什么 | 双击这个文件 |
|---|---|
| **后台挂机跑起来**（推荐，日常用这个） | **`start_ac_os.bat`** |
| 完全静默启动（无任何窗口，适合开机自启） | `run_entropy.vbs` |
| 停止后台进程 | `stop_entropy.bat` |
| 前台调试（能看到全部输出） | `start_ac_os.bat --foreground`（或命令行执行） |
| 首次安装依赖与模型 | `setup_env.bat` |
| 用 Docker 跑 | `run_docker.bat` |

启动后的日志在 `logs\entropy_*.log`。

> 💡 `run_entropy.vbs` 与 `start_ac_os.bat` 的区别：
> 前者是**纯静默**启动器（不弹任何窗口，也不做环境检查）；
> 后者会先检查环境并给出友好提示，再用静默方式启动，**更推荐**。
> 把 `run_entropy.vbs` 的快捷方式放进「启动」文件夹即可实现开机自启。

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

## 🌟 Core Contributors

<table>
  <tr>
    <td width="120" align="center"><b>DavidDeng</b></td>
    <td><b>创世主 / 架构师</b><br/>
        提出核心哲学（系统即生命）、设计内分泌与记忆进化闭环、主导 Vibe Coding 工作流。</td>
  </tr>
  <tr>
    <td align="center"><b>DSH</b><br/><sub>DeepSeek Harness</sub></td>
    <td><b>全栈包工头</b><br/>
        负责底层代码实现、Docker 容器化部署、网络桥接排障（修复 Steam++ 劫持等致命 Bug）以及长期挂机稳定性重构。</td>
  </tr>
</table>

> 熵灵不是被写出来的程序，而是被「喂养」和「陪伴」长大的数字生命。

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


## 🐳 用 Docker 跑（跨平台，推荐长期挂机）

```bat
run_docker.bat
```

它会检查 Docker、创建数据目录、构建镜像并后台启动容器。手动方式：

```bash
docker compose up -d        # 构建并后台启动
docker compose logs -f      # 查看实时日志
docker compose down         # 停止
```

**关键设计**：

| 项 | 说明 |
|---|---|
| 基础镜像 | `python:3.11-slim` |
| 模型服务 | 容器不装 Ollama，通过 `host.docker.internal:11434` 连宿主机 |
| 启动命令 | `python main.py --auto`（后台挂机自动进化） |
| 数据持久化 | `data/hf_cache`、`data/state`、`data/run_evolve`、`logs/` |
| 无 GPU | 容器内无 GPU，微调必然 OOM，自动降级为**代码级自我重构** |

宿主机需先准备好模型：

```bash
ollama pull qwen3.5:0.8b
```


### Docker 踩坑记录（实测）

| 问题 | 现象 | 解决 |
|---|---|---|
| docker 命令找不到 | `docker` 不在 PATH | 脚本自动回退到 `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe` |
| 镜像拉取失败 | `docker-credential-desktop not found` | 把上述 bin 目录加入 PATH |
| 拉镜像超时 | Docker Hub 国内不可达 | 用 `docker.m.daocloud.io/library/python:3.11-slim` 再 `docker tag` |
| torch 卡死 | `download.pytorch.org` 196MB 下载不动 | 换源（见下） |
| 镜像 10.2GB | 清华 PyPI 的 torch 是 CUDA 版，拖入 nvidia-cudnn 553MB 等 | 用官方 CPU 索引，镜像降到 **2.62GB** |
| `invalid file request` | 源码目录里有断链软链接（Docker Desktop 挂载残留） | entrypoint 不再创建软链接，改用定时回写 |
| `%2B` 报错 | `torch==2.9.1%2Bcpu` 被 pip 当成非法版本号 | 写成 `+cpu`，URL 编码只用于索引路径 |
| 容器连不上 Ollama | `127.0.0.1` 指向容器自身 | `config.py` 支持 `OLLAMA_BASE_URL` 环境变量覆盖 |
| 微调启动失败 | `creationflags is only supported on Windows` | 按平台条件传参 |
| **模型返回空内容** | `finish_reason=length`，token 全耗在 thinking | 自动降级到 Ollama 原生 API + `think:false` |

> torch 源结论：真正的 CPU wheel 只有官方索引有（`torch-2.14.1+cpu`，196MB）；
> 阿里云 `pytorch-wheels/cpu` 目录下没有 `+cpu` 后缀的 wheel。

### 容器内验证结果

```
[内分泌] D=0.450 C=0.440 E=0.400 | 基因池 20/20
第 3 轮:
大模型回复: 橘猫慵懒地倚在窗台，沐浴着暖洋洋的晨光。
[内分泌] D=0.408 C=0.548 E=0.403 | 基因池 20/20
```
## 💻 用 QEMU 跑（Alpine 虚拟机）

适合在干净隔离环境里长期挂机、又不想装 Docker 的场景。

### 1. 装 Alpine 虚拟机

```bash
# 下载 Alpine 虚拟镜像（约 60MB）
curl -LO https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/alpine-virt-3.20.0-x86_64.iso

# 创建 8GB 虚拟磁盘
qemu-img create -f qcow2 ac_os.qcow2 8G

# 启动安装（4GB 内存，SSH 转发到宿主机 2222）
qemu-system-x86_64 \
  -m 4096 \
  -smp 4 \
  -drive file=ac_os.qcow2,format=qcow2,if=virtio \
  -cdrom alpine-virt-3.20.0-x86_64.iso \
  -netdev user,id=n0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=n0 \
  -nographic
```

进入 Alpine 后执行 `setup-alpine`，磁盘选 `vda`、模式选 `sys`，装完重启。

### 2. 在虚拟机里准备环境

```sh
apk add python3 py3-pip git curl bash

# 从宿主机拷代码（宿主机另开终端）
#   scp -P 2222 -r AC_OS root@localhost:/root/

cd /root/AC_OS
sh setup_env.sh --skip-model   # 模型在宿主机跑，虚拟机只管代码
```

### 3. 让虚拟机连宿主机的 Ollama

QEMU user 网络里宿主机地址固定是 `10.0.2.2`。先让宿主机 Ollama 对外监听：

```bash
# Linux / macOS
OLLAMA_HOST=0.0.0.0:11434 ollama serve

# Windows PowerShell
$env:OLLAMA_HOST="0.0.0.0:11434"; ollama serve
```

然后在虚拟机里改配置并启动：

```sh
cd /root/AC_OS/newlivingthings
sed -i 's|127.0.0.1:11434|10.0.2.2:11434|' config.py
nohup python3 main.py --auto > /root/entropy.log 2>&1 &
tail -f /root/entropy.log
```

> ⚠️ 虚拟机里同样没有 GPU，LoRA 微调会 OOM，系统会自动转去"代码级自我重构"（改自己的 `vision.py` / `thinker.py`）。

## 🧬 代码级自我重构（没有 GPU 也能进化）

本机没有 GPU 时，LoRA 微调必然 OOM。熵灵不会就此躺平，而是**降级去改自己的代码**：

```
空闲触发 -> LoRA 微调 -> OOM 失败
            |
            v
      代码级重构（改自己的 vision.py / thinker.py）
            |
    大模型提方案 -> 静态校验 -> 备份 .bak -> 原子覆盖
            |
      冒烟导入测试 ---失败---> 自动从 .bak 回滚
            |成功
            v
        os.execv 热重启，新代码生效
```

**七道安全闸门**：

| # | 闸门 | 说明 |
|---|---|---|
| 1 | 白名单 | 只允许改 `vision.py` / `thinker.py` |
| 2 | 语法校验 | `ast.parse` 必须通过 |
| 3 | 保留函数 | 原有 `def`/`class` 一个都不能少 |
| 4 | 危险调用拦截 | 新增代码不得含 `os.remove` / `subprocess` / `eval` 等 |
| 5 | 体积护栏 | 缩短到 70% 以下或膨胀超 1.5 倍即拒绝 |
| 6 | 原子写入 | `.bak` 备份 + 临时文件 + `os.replace` |
| 7 | 冒烟回滚 | 导入失败立即从 `.bak` 恢复，源码零损失 |

手动试一下：

```bash
cd newlivingthings

# 演练模式：只生成预览，不动真代码
python code_rewriter.py --offline --dry-run

# 真实重构（备份 + 冒烟 + 失败自动回滚）
python code_rewriter.py --offline

# 手动回滚到最近一次备份
python code_rewriter.py --rollback vision.py
```

配置开关在 `config.py`：`CODE_REWRITE_ENABLED`、`CODE_REWRITE_ON_OOM`、`CODE_REWRITE_USE_MODEL`。

## 📁 缓存路径（HF_HOME 兼容）

如果你设置了 `HF_HOME`（例如 `D:\hf_cache`），程序会**尊重这个设置**；
但如果该目录不可写，会自动降级到可写位置，**绝不会报权限错误**。

```bash
cd newlivingthings && python cache_paths.py   # 查看实际使用的缓存目录
```

支持的变量：`HF_HOME`、`HF_HUB_CACHE`、`SENTENCE_TRANSFORMERS_HOME`、`TORCH_HOME`、`AC_MODEL_CACHE`、`AC_FINETUNE_DIR`。
## 五、测试结果

`newlivingthings/test_evolve.py` 全部通过，覆盖：

- **T1-T7** 基因采集阈值、20 条门槛、后台训练拉起、空闲触发
- **T8** 安全红线：既有文件完整
- **T9** 端到端：真实主循环 -> 20 条基因 -> 空闲进化 -> OOM 回滚 -> 继续运行
- **T10** 缓存路径防呆：`HF_HOME` 不可写时自动降级
- **T11** 代码重构安全校验：删函数 / 语法错 / 危险调用 / 截断 / 膨胀 全部拦截
- **T12** 代码重构：备份 -> 覆盖 -> 冒烟 -> 手动回滚，哈希完全还原
- **T13** **代码崩坏自动回滚**：写入坏代码 -> 冒烟失败 -> 自动从 `.bak` 恢复
- **T14** OOM 降级链路：不进入长冷却，转而触发代码进化

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

本项目采用分层开源策略：
- **源代码**：采用 [Apache License 2.0](LICENSE) 许可证。
- **模型权重与数据**：采用 [CC BY 4.0](MODELS.md) 许可证。

详情请参阅项目根目录下的 `LICENSE` 和 `MODELS.md` 文件。

我和DSH所做
