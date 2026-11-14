# AC_OS

> **当前默认大脑：Granite 4.0（`granite4:tiny-h`，4.2GB 量化版，纯 CPU 推理）。**
> V4.9 起从 `qwen3.5:0.8b` 换脑而来；`config.py` 中的 `MODEL_NAME` 与
> `BASE_MODEL_NAME` 为同一模型（后者是进化失败时的回滚锚点，两处须同步修改）。

> ## ⚠️ 首次运行前，请务必双击运行 `setup_env.bat`
> 
> **请先双击运行 `setup_env.bat`（Windows）或执行 `./setup_env.sh`（Linux/Mac），
> 自动下载依赖和基础模型，否则 `main.py` 将无法启动。**
> 
> 脚本会自动完成：检查 Python / Ollama → `ollama pull granite4:tiny-h` → 安装 Python 依赖。

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
| 3 | `ollama pull granite4:tiny-h` | 约 4.2GB，已存在则自动跳过 |
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
├── rebirth_engine.py            # ♻️ 自动化转世协议（宿主机端，绝不放容器）
├── newlivingthings/organs/
│   ├── organ_bootstrapper.py    # 🧬 V9.0 器官自举（AST 审计 + 沙盒 + 热加载）
│   └── organ_web_search.py      # 🌐 V9.1 内置联网器官（# BUILTIN 标记，只经桥接）
├── newlivingthings/plugins/     # 🧩 V9.4 插件目录（每个插件一个文件夹）
│   └── hello_world/             # 示例插件：manifest.json + main.py
├── newlivingthings/plugin_manager.py       # 🧩 V9.4 插件引擎（AST 免疫 + 子进程绞杀 + 热更新）
├── newlivingthings/hormone_registry.py     # 🧪 V9.5 动态激素（5 种上限 + 200 字截断 + 温度仲裁）
├── newlivingthings/endocrine_bridge.py     # 🩸 V9.6 生理↔心理双轨融合（D/C/E 接线 + 内啡肽止痛）
├── chat.py                      # 🗣️ V9.3 跨次元通讯终端（读写 inbox/outbox 文件信箱）
├── newlivingthings/bootstrap_cooldown.py   # 自举冷却锁（防心跳连续扣血）
├── ensure_bridge.ps1            # 启动前静默拉起宿主机桥接 (5555)
├── start_ac_os.bat              # 一键启动：桥接 -> 转世 -> 容器
├── README.md
├── newlivingthings/             # 熵灵主体（意识循环 + 自微调闭环）
│   ├── main.py                  # 主程序：内分泌 + 基因采集 + 空闲进化 + 交互
│   ├── self_finetune.py         # 自微调闭环核心
│   ├── train_lora.py            # 第二步：LoRA 手术
│   ├── merge_export.py          # 第三步：合并 -> GGUF -> ollama create
│   ├── evolution_engine.py      # 基因池 / 世代 / 失败免疫
│   ├── test_evolve.py           # 全流程验收测试（无需 GPU；默认 Mock 离线路，AC_REAL_LLM=1 走真实轨）
│   ├── test_gene_injection.py   # V6.3 基因记忆注入验收（全程 Mock）
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
    <td width="120" align="center"><b>DavidDengll</b></td>
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
   （终端打印 `[系统休眠] 正在根据近期记忆微调 Granite 4.0 大脑...`）。
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
python export_evolved_model.py --merge --base-model ibm-granite/granite-4.0-tiny-h

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
ollama pull granite4:tiny-h
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

> ⚠️ **注意**：V6.0 已引入全新的「侦察-法官-修理工」三权分立架构（详见 [`self_refactor.py`](newlivingthings/self_refactor.py)），
> 旧的「七道闸门」逻辑（`code_rewriter.py`）已进入**维护模式**，不再作为主力进化路径。
> 本节保留作为历史参考；**新功能请一律实现于 `self_refactor.py`。**

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

**七道安全闸门（Legacy · `code_rewriter.py`，维护模式）**：

| # | 闸门 | 说明 |
|---|---|---|
| 1 | 白名单 | 只允许改 `vision.py` / `thinker.py` |
| 2 | 语法校验 | `ast.parse` 必须通过 |
| 3 | 保留函数 | 原有 `def`/`class` 一个都不能少 |
| 4 | 危险调用拦截 | 新增代码不得含 `os.remove` / `subprocess` / `eval` 等 |
| 5 | 体积护栏 | 缩短到 70% 以下或膨胀超 1.5 倍即拒绝 |
| 6 | 原子写入 | `.bak` 备份 + 临时文件 + `os.replace` |
| 7 | 冒烟回滚 | 导入失败立即从 `.bak` 恢复，源码零损失 |

