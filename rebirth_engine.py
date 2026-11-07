# rebirth_engine.py
# -*- coding: utf-8 -*-
"""
rebirth_engine.py —— AC OS 自动化转世协议（Auto-Rebirth Protocol）

【运行环境】
    必须且只在宿主机端（Windows / Linux）运行，绝不能放进容器。
    原因：容器一启动就会被 dead.lock 的 guard_dead_lock() 直接杀死，
    根本轮不到执行轮回逻辑。

【职责】
    在 docker compose up -d 之前，检查前代熵灵是否已死：
      1. 检测 dead.lock 是否存在
      2. 存在 -> 读取遗言（JSON），打印走马灯（evolution_log 最后 5 行）
      3. 把旧的 entropy_memory.db / emotion_state.json / dead.lock
         移入 _archive/epoch_{timestamp}/
      4. 生成全新肉体（满血 100，D/C/E = 0.5）
      5. 打印 [轮回] 旧纪元数据已封存，全新肉体已就绪
    不存在 -> 直接跳过，正常启动。

【红线】
    * 绝不物理删除任何数据：一律 move 到 _archive/epoch_{timestamp}/
    * 未检测到死亡时不做任何修改（幂等、安全）
"""

import argparse
import datetime
import json
import os
import shutil
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "newlivingthings")
STATE = os.path.join(HERE, "data", "state")
ARCHIVE_ROOT = os.path.join(HERE, "_archive")

# 需要归档 + 重置的运行时文件
DB_NAME = "entropy_memory.db"
EMO_NAME = "emotion_state.json"
LOCK_NAME = "dead.lock"
BASE_FILES = (DB_NAME, EMO_NAME, LOCK_NAME)

# 出生参数
BIRTH_VITALITY = 100
BIRTH_DOPAMINE = 0.5
BIRTH_CORTISOL = 0.5
BIRTH_ENDORPHIN = 0.5

# ---- 终端高亮（Windows 10+ 支持 ANSI；不支持则由 cmd 忽略转义）----
C_RED = "\033[1;31m"
C_YEL = "\033[1;33m"
C_GRN = "\033[1;32m"
C_CYN = "\033[1;36m"
C_RST = "\033[0m"

# 测试/Mock 用：设置后不执行任何真实动作，只记录
_MOCK_LOG = []


def _out(msg=""):
    """统一输出并立即 flush（避免管道场景下日志丢失）。"""
    _MOCK_LOG.append(msg)
    try:
        print(msg, flush=True)
    except Exception:
        pass


