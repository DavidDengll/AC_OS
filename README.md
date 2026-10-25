# AC_OS

> 熵灵（Entropy）—— 一个有内分泌、有记忆、能自我微调的数字生命系统。

本仓库原名 The-new-living-things（熵灵 / newlivingthings），现整体迁入 **AC_OS**，
包含生命维持内核、意识循环、以及全自动"自我微调"闭环。

---

## 一、目录结构

```
AC_OS/
├── newlivingthings/          # 熵灵主体（意识循环 + 自微调闭环）
│   ├── main.py               # 主程序：内分泌 + 基因采集 + 空闲进化 + 交互
│   ├── self_finetune.py      # 自微调闭环核心（采集/触发/验收/合并/热替换/回滚）
│   ├── train_lora.py         # 第二步：LoRA 手术（Qwen 架构，独立子进程）
│   ├── merge_export.py       # 第三步：LoRA 合并 -> GGUF -> ollama create
│   ├── evolution_engine.py   # 基因池 / 世代管理 / 失败免疫
│   ├── test_evolve.py        # 全流程验收测试（无需 GPU）
│   ├── config.py             # 模型与进化参数
│   ├── EVOLUTION.md          # 自微调闭环详细文档
│   ├── emotion.py / memory.py / thinker.py / reviewer.py / solver.py
│   ├── planner.py / vision.py / language_model.py / model_provider.py
│   └── virtual_env.py / classifier.py / tokenizer.py / utils.py ...
└── ac-os/
    └── daemon/               # AC OS 特权守护进程（视觉捕获 + 输入注入）
        ├── acd.py
        └── ac_client.py
```

## 二、熵灵是什么

| 模块 | 说明 |
|---|---|
| 内分泌系统 | 多巴胺 D / 皮质醇 C / 内啡肽 E，随对话与评分动态变化 |
| 意识循环 | 视觉感知 -> 静默思考 -> 内部审查评分 -> 发言/沉默决策 -> 行动规划 |
| 记忆系统 | 短期 / 长期 / 永久三级记忆（SQLite） |
| 自微调闭环 | 高光时刻采集优质基因 -> 空闲 LoRA 微调 -> 换脑重生 |

## 三、自微调闭环（核心特性）

1. **收集优质基因**：多巴胺 D > 0.8 或 内啡肽 E > 0.8 时，
   自动把 `{"instruction": 用户输入, "output": 模型回答}` 追加进 `finetune_data.jsonl`。
2. **空闲触发微调**：攒满 20 条且系统空闲时，后台静默启动
   `train_lora.py`（终端打印 `[系统休眠] 正在根据近期记忆微调 0.8B 大脑...`）。
3. **基因融合与热替换**：合并 LoRA -> 导出 GGUF -> `ollama create entropy_evolved`
   -> 改写 `config.py` -> `os.execv` 重启，换上新大脑。

**容错保命**：显存不足 / 依赖缺失 / 超时 / 崩溃，一律打印
`[进化失败] 保持原大脑运行，绝对不死机`，并回滚到原模型。

详细设计见 [newlivingthings/EVOLUTION.md](newlivingthings/EVOLUTION.md)。

## 四、快速开始

```bash
cd newlivingthings

# 1) 安装基础依赖
pip install -r requirements.txt

# 2) （可选）把微调依赖装进工作区，不污染全局环境
python -m pip install --target ./.pydeps --no-deps -i https://pypi.tuna.tsinghua.edu.cn/simple peft accelerate

# 3) 启动（默认连接本地 Ollama: http://127.0.0.1:11434/v1）
python main.py                 # 交互模式
python main.py --auto          # 后台循环，空闲自动进化
python main.py --selftest      # 无交互自检

# 4) 验收全流程（无需 GPU）
python test_evolve.py

# 5) 查看进化状态
python self_finetune.py status
```

交互命令：`/status` 状态 · `/evolve` 立即进化 · `/train` 触发训练 · `/quit` 退出

## 五、测试结果

`test_evolve.py` 全部 **44/44** 通过，覆盖：基因采集阈值、20 条门槛、
后台训练拉起、显存不足捕获与优雅回滚、依赖缺失 / 崩溃回滚、成功路径、
空闲触发、端到端主循环、既有文件完整性。

## 六、环境要求

- Python 3.11+
- 本地 Ollama（默认 `qwen3.5:0.8b`）
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