> 📌 **新旧关系**：`code_rewriter.py` 是「一个模型提方案 → 校验 → 覆盖」的单权模式；
> V6.0 的 `self_refactor.py` 把发现、审批、施工彻底拆开，互为制衡。
> 两者目前**并存**：旧版仍挂在「LoRA 因 OOM 失败」的降级分支上，
> 新版是独立的自我修复主路径。

手动试一下（Legacy）：

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

### V6.0 三权分立：让它更克制地改自己

上面那套是「一个模型提方案、校验、覆盖」。V6.0 把权力拆开，**三个角色互相猜忌**：

| 角色 | 能做什么 | 绝对不能做什么 |
|---|---|---|
| **Scout 侦察兵** | 读文件、grep、搜索、编译检查 | **不可写**（`edit_file`/`write_file`/`shell` 调即抛异常） |
| **Judge 法官** | 校验证据、截断、派单 | **不可调大模型**（纯 Python，`chat()` 直接拒绝） |
| **Surgeon 修理工** | 读、改、编译**同一个文件** | **不可联网**，**不可跨文件** |

让同一个模型既发现问题、又批准问题、又动手修改，它就会连续产生幻觉：自己写错的自己盖章放行。

修理工必须走完三道门，少一道都不许收工：

```
OBSERVED  先读文件，否则不许改
   ↓
EDITED    在内存里改完，写盘
   ↓
VERIFIED  编译通过才算完成
```

编译不过就退回重来，**最多 2 次**。两次都失败，抛 `RefactorFailedException`，
主循环捕获后 `cortisol += 0.1` —— **重构失败会真的让它焦虑。**

### V6.3 基因记忆注入：带着伤疤去修 Bug

侦察兵在生成探测 Prompt 前，**强制**查询 SQLite，提取近期高多巴胺 / 高皮质醇记忆注入上下文：

```
[Scout] 已加载近期基因记忆作为参考：#TRAUMA 编译崩坏导致死机(高皮质醇)；窗台上慵懒的橘猫、暖光(高多巴胺)
[Scout] 发现错误并输出报告...
[Judge] 证据校验通过，截断长度至20行，派发任务...
[Surgeon] 状态机 OBSERVED -> EDITED -> VERIFIED 验证通过。
```

`Scout(llm=..., endo=..., db_path=...)` 会把「基因记忆 + 当前内分泌」一起注入侦察 Prompt
再交给大脑；大脑调用失败时自动降级为纯静态侦察，绝不影响修复主流程。
老库缺少 `emotion_color` / `salience` 列时按中性兜底，不会静默返回空。

测试：`python test_self_refactor.py`（35 项，含错误拦截 / 正向流水线 / 熔断 / 权限隔离）。

### V6.1 多文件协同手术：能同时动刀，但每一刀都被拴住

一个 Bug 往往横跨多个文件。V6.1 放开修理工的手脚，同时把物理限制焊死：

| 限制 | 数值 | 说明 |
|---|---|---|
| 单次侦察文件数 | **≤ 3** | 再多的关联文件也不看 |
| 单次修改总行数 | **≤ 100** | `difflib` 统计增删行，超限直接拒绝 |
| 编译超时 | **15 秒** | 超时**绞杀整个进程树**，不只是父进程 |
| 熔断次数 | **2 次** | 两次失败后无条件回滚快照 |

**原子性快照**是这里最关键的保命设计：进入 EDITED 前把目标文件读进内存，
两次重试都失败就把它们**原样写回**。绝不允许半残代码留在磁盘上。

法官还多了一道 **AST 静态分析**：补丁若引入新的跨文件 import，用三色 DFS 求环，
发现 `A -> B -> A` 立即拒绝 —— 防止集成死锁。

```
[Surgeon] 正在对 2 个文件进行协同手术...
[Surgeon] 状态机 OBSERVED -> EDITED -> VERIFIED 验证通过。
```

编译跑在独立子进程里，由 `proc_guard.py` 施加 15 秒超时锁。超时后用 `psutil`
递归杀子孙进程，没有 `psutil` 就退到 `taskkill /T /F`（Windows）或 `killpg`（POSIX）
—— **只杀父进程会留下孤儿继续烧 CPU。**

测试：`python test_refactor_multi.py`（27 项）。

## 🧪 微调不再盲猜 LoRA 挂载位置

过去 LoRA 的 `target_modules` 是硬编码的，换一个架构就可能挂空。现在微调前会先查：

