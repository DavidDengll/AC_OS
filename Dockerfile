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
# 关键坑位记录：
#   1) download.pytorch.org 在国内实测会卡死在 196MB 下载
#   2) 清华/阿里 PyPI 镜像上的 torch 是 CUDA 版，会拖入 nvidia-cudnn 等 3GB+ 依赖
#   3) 这里用阿里云 pytorch-wheels/cpu：国内 CDN + 纯 CPU 版
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ARG TORCH_CPU_INDEX=https://mirrors.aliyun.com/pytorch-wheels/cpu/
ARG PIP_TIMEOUT=300
ARG TORCH_VER=2.9.1%2Bcpu
ENV PIP_DEFAULT_TIMEOUT=${PIP_TIMEOUT}

RUN pip install --upgrade pip -i ${PIP_INDEX} && \
    pip install --index-url ${TORCH_CPU_INDEX} --extra-index-url ${PIP_INDEX} \
        "torch==${TORCH_VER}" && \
    python -c "import torch; print('[torch]', torch.__version__, 'cuda:', torch.cuda.is_available()); assert not torch.cuda.is_available(), 'expected CPU build'"

# 基础依赖：去掉 torch 后再装（torch 已按 CPU 版装好）
# --no-deps 会被 pip 忽略于 requirements 模式，因此改用约束文件锁死 torch 版本，
# 防止 sentence-transformers 之类的传递依赖把 torch 升级回 CUDA 版（会多出数 GB）
RUN printf "torch==${TORCH_VER}\n" > /tmp/constraints.txt && \
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
