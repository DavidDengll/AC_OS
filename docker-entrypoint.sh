#!/usr/bin/env bash
# docker-entrypoint.sh —— 容器启动引导
#
# 背景：容器内工作目录 /app/newlivingthings 是挂载进来的 Windows 目录。
# Docker Desktop 在 Windows 挂载卷上无法创建 Linux 软链接（会生成断链的 reparse point，
# 反过来导致下次 docker build 报 "invalid file request"）。
# 因此这里改用"真实文件 + 定时回写"的方式，不再创建任何符号链接。
set -e

APP="/app/newlivingthings"
STATE="/data/state"

mkdir -p "$STATE" "$APP/run_evolve" /data/hf_cache 2>/dev/null || true

# 把持久卷里的历史状态"拷回"工作目录（只在新容器启动时做一次）
for f in entropy_memory.db emotion_state.json finetune_data.jsonl generation.json evolution_log.jsonl; do
    src="$STATE/$f"
    dst="$APP/$f"
    # 如果工作目录里是坏链接/空文件，先清掉
    if [ -L "$dst" ] || [ ! -e "$dst" ]; then
        rm -f "$dst" 2>/dev/null || true
    fi
    if [ -f "$src" ] && [ ! -s "$dst" ]; then
        cp -f "$src" "$dst" 2>/dev/null || true
    fi
    [ -f "$dst" ] || : > "$dst" 2>/dev/null || true
done

# 后台定时把工作目录的状态回写到持久卷（每 60 秒一次，退出时再写一次）
sync_state() {
    for f in entropy_memory.db emotion_state.json finetune_data.jsonl generation.json evolution_log.jsonl; do
        if [ -f "$APP/$f" ] && [ ! -L "$APP/$f" ]; then
            cp -f "$APP/$f" "$STATE/$f" 2>/dev/null || true
        fi
    done
}

( while true; do sleep 60; sync_state; done ) &
SYNC_PID=$!

_cleanup() {
    kill "$SYNC_PID" 2>/dev/null || true
    sync_state
    exit 0
}
trap _cleanup TERM INT

cd "$APP"
exec "$@"