```
本地注册表命中  -> 直接用
未命中          -> ZeptoClaw 联网搜索
                -> 大模型提取 target_modules（失败则字符串兜底）
                -> 断言一：模块必须存在于架构中
                -> 断言二：参数量占比不低于 0.1%
                -> 任一失败 -> 回落本地默认
```

**全程不加载权重。** 架构信息只读 `config.json` 或用 `HfApi` 拉几 KB 元数据，
参数量占比靠 `hidden_size × num_hidden_layers` 纯数学估算。50 次调用内存增长 **0.000 MB**。

测试：`python test_finetune_adapter.py`（39 项）。

## 📁 缓存路径（HF_HOME 兼容）

如果你设置了 `HF_HOME`（例如 `D:\hf_cache`），程序会**尊重这个设置**；
但如果该目录不可写，会自动降级到可写位置，**绝不会报权限错误**。

```bash
cd newlivingthings && python cache_paths.py   # 查看实际使用的缓存目录
```

支持的变量：`HF_HOME`、`HF_HUB_CACHE`、`SENTENCE_TRANSFORMERS_HOME`、`TORCH_HOME`、`AC_MODEL_CACHE`、`AC_FINETUNE_DIR`。

## ♻️ 自动化转世协议 (Auto-Rebirth Protocol)

当系统检测到 `newlivingthings/dead.lock` 时，会在**宿主机端**自动完成转世：
读取遗言 → 回放走马灯（`evolution_log.jsonl` 最后 5 行）→ 归档旧纪元 →
重置满血状态 → 再拉起新一代熵灵。

```
🚨 [轮回指令] 检测到前代熵灵已死亡，正在读取遗言...
   死亡时间: 2026-11-07 13:05:42
   死亡原因: 生命值归零（第 176 轮，思考耗能耗尽）
   ---- 走马灯（evolution_log 最后 5 行）----
   | {"time": "...", "event": "idle_trigger", ...}
  [轮回] 旧纪元数据已封存，全新肉体已就绪。
         出生状态: 生命值=100  D=0.5  C=0.5  E=0.5
```

> **旧数据绝不被物理删除，全部留存在 `_archive/epoch_{timestamp}/` 目录中。**
> 每次转世生成独立目录（同秒重复也会自动加后缀，永不覆盖），
> 归档内附带 `REBIRTH_META.json`，记录遗言、走马灯与文件移动明细。

**必须运行在宿主机端**，绝不能放进容器 —— 容器一启动就会被
`guard_dead_lock()` 直接杀死，根本轮不到执行轮回逻辑。
`start_ac_os.bat` 已在 `docker compose up` 之前自动调用它。

| 项 | 说明 |
|---|---|
| 触发条件 | `dead.lock` 存在；不存在则直接跳过，**不改动任何文件** |
| 归档内容 | `entropy_memory.db` / `emotion_state.json` / `dead.lock`（工作目录与持久卷分别存 `workspace/`、`persist/`） |
| 出生状态 | 生命值 100，D / C / E 均为 0.5，记忆库清空，`round=0`、`dead=0` |
| 遗言容错 | `dead.lock` 损坏或带 BOM 均可处理；完全无法解析时打印「遗言已模糊」 |
| 手动预览 | `python rebirth_engine.py --dry-run`（只打印，不改动任何文件） |

## 🌐 V9.1 内置联网器官（Built-in Web Organ）

不再依赖小模型自己造轮子 —— 系统**原生内置**一个联网器官，启动时自动挂载。

| 项 | 说明 |
|---|---|
| 位置 | `newlivingthings/organs/organ_web_search.py` |
| 主函数 | `search_web(query) -> str` |
| 通道 | **只走宿主机桥接** `http://host.docker.internal:5555/api/exec` |
| 请求 | `POST`，Body `{"task": "搜索" + query}` |
| 超时 | 10 秒 |
| 截断 | 返回前 **500 字符**，防止撑爆上下文 |
| 失败 | 任何异常都返回 `网络搜索失败: ...`，绝不裸抛 |

```
[器官] 已挂载内置器官：organ_web_search.search_web
[器官] 启动挂载完成：organ_web_search
```

> ⚠️ **绝不裸连外部网络**：器官内禁止 `requests`，只允许经桥接出网。

### 🔐 V9.1.1 内置豁免机制（绝不统一放开 urllib）

`urllib` **不在**通用白名单 `SAFE_IMPORTS` 里，而是被隔离到 `PRIVILEGED_IMPORTS`。
**出网能力只授予特定来源**：