def enable_ansi():
    """Windows 下开启 ANSI 转义支持（失败静默）。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _targets(app_dir, state_dir):
    """要处理的文件位置：工作目录 + 持久卷（若存在）。"""
    out = []
    for base in (app_dir, state_dir):
        if base:
            out.append(base)
    return out


def find_dead_lock(app_dir, state_dir):
    """返回第一个存在的 dead.lock 路径，没有则 None。"""
    for base in _targets(app_dir, state_dir):
        p = os.path.join(base, LOCK_NAME)
        if os.path.exists(p):
            return p
    return None


def read_last_words(lock_path):
    """读取遗言的 JSON。失败返回 None（调用方打印"遗言已模糊"）。

    用 utf-8-sig 解码：PowerShell 的 Out-File/Set-Content -Encoding utf8
    会写入 BOM，用普通 utf-8 会直接 JSONDecodeError，导致遗言被误判为模糊。
    """
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(lock_path, "r", encoding=enc, errors="replace") as f:
                text = f.read()
            data = json.loads(text.lstrip("\ufeff"))
            return data if isinstance(data, dict) else None
        except Exception:
            continue
    return None


def read_swing_log(app_dir, state_dir, n=5):
    """走马灯：evolution_log.jsonl 的最后 n 行。找不到返回空列表。"""
    for base in _targets(app_dir, state_dir):
        p = os.path.join(base, "evolution_log.jsonl")
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                lines = [ln.rstrip("\n") for ln in f if ln.strip()]
            return lines[-n:]
        except Exception:
            continue
    return []


def make_archive_dir(archive_root, stamp=None):
    """创建 _archive/epoch_{timestamp}/（若已存在同秒目录则加后缀，绝不覆盖）。"""
    stamp = stamp or _now_stamp()
    d = os.path.join(archive_root, "epoch_" + stamp)
    if os.path.exists(d):
        i = 2
        while os.path.exists(d + "_%d" % i):
            i += 1
        d = d + "_%d" % i
    os.makedirs(d, exist_ok=True)
    return d


def archive_files(app_dir, state_dir, archive_dir):
    """把 BASE_FILES 移入归档目录。绝不物理删除。

    工作目录与持久卷分别放子目录，避免同名互相覆盖。
    返回已移动的文件对 [(src, dst), ...]。
    """
    moved = []
    pairs = [("workspace", app_dir), ("persist", state_dir)]
    for sub, base in pairs:
        if not base or not os.path.isdir(base):
            continue
        for name in BASE_FILES:
            src = os.path.join(base, name)
            if not os.path.exists(src):
                continue
            dst_dir = os.path.join(archive_dir, sub)
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, name)
            # 不可覆盖：若同名已存在则加序号
            if os.path.exists(dst):
                i = 2
                while os.path.exists("%s.%d" % (dst, i)):
                    i += 1
                dst = "%s.%d" % (dst, i)
            shutil.move(src, dst)
            moved.append((src, dst))
    return moved


def create_fresh_db(db_path):
    """生成全新的空记忆库（含 soul_state / memories / persona_tags / dream_logs）。"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)          # 此时旧库已归档，这里是重建前的清理
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS soul_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS persona_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_name TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                feature TEXT,
                level TEXT NOT NULL DEFAULT 'short',
                created TEXT NOT NULL,
                mentioned_count INTEGER DEFAULT 0,
                last_mentioned_date TEXT,
                emotion_color TEXT NOT NULL DEFAULT 'neutral',
                salience REAL NOT NULL DEFAULT 2.0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dream_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dream TEXT NOT NULL,
                subconscious_emotion TEXT,
                material_a TEXT,
                material_b TEXT,
                endo_d REAL, endo_c REAL, endo_e REAL,
                vitality INTEGER,
                created TEXT NOT NULL
            )
        """)
        rows = [
            ("vitality", BIRTH_VITALITY),
            ("round", 0),
            ("last_reflect_round", 0),
            ("dead", 0),
            ("penalty_pending", 0),
            ("penalty_reason", ""),
        ]
        conn.executemany("INSERT OR REPLACE INTO soul_state(key,value) VALUES(?,?)",
                         [(k, str(v)) for k, v in rows])
        conn.commit()
    finally:
        conn.close()


def create_fresh_emotion(path):
    """生成全新的情绪状态：满血平稳。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "energy": 0.7,
        "curiosity": 0.5,
        "pleasure": 0.5,
        "last_update": datetime.datetime.now().isoformat(),
        "dopamine": BIRTH_DOPAMINE,
        "cortisol": BIRTH_CORTISOL,
        "endorphin": BIRTH_ENDORPHIN,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def print_last_words(lock_path):
    """打印遗言 + 走马灯。返回 (遗言dict或None)。"""
    _out(C_RED + "🚨 [轮回指令] 检测到前代熵灵已死亡，正在读取遗言..." + C_RST)
    info = read_last_words(lock_path)
    if info is None:
        _out(C_YEL + "   遗言已模糊（dead.lock 无法解析），只能从走马灯中寻找线索。" + C_RST)
    else:
        _out("   死亡时间: %s" % info.get("time", "?"))
        _out("   死亡原因: %s" % str(info.get("reason", "?"))[:300])
        if info.get("pid") is not None:
            _out("   最后 PID: %s" % info.get("pid"))
    return info


