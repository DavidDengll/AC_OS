#!/usr/bin/env bash
# docker-entrypoint.sh —— 容器启动引导（任务三）
#
# 容器内的工作目录是 /app/newlivingthings，而记忆库/情绪状态需要持久化到 /data/state。
# 这里先用"软链接"把持久目录接进工作目录，再启动主程序。
set -e

WORKDIR_APP="/app/newlivingthings"
STATE_DIR="/data/state"

mkdir -p "$STATE_DIR" "$WORKDIR_APP/run_evolve" /data/hf_cache

# 把易失的状态文件软链到持久卷（已存在实体文件时先迁移过去）
for f in entropy_memory.db emotion_state.json finetune_data.jsonl generation.json evolution_log.jsonl; do
    target="$STATE_DIR/$f"
    link="$WORKDIR_APP/$f"
    if [ -f "$link" ] && [ ! -L "$link" ]; then
        if [ ! -e "$target" ]; then
            mv "$link" "$target" 2>/dev/null || true
        else
            rm -f "$link" || true
        fi
    fi
    [ -f "$target" ] || : > "$target"
    ln -sfn "$target" "$link" 2>/dev/null || true
done

# 进化产物目录（LoRA / 合并权重 / 代码备份）
ln -sfn "/app/newlivingthings/run_evolve" "/data/run_evolve" 2>/dev/null || true

cd "$WORKDIR_APP"
exec "$@"