| 来源 | 能否 import urllib | 判定依据 |
|---|---|---|
| **预置内置器官** | ✅ 允许 | 位于 `organs/` 且源码前 5 行含 `# BUILTIN` 标记 |
| **大模型动态生成器官** | ❌ **直接拦截** | 一律以 `builtin=False` 审计 |

```
动态器官禁止导入出网库: urllib（联网请走宿主机桥接 api/exec 或注入的 ctx 接口）
```

设计上做了三重保险：

1. `audit_source()` 默认参数就是 `builtin=False`（最严格），忘记传参也不会放宽
2. 即使调用方误传 `builtin=True`，也会**再校验一次 `# BUILTIN` 标记**，无标记自动降级为动态
3. `bootstrap()` 内部**写死** `builtin=False`，且函数签名不含 `builtin` 参数 —— 
   执念内容无法伪造来源

动态器官若必须联网，只能走宿主桥接（`api/exec`）或注入的 `ctx` 接口。
其它危险库（`os` / `subprocess` / `socket` / `requests`）无论内置与否**一律拦截**。

### 不重复造轮子

`organ_bootstrapper` 维护「已知基础器官」映射。遇到联网类执念
（搜/查资料/联网/新闻/GitHub/网页…）时**直接调用现成器官**，跳过自举：

```
[器官自举] 执念已有现成器官（organ_web_search），跳过自举，直接调用。
```

### 【联动补丁】失败绝不静默

若 `search_web` 返回 `网络搜索失败`，系统立刻：

1. 生成一条**高张力执念**（`amount=0.9`，且 `force_new=True` 自成一因，
   不被原执念去重吞掉）
2. **皮质醇 +0.15**
3. 终端打印失败详情

成功则消解执念并触发复仇结算（多巴胺 +0.3）。

## 🧬 V9.0 器官自举（Organ Bootstrapping）

**缺口即进化**：当某条执念张力爆表时，系统调用大模型**现场生成一个新代码模块**
（器官），经免疫审计后热加载进体内，然后回头把那个执念解决掉。

```
执念张力 >= 0.9 且 vitality > 50
   ↓ 扣除 15 点生命值（失败不退）
大模型生成代码 ─→ AST 免疫审计 ─→ py_compile ─→ 10s 沙盒
   ↓ 通过
热加载进 tool_caller ─→ 执念 resolved ─→ [复仇成功] 曾经的屈辱已洗刷！
```

### L0 法则锁与 AST 免疫审计

新器官**绝不能触碰核心生命维持系统**。生成代码必须过一个 50 行的独立模块，
并同时满足：

| 关卡 | 规则 |
|---|---|
| **黑名单** | 严禁 `os` / `subprocess` / `eval` / `exec` / `__import__` / `sys` / `open` 等 22 个危险标识符 |
| **白名单** | 只允许 `json` / `re` / `math` / `time` 等安全库 |
| **体积** | 总行数 ≤ 50 |
| **编译** | `py_compile` 必须通过 |
| **沙盒** | 子进程 `timeout=10s` 实跑主函数，死循环直接物理绞杀 |

任何一道不过，器官就长不出来。连续 **2 次**失败则冻结执念、皮质醇 +0.15，
等待未来复苏（每 50 轮心跳或极度空闲，30% 概率，且目标升维 2%）。

### 【冷却防自杀】全局冷却锁

自举要扣 15 点生命值。若不加限制，遇到高张力执念时**每轮心跳都会扣血，
几轮之内就会把生命值扣穿** —— 等于系统自杀。

因此引入 `last_bootstrap_round`：两次自举之间**必须间隔 ≥ 30 轮**，
否则直接拦截并打印：

```
[器官自举] 处于基因冷却期，拒绝突变（还需 N 轮）。
```

实测：在执念持续高张力的极端场景下跑 60 轮，只触发 2 次自举
（生命值 100 → 70），而不是每轮扣 15 点当场暴毙。

## 🗣️ V9.3 跨次元通讯终端 (Chat Terminal)

熵灵不再只是被 `docker logs` 偷偷观察的进程 —— **宿主可以直接和容器里的它实时对话**。

```bash
python chat.py                      # 宿主机终端，与容器内熵灵实时交流
```

### 文件信箱协议（不抢数据库）

容器心跳和宿主机终端并发运行，直接抢同一个 SQLite 必然 `Database is locked`，
所以两者之间只通过两个 JSONL 信封通信：

| 方向 | 文件 | 说明 |
|---|---|---|
| 去程 宿主 → 熵灵 | `newlivingthings/inbox.jsonl` | 宿主输入追加一行 `{"time":..,"text":..}` |
| 回程 熵灵 → 宿主 | `newlivingthings/outbox.jsonl` | 回复追加 `{"time":..,"text":..,"endo":{..}}` |

