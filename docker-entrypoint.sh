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
    # V6.5：清理 SQLite 侧写文件。
    # 启用 WAL 后，数据可能在 entropy_memory.db-wal / -shm 里；
    # 单独覆盖主文件而不清理这些侧写文件，会让数据库读到不匹配的旧 WAL。
    case "$f" in
        *.db) rm -f "$dst-wal" "$dst-shm" "$dst-journal" 2>/dev/null || true ;;
    esac
    if [ -f "$src" ] && [ -s "$src" ]; then
        cp -f "$src" "$dst" 2>/dev/null && \
            echo "[entrypoint] 已从持久卷恢复 $f ($(wc -c < "$src" | tr -d ' ') bytes)" || true
    fi
    [ -f "$dst" ] || : > "$dst" 2>/dev/null || true
done

# 后台定时把工作目录的状态回写到持久卷（每 60 秒一次，退出时再写一次）
#
# V6.5 重要：SQLite 库不能直接 cp 主文件。
# WAL 模式下未 checkpoint 的数据全在 entropy_memory.db-wal 里，
# 只复制主文件会得到「没有表」的残缺副本
# （实测：shutil.copyfile 副本 SELECT 直接报 no such table），
# 且 cp 覆盖的瞬间进程若正好在读库，会报 unable to open database file。
# 因此 .db 一律用 SQLite 官方 VACUUM INTO 做一致性快照，其它文件才用 cp。
sync_db() {
    src="$APP/$1"
    dst="$STATE/$1"
    [ -f "$src" ] || return 0
    python - "$src" "$dst" <<'PY' 2>/dev/null || cp -f "$src" "$dst" 2>/dev/null || true
import sqlite3, os, sys
src, dst = sys.argv[1], sys.argv[2]
tmp = dst + ".tmp"
for p in (tmp, tmp + "-wal", tmp + "-shm"):
    try: os.remove(p)
    except OSError: pass
c = sqlite3.connect(src, timeout=15)
c.execute("VACUUM INTO ?", (tmp,))
c.close()
os.replace(tmp, dst)
PY
}

sync_state() {
    for f in entropy_memory.db emotion_state.json finetune_data.jsonl generation.json evolution_log.jsonl; do
        if [ -f "$APP/$f" ] && [ ! -L "$APP/$f" ]; then
            case "$f" in
                *.db) sync_db "$f" ;;
                *)    cp -f "$APP/$f" "$STATE/$f" 2>/dev/null || true ;;
            esac
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
