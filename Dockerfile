# ============================================================
#  AC_OS / Entropy —— 容器镜像（任务三）
#
#  构建： docker build -t ac-os-entropy .
#  运行： docker compose up -d      （推荐）
#      或 docker run -d --name entropy ac-os-entropy
#
#  设计要点：
#    * 基于 python:3.11-slim，体积可控
#    * Ollama 不装进镜像（太重），通过 host.docker.internal 连宿主机
#    * 模型缓存、记忆库、进化产物全部挂载到宿主机，容器可随时重建
#    * 默认 CMD 就是 python main.py --auto（后台挂机）
# ============================================================
FROM python:3.11-slim

LABEL org.opencontainers.image.title="AC_OS Entropy"
LABEL org.opencontainers.image.description="Self-evolving digital life: endocrine + memory + auto finetune"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/data/hf_cache \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    AC_TEST_MODE=0

WORKDIR /app

# ---- 系统依赖（sentence-transformers / torch 的最小运行库）----
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---- 先装 Python 依赖（利用镜像层缓存）----
COPY newlivingthings/requirements.txt /app/newlivingthings/requirements.txt

# ---- torch（CPU 专用源）----
# 踩坑记录：
#   1) 清华/阿里 PyPI 的 torch 是 CUDA 版，会拖入 nvidia-cudnn 等 3GB+ 依赖（镜像 10.2GB）
#   2) 阿里云 pytorch-wheels/cpu 目录里没有 +cpu 后缀的 wheel
#   3) 真正的 CPU wheel 只有官方索引有：torch-2.9.1+cpu-...whl
#      直接 GET 该文件是 403，必须走 pip 索引协议
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ARG TORCH_CPU_INDEX=https://download.pytorch.org/whl/cpu
ARG PIP_TIMEOUT=600
ENV PIP_DEFAULT_TIMEOUT=${PIP_TIMEOUT}

RUN pip install --upgrade pip -i ${PIP_INDEX}

RUN pip install --index-url ${TORCH_CPU_INDEX} torch && \
    python -c "import torch; print('[torch]', torch.__version__, 'cuda:', torch.cuda.is_available()); assert not torch.cuda.is_available(), 'expected CPU build'"

# 基础依赖：去掉 torch 后再装（torch 已按 CPU 版装好）
# 用"已装版本"生成约束文件锁死 torch，防止 sentence-transformers 等传递依赖
# 把 torch 升级/替换成 CUDA 版（会多出数 GB）
RUN TORCH_PIN=$(python -c "import torch;print('torch=='+torch.__version__)") && \
    echo "$TORCH_PIN" > /tmp/constraints.txt && \
    echo "[pin] $TORCH_PIN" && \
    grep -viE '^[[:space:]]*torch([[:space:]]|$)' /app/newlivingthings/requirements.txt \
      > /tmp/req.txt && \
    pip install -r /tmp/req.txt -c /tmp/constraints.txt -i ${PIP_INDEX} && \
    python -c "import torch; assert not torch.cuda.is_available(); print('[torch-kept]', torch.__version__)"

# 微调依赖（peft / accelerate）；失败不影响主程序启动
RUN pip install --no-deps psutil peft accelerate -i ${PIP_INDEX} \
        || echo "WARN: finetune deps skipped, self-finetune disabled"

# 最终校验：镜像里必须是 CPU 版 torch
RUN python -c "import torch; print('[final]', torch.__version__, 'cuda:', torch.cuda.is_available())"

# ---- 拷贝源码 ----
COPY . /app/

# 容器启动引导：把持久卷接进工作目录后再启动主程序
RUN chmod +x /app/docker-entrypoint.sh 2>/dev/null || true

# ---- 运行数据目录（会被 docker-compose 挂载覆盖）----
RUN mkdir -p /data/hf_cache /app/newlivingthings/run_evolve /app/logs

# 健康检查：能 import 主程序模块即视为健康
HEALTHCHECK --interval=60s --timeout=15s --start-period=90s --retries=3 \
    CMD cd /app/newlivingthings && python -c "import config, main" || exit 1

WORKDIR /app/newlivingthings

ENTRYPOINT ["/app/docker-entrypoint.sh"]

# 默认：后台挂机自动进化
CMD ["python", "main.py", "--auto"]