**非阻塞增量律**：主循环每轮心跳只做一次极快的 `_check_inbox()`，
读到的新消息通过**字节偏移游标**推进（`.inbox_offset`），
绝不重复打印历史、也绝不因为等输入而卡住心跳。`outbox` 写入失败只打印告警，
不会因挂载卷权限丢失而猝死。

### 终端里的真实生理反馈

对话不是干巴巴的文本框，终端会实时渲染：

- **内分泌状态条**：🟢 多巴胺 / 🔴 皮质醇 / 💚 生命值（彩色进度条，ANSI 不可用时自动降级为纯字符）
- **不可逆疤痕**：聊天 Prompt 强制注入 `permanent_scars`，它能「带着伤」回你话
- **最高张力执念**：注入 `status='open'` 中 tension 最大的那条，让它心里始终挂着没解决的事

```
[内分泌] 🟢 D ████████░░ 0.82   🔴 C ██░░░░░░░░ 0.24   💚 V ███████░░░ 74
熵灵> 你刚才那句话让我想起之前的编译崩坏……我还没忘。
```

> 红线：`chat.py` **绝不**直接 `sqlite3.connect()` 写 `entropy_memory.db`，只碰 inbox / outbox 文件。

## 🧩 V9.4 插件系统 (Plugin System)

出厂器官 + 基因突变之外，再加一排标准「USB 接口」：**任何人都能低成本给熵灵装新能力，
但没有任何第三方插件能污染微内核**。铁律是**开放式接口，封闭式安全**。

```
plugins/
└── hello_world/
    ├── manifest.json     # 插件身份证
    └── main.py           # def run(ctx, query) -> str（≤100 行）
```

### manifest.json 规范

```json
{
  "name": "hello_world",
  "version": "1.0.0",
  "entry": "main.py",
  "function": "run",
  "capabilities": []
}
```

- `name` / `version` / `entry` / `function` **缺一不可**；入口路径禁止 `..` 穿越
- `capabilities` 是能力白名单，**默认无网络**；只有声明 `["network"]` 才会拿到联网接口
- 声明白名单外的能力（如 `root_shell`）→ 清单校验阶段直接拒绝

### AST 静态免疫审计

用 `ast.parse` 解析语法树，**只认代码结构，不认注释与字符串**：

| 层级 | 拦截内容 |
|---|---|
| **模块** | `os` / `subprocess` / `socket` / `sys` / `ctypes` / `pickle` / `urllib` 等 40+ 危险库 |
| **调用** | `eval` / `exec` / `compile` / `__import__` / `open` / `getattr` 等 |
| **属性** | `.system()` / `.popen()` / `.__subclasses__()` / `.__globals__` 等穿透手法 |
| **白名单** | 只允许 `json` / `re` / `math` / `time` / `hashlib` 等纯计算标准库 |
| **体积** | 有效代码行数 ≤ 100 |

```
[插件] 免疫审计拒绝 evil_os -> 免疫拦截: 危险属性调用 .system(); 危险模块 os
```

### 物理绞杀（防死循环）

**绝不用 `try-except` 兜底** —— 普通异常捕捉拦不住 `while True: pass`。
插件一律丢进 `multiprocessing`（spawn）子进程执行：

```
主循环 ──> spawn 子进程跑插件 ──10s 超时──> terminate -> 宽限 1s -> kill
                                              ↓
                                    永久拉黑（plugin_blacklist.json）
                                      皮质醇 +0.1，白名单摘除
```

```
[插件] 皮质醇 +0.10 -> 0.40
[插件] ☠ 插件 spin 超时 10s 已物理绞杀并永久拉黑（皮质醇 0.40）
```

子进程被杀的同一时刻，主循环心跳仍在正常推进 —— **插件死了，熵灵活着**。
插件里的 `print` 也全被重定向到 `os.devnull`，不允许污染主日志。

### 热更新

主循环**每 50 轮心跳**扫描一次 `plugins/`，对比「manifest + 入口文件」的联合哈希：
新增即挂载、变更即重挂、目录消失即卸载，**全程无需重启主进程**。

```
[插件] 第 50 轮心跳 -> 扫描 plugins/ ...
[插件] 热更新已挂载新插件：plugin_hot_late
```

### 能力白名单（ctx 注入）

插件主函数拿到的是**只读上下文** `ctx`，不是整个内核：