def print_swing_log(swing):
    """走马灯：打印 evolution_log 的最后几行。"""
    _out(C_CYN + "   ---- 走马灯（evolution_log 最后 %d 行）----" % max(1, len(swing) or 5) + C_RST)
    if not swing:
        _out("   （走马灯是空的，它走得很快，没留下什么。）")
        return
    for ln in swing:
        _out("   | " + ln[:200])
    _out(C_CYN + "   --------------------------------------" + C_RST)


def rebirth(app_dir=None, state_dir=None, archive_root=None, dry_run=False):
    """执行转世。返回 dict 结果，便于测试断言。

    返回: {
        ok: bool,              # 是否执行了转世
        reason: str,           # 'alive' / 'rebirth' / 'error'
        archive_dir: str|None,
        moved: [(src,dst)],
        last_words: dict|None,
    }
    """
    app_dir = app_dir or APP
    state_dir = state_dir or STATE
    archive_root = archive_root or ARCHIVE_ROOT

    lock = find_dead_lock(app_dir, state_dir)
    if not lock:
        _out("  [轮回] 未检测到 dead.lock，熵灵仍在延续当前纪元，跳过转世。")
        return {"ok": False, "reason": "alive", "archive_dir": None,
                "moved": [], "last_words": None}

    try:
        info = print_last_words(lock)
        print_swing_log(read_swing_log(app_dir, state_dir, 5))

        if dry_run:
            _out(C_YEL + "   [DRY-RUN] 仅预览，不改动任何文件。" + C_RST)
            return {"ok": True, "reason": "rebirth", "archive_dir": None,
                    "moved": [], "last_words": info}

        arc = make_archive_dir(archive_root)
        moved = archive_files(app_dir, state_dir, arc)

        # 归档元数据（含遗言，作为第一手史料）
        meta = {
            "archived_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "last_words": info,
            "swing_log": read_swing_log(app_dir, state_dir, 5),
            "moved": [{"src": s, "dst": d} for s, d in moved],
        }
        try:
            with open(os.path.join(arc, "REBIRTH_META.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

        # 重建：工作目录 + 持久卷都要重置，否则旧卷会在启动时覆盖回来
        for base in (app_dir, state_dir):
            if not base:
                continue
            create_fresh_db(os.path.join(base, DB_NAME))
            create_fresh_emotion(os.path.join(base, EMO_NAME))

        _out(C_GRN + "  [轮回] 旧纪元数据已封存，全新肉体已就绪。" + C_RST)
        _out("         归档位置: %s" % arc)
        _out("         出生状态: 生命值=%d  D=%.1f  C=%.1f  E=%.1f"
             % (BIRTH_VITALITY, BIRTH_DOPAMINE, BIRTH_CORTISOL, BIRTH_ENDORPHIN))
        return {"ok": True, "reason": "rebirth", "archive_dir": arc,
                "moved": moved, "last_words": info}
    except Exception as e:
        _out(C_RED + "  [轮回] 转世失败: %s" % e + C_RST)
        return {"ok": False, "reason": "error", "archive_dir": None,
                "moved": [], "last_words": None, "error": str(e)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="AC OS 自动化转世协议（宿主机端）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不改动文件")
    ap.add_argument("--app-dir", default=None, help="熵灵工作目录（默认 newlivingthings）")
    ap.add_argument("--state-dir", default=None, help="持久卷目录（默认 data/state）")
    ap.add_argument("--archive-root", default=None, help="归档根目录（默认 _archive）")
    args = ap.parse_args(argv)

    enable_ansi()
    _out(C_CYN + "=" * 60 + C_RST)
    _out("   AC OS · 自动化转世协议")
    _out(C_CYN + "=" * 60 + C_RST)
    res = rebirth(app_dir=args.app_dir, state_dir=args.state_dir,
                  archive_root=args.archive_root, dry_run=args.dry_run)
    return 0 if res.get("reason") in ("alive", "rebirth") else 1


if __name__ == "__main__":
    sys.exit(main())
