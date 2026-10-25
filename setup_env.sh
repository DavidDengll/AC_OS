#!/usr/bin/env bash
# ============================================================
#  AC_OS 一键初始化脚本（Linux / macOS）
#
#  用法:
#    ./setup_env.sh                完整安装（检查 + 拉模型 + 装依赖）
#    ./setup_env.sh --check-only   只检查，不下载任何东西
#    ./setup_env.sh --skip-model   跳过 ollama pull
#    ./setup_env.sh --skip-deps    跳过 pip 安装
#    ./setup_env.sh -h             帮助
# ============================================================

set -uo pipefail

MODEL="qwen3.5:0.8b"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPS_DIR="$ROOT/newlivingthings/.pydeps"
REQ_FILE="$ROOT/newlivingthings/requirements.txt"
OLLAMA_URL="http://127.0.0.1:11434/api/tags"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"

CHECK_ONLY=0
SKIP_MODEL=0
SKIP_DEPS=0
FAIL=0
PY_CMD=""

usage() {
  cat <<'EOF'

  AC_OS 一键初始化
    ./setup_env.sh               完整安装（检查 + 拉模型 + 装依赖）
    ./setup_env.sh --check-only  只检查，不下载任何东西
    ./setup_env.sh --skip-model  跳过 ollama pull
    ./setup_env.sh --skip-deps   跳过 pip 安装
EOF
}

for arg in "$@"; do
  case "$arg" in
    --check-only|--check)
      CHECK_ONLY=1
      ;;
    --skip-model)
      SKIP_MODEL=1
      ;;
    --skip-deps)
      SKIP_DEPS=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
  esac
done

# ---------- 颜色 ----------
if [ -t 1 ]; then
  C_OK="\033[32m"
  C_ERR="\033[31m"
  C_WARN="\033[33m"
  C_END="\033[0m"
else
  C_OK=""
  C_ERR=""
  C_WARN=""
  C_END=""
fi

ok()   { printf "        ${C_OK}[OK]${C_END} %s\n" "$*"; }
err()  { printf "        ${C_ERR}[错误]${C_END} %s\n" "$*"; }
warn() { printf "        ${C_WARN}[警告]${C_END} %s\n" "$*"; }
info() { printf "        %s\n" "$*"; }

echo
echo "  ============================================================"
echo "              AC_OS  环境一键初始化   ($(uname -s))"
echo "  ============================================================"
if [ "$CHECK_ONLY" = "1" ]; then
  echo "   模式: 仅检查（不会下载任何东西）"
fi
echo

# ------------------------------------------------------------
# 1. Python
# ------------------------------------------------------------
echo "  [1/3] 检查 Python ..."
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)' >/dev/null 2>&1; then
      PY_CMD="$c"
      break
    fi
  fi
done

if [ -n "$PY_CMD" ]; then
  ok "找到 $("$PY_CMD" --version 2>&1) ( $PY_CMD )"
elif command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
  err "Python 版本过低，需要 3.9 或更高版本。"
  FAIL=1
else
  err "未检测到 Python。"
  info "macOS : brew install python@3.11"
  info "Ubuntu: sudo apt install python3 python3-pip python3-venv"
  info "或访问 https://www.python.org/downloads/"
  FAIL=1
fi

# ------------------------------------------------------------
# 2. Ollama + 基础模型
# ------------------------------------------------------------
echo
echo "  [2/3] 检查 Ollama ..."

api_up() {
  if [ -n "$PY_CMD" ]; then
    "$PY_CMD" -c "import urllib.request,sys; urllib.request.urlopen('$OLLAMA_URL',timeout=3); sys.exit(0)" >/dev/null 2>&1
  elif command -v curl >/dev/null 2>&1; then
    curl -sf --max-time 3 "$OLLAMA_URL" >/dev/null 2>&1
  else
    return 1
  fi
}

if ! command -v ollama >/dev/null 2>&1; then
  err "未检测到 Ollama。"
  info "macOS : 下载 https://ollama.com/download/Ollama-darwin.zip"
  info "Linux : curl -fsSL https://ollama.com/install.sh | sh"
  info "安装完成后重新运行本脚本。"
  FAIL=1