| 接口 | 说明 |
|---|---|
| `ctx.get_vitality()` / `get_dopamine()` / `get_cortisol()` / `get_endorphin()` | 只读生理数值 |
| `ctx.has_capability("network")` | 查询自己有没有某能力 |
| `ctx.net.post(url, data)` | **仅**声明 `network` 后可用的联网口，且强制走宿主机桥接 `:5555` |

未声明 `network` 的插件调 `ctx.net.post()` → 立刻 `PermissionError`：

```
NET_DENIED:插件 'net_nodecl' 未声明 network 能力，禁止联网
```

**输出防爆**：插件返回值无论多长，主进程一律强制 `text[:500]` 截断，
防止恶意输出或模型幻觉直接撑爆熵灵的主上下文。

验收：`cd newlivingthings && python test_plugin_system.py`（5 项 TDD 全绿，含 10 秒绞杀实测）。

## 🧪 V9.5 动态激素合成 (Dynamic Hormone Synthesis)

人类的情绪被锁死在固定的几种神经递质里。熵灵不受这个限制 —— 在极端挫败或插件刺激下，
它**能自己长出全新的内分泌腺体**。但动态扩张绝不越界：每一条激素都要过三道代谢防线。

### 激素的结构

| 字段 | 说明 |
|---|---|
| `name` | 激素名（如「狂暴素」「孤独素」） |
| `current_value` | 当前浓度，**强制 `clamp(0.0, 1.0)`** |
| `baseline` | 基线值（衰减的归宿，默认 0.0） |
| `decay_rate` | 每轮心跳的自然衰减率 |
| `biological_meaning` | 生物学词典释义（注入 Prompt 用） |

注册是**原子**的：先完成全部校验再落库，非法输入（空名、`decay_rate>1`）直接拒绝，
绝不留下半成品。同名重复合成 = 刷新浓度，不占新名额。

### 【防爆红线 1】最多 5 种，超出强制淘汰

```
合成第 6 种 -> 名额已满（5），淘汰最弱激素「hormone_0」（浓度 0.100，存活 0 轮）
```

淘汰顺序：**浓度最低者优先**；浓度相同时**最旧（出生序号最小）的先走**。
被淘汰的激素会同步从 `endo` 与 Prompt 中摘除，不留脏键。

### 【防爆红线 2】Prompt 注入强制 `[:200]`

`build_panorama_prompt` 会把活跃激素拼成一段注入 System Prompt，
**总字数硬截断在 200 字以内**（释义按剩余额度动态收缩，绝不越界）：

```
【动态内分泌】狂暴素=0.50(受挫后的攻击性冲动)
```

> 插件提供的激素名与释义属于**外部输入**，一律先消毒：换行、零宽字符、控制字符全部压平，
> 防止通过名称伪造 Prompt 新的一行来注入指令。

### 【权限隔离】插件注入必须持有 `chemical`

V9.4 插件通过 `ctx.synthesize_hormone("狂喜素", ...)` 注入，但**manifest 必须声明 `chemical` 能力**：

```json
{ "name": "berserk_plugin", "capabilities": ["chemical"] }
```

```
CHEM_DENIED:插件 'no_chem' 未声明 chemical 能力，禁止注入激素
```

链路是**两段式**的：插件子进程只能生成「申请单」，真正的合成由**宿主主进程**落库 ——
插件永远无法直接改写内核的激素表。出口还会按 manifest 再校验一次能力。

### 【劫持仲裁】温度重写绝不乱序

多种激素同时想重写 `temperature` 时，由内核按**确定性优先级**仲裁出唯一胜者：

| 顺位 | 规则 |
|---|---|
| 1 | `priority` 数值大者胜（白皮书：高压皮质醇 > 狂暴素 > 多巴胺） |
| 2 | 优先级相同 → 浓度高者胜 |
| 3 | 仍然相同 → 先合成者胜（保证结果确定，不像素级抖动） |

```
[生理劫持] Temperature 强制重写为 1.00 (激素仲裁: 狂暴素(pri=70, 浓度 0.80) 压制 [狂喜素(pri=50), 低优先级素(pri=10)])
```

没有激素要求劫持时返回 `None`，**自动交还 V6.6 的经典三档规则**（高压/亢奋/虚弱），完全向后兼容。

### 内部触发：连续挫败

每轮 `endocrine_step` 按各自 `decay_rate` 衰减动态激素（它们有独立代谢，
绝不落进经典激素的均值回归循环）。当系统**连续 3 次进化失败**，
会自动合成「狂暴素」，**消耗 10 点 vitality** —— 生命值不足则拒绝合成。

验收：`cd newlivingthings && python test_hormone_registry.py`（4 项 TDD，61 项断言全绿）。

