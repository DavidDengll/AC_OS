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

# 把持久卷里的状态"恢复"到工作目录。
#
# 关键：工作目录是宿主机挂载，里面常常残留上一轮的旧文件。
# 若只在"目标为空"时才恢复，容器重建后就永远读旧状态 —— 所以改为：
#   以持久卷为准，持久卷有内容就覆盖工作目录（持久卷才是真相来源）。
for f in entropy_memory.db emotion_state.json finetune_data.jsonl generation.json evolution_log.jsonl; do
    src="$STATE/$f"
    dst="$APP/$f"
    # 工作目录里若是坏链接（Windows 挂载卷残留），先清掉
    if [ -L "$dst" ]; then
        rm -f "$dst" 2>/dev/null || true
    fi
    if [ -f "$src" ] && [ -s "$src" ]; then
        cp -f "$src" "$dst" 2>/dev/null && \
            echo "[entrypoint] 已从持久卷恢复 $f ($(wc -c < "$src" | tr -d ' ') bytes)" || true
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