else
  ok "找到 $(ollama --version 2>&1 | head -1)"
  info "路径: $(command -v ollama)"
  echo

  if api_up; then
    ok "Ollama 服务在线 (127.0.0.1:11434)"
  else
    info "服务未运行，尝试启动 ollama serve ..."
    nohup ollama serve >/dev/null 2>&1 &
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
      sleep 1
      if api_up; then
        break
      fi
    done
    if api_up; then
      ok "Ollama 服务已启动"
    else
      warn "服务未能自动启动，请手动运行: ollama serve"
    fi
  fi

  if ollama list 2>/dev/null | grep -qi "$MODEL"; then
    ok "基础模型 $MODEL 已就绪，跳过下载。"
  elif [ "$SKIP_MODEL" = "1" ]; then
    info "[跳过] 未下载模型 $MODEL （--skip-model）"
  elif [ "$CHECK_ONLY" = "1" ]; then
    info "[缺失] 未找到模型 $MODEL ，正式运行时会自动下载。"
  else
    info "正在下载基础模型 $MODEL （约 1.3GB，请耐心等待） ..."
    echo "        --------------------------------------------"
    if ollama pull "$MODEL"; then
      echo "        --------------------------------------------"
      ok "模型下载完成。"
    else
      echo "        --------------------------------------------"
      err "模型下载失败，请检查网络后重试。"
      FAIL=1
    fi
  fi
fi

# ------------------------------------------------------------
# 3. Python 依赖
# ------------------------------------------------------------
echo
echo "  [3/3] 安装 Python 依赖 ..."

if [ ! -f "$REQ_FILE" ]; then
  err "找不到依赖清单: $REQ_FILE"
  FAIL=1
elif [ -z "$PY_CMD" ]; then
  warn "Python 不可用，跳过依赖安装。"
elif [ "$SKIP_DEPS" = "1" ]; then
  info "[跳过] 依赖安装 （--skip-deps）"
elif [ "$CHECK_ONLY" = "1" ]; then
  MISSING=""
  for p in openai jieba ddgs gymnasium numpy sentence_transformers; do
    "$PY_CMD" -c "import $p" >/dev/null 2>&1 || MISSING="$MISSING $p"
  done
  if [ -n "$MISSING" ]; then
    info "[缺失] 以下依赖未安装:$MISSING"
    info "正式运行时会自动安装。"
  else
    ok "全部基础依赖已安装。"
  fi
else
  info "安装基础依赖 ..."
  if "$PY_CMD" -m pip install -r "$REQ_FILE" --disable-pip-version-check >/dev/null 2>&1; then
    ok "基础依赖安装完成。"
  else
    warn "直连 PyPI 失败，改用国内镜像 ..."
    if "$PY_CMD" -m pip install -r "$REQ_FILE" --disable-pip-version-check -i "$MIRROR"; then
      ok "基础依赖安装完成（镜像）。"
    else
      err "基础依赖安装失败。"
      FAIL=1
    fi
  fi

  echo
  info "安装微调依赖到项目内 .pydeps （不污染全局环境） ..."
  if "$PY_CMD" -m pip install --target "$DEPS_DIR" --no-deps psutil peft accelerate --disable-pip-version-check -i "$MIRROR" >/dev/null 2>&1; then
    ok "微调依赖安装完成。"
  else
    warn "微调依赖安装失败。这不影响主程序运行，只影响空闲自我微调功能。"
  fi
fi

# ------------------------------------------------------------
echo
echo "  ============================================================"
if [ "$FAIL" = "0" ]; then
  echo "    [完成] 环境检查/安装完毕，可以启动熵灵了！"
  echo
  echo "    启动命令:"
  echo "        cd newlivingthings"
  echo "        python3 main.py"
else
  echo "    [注意] 存在问题，请根据上方提示处理后再启动 main.py。"
fi
echo "  ============================================================"
echo

exit "$FAIL"