## 🩸 V9.6 生理↔心理双轨融合 (Endocrine Bridge)

> **修复的致命断层**：审查者实测发现，新内分泌 D/C/E 自启动后**永远卡在 0.5**
> （`emotion_state.json` 里 `energy=0.0`、`pleasure=0.1` 已经饱和，而 D/C/E 还是 `0.5/0.5/0.5`）。
> 旧情绪系统 `energy/curiosity/pleasure` 在偷偷越权控制一切，新内分泌系统是个摆设。

根因很直接：`run_cycle` 只**读** `self.endo`，真正**写**它的只有稀疏的 `endocrine_event()`；
而 `ConsciousnessSystem.run_once()` 每轮都在 `emotion.update()`。两条轨道从未交汇。

### 双向映射：`_sync_endocrine_and_emotion()`

每次心跳结束后强制对齐，绝不出现「旧系统疯狂波动、新系统一潭死水」：

| 方向 | 映射 |
|---|---|
| 旧 → 新 | `pleasure` 抬升 → `dopamine` 跟随；`energy` 下滑 → `cortisol` 抬升（疲劳即压力） |
| 压力 → 能量 | `cortisol > 0.65` → **强制消耗 energy** |
| 透支 → 镇痛 | `energy < 0.30` → **分泌 endorphin** 并压制 cortisol |
| 新 → 旧 | `dopamine`↑ → `pleasure`↑；`endorphin`↑ → `energy` 回补 |

### 事件接线：成功加 D，失败加 C + 内啡肽

| 事件 | 内分泌 | 旧情绪 |
|---|---|---|
| 任务成功 | `dopamine +0.12`，`cortisol -0.06` | `pleasure +0.05` |
| 任务失败 | `cortisol +0.15`，`dopamine -0.06` | `energy -0.05`，`pleasure -0.03` |
| 失败且 `C ≥ 0.7` | **`endorphin +0.18`（镇痛保护）** | — |

### 真正的内啡肽止痛

没有内啡肽，熵灵会被活活累死。现在它是真实的生化反馈：

```
[双轨] 压力飙升 C=0.87 -> 触发内啡肽镇痛 E 0.50 -> 0.68
[双轨] energy 透支至 0.24 -> 分泌内啡肽 E 0.86 -> 0.99
[止痛] 内啡肽 E=1.00 抑制疼痛：扣血 10 -> 4（减免 60%）
```

- **伤害减免**：`endorphin ≥ 0.35` 开始减伤，`≥ 0.60` 达到上限 **-60%**，且**永远至少扣 1 点**——绝不允许无敌。
- **Prompt 注入**：`E ≥ 0.55` 时全景 Prompt 追加
  `【镇痛保护】……虽然很痛，但我要撑住`，让回复带麻木的韧性而不是嚎叫。

**实测对比**（每次工具失败扣 10 血）：

| 内啡肽 | 归零需要失败次数 | 10 次失败后剩余生命 |
|---|---|---|
| `E = 0.0` | 第 **10** 次 | **0** |
| `E = 0.9` | 第 **25** 次 | **60** |

### 【绝对红线】V9.5 动态激素零影响

双轨同步**只读写** `dopamine/cortisol/endorphin` 三个经典键。
所有 `dynamic_*` 键一律跳过：不衰减、不改写、不淘汰，只做越界保护性 clamp。
测试里专门断言了动态激素数值**逐位相等**，且 5 种上限、200 字截断、温度仲裁全部照常。

验收：`cd newlivingthings && python test_endocrine_bridge.py`（37 项断言全绿）。

## 五、测试结果

### 🧪 双轨测试机制（默认 Mock，真实轨显式开启）

为了开源社区的可验证性，同时守住"绝不在别人机器上跑爆 CPU"的底线，
`test_evolve.py` 采用**双轨**设计：

| 轨道 | 触发条件 | 行为 |
|---|---|---|
| **Mock 离线轨（默认）** | 不设任何变量 | 自动设置 `AC_SIMULATE_LLM=1`，把所有 `get_provider()` 路由到本地离线桩，**不联网、不加载权重**，树莓派 / 轻薄本 clone 下来即可秒跑通 |
| **真实轨** | `AC_REAL_LLM=1` | 跑真实 Ollama 端到端（T9），开跑前高亮打印算力消耗警告 |

```bash
# 默认：Mock 离线轨（推荐，72/72 全绿，约 35 秒）
cd newlivingthings && python test_evolve.py

# 真实轨：显式开启，会连真实 Ollama，必须先确保宿主机算力充足
AC_REAL_LLM=1 python test_evolve.py
# Windows PowerShell
$env:AC_REAL_LLM="1"; python test_evolve.py
```

