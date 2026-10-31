# 模型权重许可证说明

本仓库的**源代码**（Python、Shell、Dockerfile 等）统一采用 **Apache License 2.0**，
详见根目录 [LICENSE](LICENSE)。

而由本项目生成或微调的**大语言模型权重文件**，采用
**Creative Commons Attribution 4.0 International (CC BY 4.0)** 许可证。

## 适用范围

CC BY 4.0 覆盖以下产物：

- `newlivingthings/run_evolve/` 下由 `train_lora.py` 生成的 LoRA 适配器
  （含 `adapter_model.safetensors`、`latest_adapter/` 等）
- `export_evolved_model.py` 导出的合并权重
- `.gguf` 格式的量化模型文件
- 任何经 `merge_export.py` 合并后的模型产物

## 你可以自由地

1. 共享、复制和重新分发这些权重文件（任何媒介、任何目的）；
2. 改编、微调、再训练这些权重。

## 前提条件

你必须：

1. 给出适当署名，标明原作者 **DavidDengll / AC OS**，并附上仓库链接
   <https://github.com/DavidDengll/AC_OS>；
2. 提供 CC BY 4.0 许可证链接 <https://creativecommons.org/licenses/by/4.0/>；
3. **说明是否做出了修改**（例如：是否经过再微调、是否量化、是否合并）。

## 关于基础模型

熵灵本身不发布基础模型。`config.py` 中的 `BASE_MODEL_NAME` 指向你自行选择的外部模型
（例如 `qwen3.5:0.8b`）。这些**基础模型有各自的许可证**，CC BY 4.0
仅适用于本仓库产出的微调产物，不能替代、也不能改变基础模型的授权条款。

使用前请自行确认所接入基础模型的许可要求。
