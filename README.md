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
│   └── organ_web_search.py      # 🌐 V9.1 内置联网器官（只经宿主机桥接）
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
> 这也是 `urllib` 被加入审计白名单的**唯一**理由。

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
| `test_web_organ.py` | **V9.1 内置联网器官**：挂载/桥接请求/截断/失败联动（32 项） |
| `test_organ_bootstrap.py` | **V9.0 器官自举闭环**，含恶意代码 AST 拦截（41 项） |
| `test_organ_integration.py` | 器官自举接入主循环与扣血（18 项） |
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