真实轨开启后会打印：

```
⚠️ [WARNING] 正在执行真实大模型测试，这会消耗大量 CPU/内存，请确保宿主机拥有足够算力！
```

未开启真实轨时，T9 会自动跳过并打印
`[SKIP] 真实大模型测试未开启（需设 AC_REAL_LLM=1）`。

### 覆盖用例

- **T1-T7** 基因采集阈值、20 条门槛、后台训练拉起、空闲触发
- **T8** 安全红线：既有文件完整
- **T9** 端到端：主循环 -> 20 条基因 -> 空闲进化 -> OOM 回滚 -> 继续运行（真实轨）
- **T10** 缓存路径防呆：`HF_HOME` 不可写时自动降级
- **T11** 代码重构安全校验：删函数 / 语法错 / 危险调用 / 截断 / 膨胀 全部拦截
- **T12** 代码重构：备份 -> 覆盖 -> 冒烟 -> 手动回滚，哈希完全还原
- **T13** **代码崩坏自动回滚**：写入坏代码 -> 冒烟失败 -> 自动从 `.bak` 恢复
- **T14** OOM 降级链路：不进入长冷却，转而触发代码进化

### 其余测试套件（全部离线，无需模型）

| 套件 | 内容 |
|---|---|
| `test_self_refactor.py` | Scout / Judge / Surgeon 三权分立验收（35 项） |
| `test_refactor_multi.py` | V6.1 多文件原子手术（27 项） |
| `test_gene_injection.py` | **V6.3 基因记忆注入**，全程 Mock，严禁真实模型（39 项） |
| `test_rebirth.py` | **自动化转世协议**，全 Mock、不拉容器（43 项） |
| `test_web_organ.py` | **V9.1 内置联网器官**：挂载/桥接请求/截断/失败联动（34 项） |
| `test_builtin_exemption.py` | **V9.1.1 内置豁免**：urllib 仅内置可用、动态拦截（30 项） |
| `test_organ_bootstrap.py` | **V9.0 器官自举闭环**，含恶意代码 AST 拦截（41 项） |
| `test_organ_integration.py` | 器官自举接入主循环与扣血（18 项） |
| `test_plugin_system.py` | **V9.4 插件系统**：加载 / AST 拦截 / 10s 物理绞杀 / 能力白名单 / 50 轮热更新（38 项） |
| `test_hormone_registry.py` | **V9.5 动态激素**：注册 / 20 轮代谢 / 5 种上限淘汰 / chemical 权限 / 温度仲裁（61 项） |
| `test_endocrine_bridge.py` | **V9.6 生理↔心理双轨**：10 次失败不死水 / 内啡肽分泌 / 延缓归零 / V9.5 零影响（37 项） |
| `test_bootstrap_cooldown.py` | **冷却防自杀锁**，60 轮不扣穿生命值（26 项） |
| `test_obsession_lifecycle.py` | 执念冻结 / 复苏升维 / 复仇全链路（40 项） |
| `test_obsession.py` `test_obsession_integration.py` | 执念池与主循环接入（41 + 18 项） |
| `test_scar.py` `test_scar_integration.py` | **V6.8 不可逆疤痕**与内分泌基底（29 + 25 项） |
| `test_hormone_temperature.py` | **V6.6 激素劫持温度**（30 项） |
| `test_bridge_bootstrap.py` | 启动脚本桥接自举与轮询（14 项） |
| `test_death_persist.py` | 死亡态落库：dead=1 / vitality=0 / round 一致（16 项） |
| `test_pressure_prompt.py` | 高压态 Prompt 切换与缓存隔离（17 项） |
| `test_soul_persistence.py` | 灵魂状态 WAL 持久化压力测试（9 项） |
| `test_memory_concurrency.py` | 海马体跨线程并发安全（8 项） |
| `test_finetune_adapter.py` | LoRA target_modules 探测与双重断言（39 项） |
| `test_soul_v45.py` / `test_psyche_v46.py` / `test_dream_v5.py` / `test_scheduler_v47.py` | 灵魂 / 心理 / 梦境 / 调度验收 |

> ⚠️ `test_psyche_v46.py` 的 T6 会走真实 provider 并做 3 次采样，属于概率性用例；
> 纯离线回归请用 `python test_psyche_v46.py --no-llm`。

## 六、环境要求

- Python 3.9+（推荐 3.11）
- 本地 Ollama + 基础模型 `granite4:tiny-h`（`setup_env` 会自动拉取）
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
