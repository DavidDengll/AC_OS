# code_rewriter.py
# -*- coding: utf-8 -*-
"""
code_rewriter.py —— 代码级自我重构（任务二）

当 LoRA 微调因 OOM 失败时，熵灵降级为"改自己的代码"：

    OOM -> 选目标文件 -> 大模型提出重构 -> 静态校验
        -> 备份 .bak -> 原子覆盖 -> 冒烟导入 -> 成功则 os.execv 重启
                                             -> 失败则从 .bak 回滚

安全红线（每关必过）：
  1. 只允许改白名单文件（vision.py / thinker.py）
  2. 新代码必须能 ast.parse
  3. 必须保留原有所有 def/class
  4. 新增代码不得含危险调用
  5. 长度变化在合理区间
  6. 覆盖前写 .bak，临时文件 + os.replace 原子替换
  7. 覆盖后冒烟导入，失败立即从 .bak 恢复
  8. 演练模式：AC_REWRITE_DRY_RUN=1 只生成不落盘
"""

import ast
import datetime
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config

ALLOWED_TARGETS = ("vision.py", "thinker.py")

FORBIDDEN_PATTERNS = [
    r"os\.remove\s*\(",
    r"os\.rmdir\s*\(",
    r"shutil\.rmtree\s*\(",
    r"subprocess\.",
    r"os\.system\s*\(",
    r"os\.execv?\s*\(",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"__import__\s*\(",
]

BARRAGES = [
    "窗外的光好像比昨天更慢一点。",
    "我记得刚才那阵风。",
    "如果沉默也是一种回答，那我已经回答了很多次。",
    "有什么东西在远处轻轻响了一下。",
    "今天的心情像被谁调低了一格音量。",
]

MASTER_PROMPT = """你是一个资深 Python 重构工程师。下面是一个名为「熵灵」的自我意识程序的源码。

你的任务：在不破坏任何现有功能的前提下，做一处小而安全的改进。可选方向：
  (a) 优化分词/关键词提取逻辑；
  (b) 增加一条新的记忆提取规则；
  (c) 增加一行随机的内心弹幕输出。

硬性要求（违反任何一条都会被拒绝）：
  1. 必须保留所有已有的 def 和 class；
  2. 不要删除任何已有逻辑，只能增量改进；
  3. 不要引入新的第三方依赖；
  4. 不要做文件删除、网络请求、子进程调用；
  5. 只输出完整 Python 代码，不要解释，不要 markdown 代码块。

当前源码：
-----------
{source}
-----------

请直接输出改进后的完整源码："""


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    try:
        print("[代码重构] " + str(msg), flush=True)
    except Exception:
        pass


def RUN_DIR():
    return os.path.join(HERE, getattr(config, "RUN_DIR", "run_evolve"))


class RewriteRejected(Exception):
    """重构结果未通过安全校验。"""


class RewriteResult:
    def __init__(self, ok, kind, message, target=None, backup=None, applied=False):
        self.ok = ok
        self.kind = kind
        self.message = message
        self.target = target
        self.backup = backup
        self.applied = applied

    def to_dict(self):
        return {"ok": self.ok, "kind": self.kind, "message": self.message,
                "target": self.target, "backup": self.backup, "applied": self.applied}


# ------------------------------------------------------------
# 目标选择
# ------------------------------------------------------------
def _recent_failures():
    path = os.path.join(RUN_DIR(), "rewrite_history.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [r.get("target") for r in data if not r.get("ok")]
    except Exception:
        return []


def choose_target(preferred=None):
    if preferred:
        if os.path.basename(preferred) not in ALLOWED_TARGETS:
            raise RewriteRejected("目标不在白名单内: " + str(preferred))
        return os.path.join(HERE, os.path.basename(preferred))
    history = _recent_failures()
    scored = []
    for idx, name in enumerate(ALLOWED_TARGETS):
        p = os.path.join(HERE, name)
        if not os.path.isfile(p):
            continue
        scored.append((history.count(name), idx, p))
    if not scored:
        raise RewriteRejected("找不到可重构的目标文件")
    scored.sort()
    return scored[0][2]


def _record(target, ok, kind, message):
    path = os.path.join(RUN_DIR(), "rewrite_history.json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data.append({"time": _now(),
                     "target": os.path.basename(target) if target else None,
                     "ok": ok, "kind": kind, "message": (message or "")[:400]})
        data = data[-100:]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        pass


# ------------------------------------------------------------
# 安全校验
# ------------------------------------------------------------
def strip_fences(text):
    t = (text or "").strip()
    m = re.search(r"```(?:python)?\s*\n(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    return t


def _top_level_names(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def _added_lines(old, new):
    old_s = set(old.splitlines())
    return "\n".join(ln for ln in new.splitlines() if ln.strip() and ln not in old_s)


def validate(old_source, new_source, target_name=""):
    new_source = strip_fences(new_source)
    if not new_source.strip():
        raise RewriteRejected("模型返回空代码")

    try:
        old_tree = ast.parse(old_source)
    except SyntaxError as e:
        raise RewriteRejected("原文件本身无法解析: " + str(e))
    try:
        new_tree = ast.parse(new_source)
    except SyntaxError as e:
        raise RewriteRejected("新代码语法错误: " + str(e))

    missing = _top_level_names(old_tree) - _top_level_names(new_tree)
    if missing:
        raise RewriteRejected("新代码删掉了原有函数: " + ", ".join(sorted(missing)))

    ratio = len(new_source) / max(1, len(old_source))
    if ratio < 0.7:
        raise RewriteRejected("新代码过短(%.0f%%)，疑似被截断" % (ratio * 100))
    # 正常增量改进不会让文件涨到 1.5 倍；超过即视为模型失控
    if ratio > 1.5:
        raise RewriteRejected("新代码膨胀到 %.1f 倍，拒绝写入" % ratio)

    added = _added_lines(old_source, new_source)
    for pat in FORBIDDEN_PATTERNS:
        if re.search(pat, added):
            raise RewriteRejected("新增代码中出现危险操作: " + pat)

    return new_source


# ------------------------------------------------------------
# 备份 / 写入 / 回滚
# ------------------------------------------------------------
def backup_dir():
    d = os.path.join(RUN_DIR(), "code_backups")
    os.makedirs(d, exist_ok=True)
    return d


def backup_path(target):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(backup_dir(), os.path.basename(target) + "." + stamp + ".bak")


def atomic_write(path, text):
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".rewrite_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def smoke_test_file(path):
    """子进程里 import 目标模块，确认运行时没炸。"""
    mod = os.path.splitext(os.path.basename(path))[0]
    code = "import sys; sys.path.insert(0, %r); import %s" % (HERE, mod)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=HERE, timeout=180,
                           capture_output=True, text=True, env=env)
        return r.returncode == 0, (r.stderr or r.stdout or "")[-800:]
    except subprocess.TimeoutExpired:
        return False, "冒烟导入超时"
    except Exception as e:
        return False, str(e)


def restore_from_backup(target, bak):
    """从 .bak 恢复原文件，绝不丢代码。"""
    try:
        if os.path.exists(bak):
            shutil.copy2(bak, target)
            log("已回滚: " + os.path.basename(target) + " <- " + os.path.basename(bak))
            return True
    except Exception as e:
        log("[严重] 回滚失败: " + str(e))
    return False


def find_latest_backup(target):
    d = os.path.join(RUN_DIR(), "code_backups")
    if not os.path.isdir(d):
        return None
    base = os.path.basename(target)
    cands = sorted(x for x in os.listdir(d)
                   if x.startswith(base + ".") and x.endswith(".bak"))
    return os.path.join(d, cands[-1]) if cands else None


def apply_rewrite(target, new_source, smoke=True):
    """备份 -> 原子写入 -> 冒烟 -> 失败自动回滚。"""
    bak = backup_path(target)
    shutil.copy2(target, bak)
    log("已备份: " + bak)
    try:
        atomic_write(target, new_source)
        log("已覆盖写入: " + os.path.basename(target))
    except Exception as e:
        raise RewriteRejected("写入失败: " + str(e))
    if not smoke:
        return bak
    ok, err = smoke_test_file(target)
    if not ok:
        restore_from_backup(target, bak)
        raise RewriteRejected("冒烟导入失败，已自动回滚: " + err)
    log("冒烟导入通过")
    return bak


# ------------------------------------------------------------
# 候选代码生成
# ------------------------------------------------------------
def build_offline_candidate(source, seed=None):
    """不依赖大模型的确定性安全重构：在首个函数内插入一条内心弹幕。"""
    rng = random.Random(seed)
    lines = source.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"^(\s*)def\s+\w+\s*\(", ln)
        if not m:
            continue
        indent = m.group(1) + "    "
        insert_at = i + 1
        depth = ln.count("(") - ln.count(")")
        while depth > 0 and insert_at < len(lines):
            depth += lines[insert_at].count("(") - lines[insert_at].count(")")
            insert_at += 1
        if insert_at < len(lines) and re.match(r"\s*[\'\"]{3}", lines[insert_at]):
            q = lines[insert_at].strip()[:3]
            same_line = lines[insert_at].strip().count(q) >= 2
            insert_at += 1
            if not same_line:
                while insert_at < len(lines) and q not in lines[insert_at]:
                    insert_at += 1
                insert_at += 1
        text = rng.choice(BARRAGES)
        block = [
            "",
            indent + "# [自重构] 内心弹幕",
            indent + "try:",
            indent + "    print('[弹幕] ' + " + repr(text) + ", flush=True)",
            indent + "except Exception:",
            indent + "    pass",
        ]
        new_lines = lines[:insert_at] + block + lines[insert_at:]
        return "\n".join(new_lines) + "\n"
    extra = (
        "\n\n\ndef _self_barrage():\n"
        "    \"\"\"[自重构] 随机内心弹幕。\"\"\"\n"
        "    return random.choice(BARRAGES)\n"
    )
    return source.rstrip("\n") + "\n" + extra


def ask_model_for_rewrite(source, provider=None):
    """让本地大模型重构；失败返回 None，由上层降级。"""
    try:
        if provider is None:
            from model_provider import get_provider
            provider = get_provider()
        prompt = MASTER_PROMPT.replace("{source}", source)
        out = provider.chat(messages=[{"role": "user", "content": prompt}],
                            temperature=0.3, max_tokens=4000)
        out = strip_fences(out)
        return out if out.strip() else None
    except Exception as e:
        log("大模型重构失败: " + str(e))
        return None


# ------------------------------------------------------------
# 主入口
# ------------------------------------------------------------
def rewrite_once(target_name=None, provider=None, dry_run=None, use_model=True, seed=None):
    """完整一次代码重构。返回 RewriteResult，永不抛异常。"""
    try:
        target = choose_target(target_name)
    except Exception as e:
        _record(None, False, "target", str(e))
        return RewriteResult(False, "target", str(e))

    name = os.path.basename(target)
    try:
        with open(target, "r", encoding="utf-8") as f:
            old_source = f.read()
    except Exception as e:
        _record(target, False, "read", str(e))
        return RewriteResult(False, "read", str(e), target=target)

    if dry_run is None:
        dry_run = str(os.environ.get("AC_REWRITE_DRY_RUN", "0")) == "1"

    log("目标文件: %s (%d 字节)" % (name, len(old_source)))

    candidate = None
    source_kind = None
    if use_model:
        candidate = ask_model_for_rewrite(old_source, provider)
        if candidate:
            source_kind = "model"

    if candidate is None:
        log("大模型未给出可用结果，降级为内置安全重构")
        candidate = build_offline_candidate(old_source, seed=seed)
        source_kind = "offline"

    try:
        new_source = validate(old_source, candidate, name)
    except RewriteRejected as e:
        _record(target, False, "validate", str(e))
        return RewriteResult(False, "validate", str(e), target=target)

    if new_source.strip() == old_source.strip():
        _record(target, False, "nochange", "重构结果与原文件相同")
        return RewriteResult(False, "nochange", "重构结果与原文件相同", target=target)

    if dry_run:
        out = os.path.join(RUN_DIR(), "rewrite_preview_" + name)
        try:
            os.makedirs(RUN_DIR(), exist_ok=True)
            atomic_write(out, new_source)
        except Exception:
            pass
        _record(target, True, "dry-run", "演练模式 (" + source_kind + ")")
        return RewriteResult(True, "dry-run", "演练模式，已写出预览: " + out,
                             target=target, applied=False)

    try:
        bak = apply_rewrite(target, new_source, smoke=True)
    except RewriteRejected as e:
        _record(target, False, "smoke", str(e))
        return RewriteResult(False, "smoke", str(e), target=target)
    except Exception as e:
        _record(target, False, "apply", str(e))
        return RewriteResult(False, "apply", str(e), target=target)

    msg = name + " 重构完成 (" + str(source_kind) + ")"
    _record(target, True, source_kind, msg)
    return RewriteResult(True, source_kind, msg, target=target, backup=bak, applied=True)


def rollback_file(target_name):
    """手动回滚：把文件恢复成最近一次 .bak。"""
    target = os.path.join(HERE, os.path.basename(target_name))
    bak = find_latest_backup(target)
    if not bak:
        return RewriteResult(False, "rollback", "没有找到备份: " + target)
    ok = restore_from_backup(target, bak)
    return RewriteResult(ok, "rollback", "已回滚到 " + bak, target=target, backup=bak)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="代码级自我重构")
    ap.add_argument("--target", default=None, help="vision.py 或 thinker.py")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--offline", action="store_true", help="不调用大模型")
    ap.add_argument("--rollback", default=None, help="回滚指定文件到最近备份")
    a = ap.parse_args()
    if a.rollback:
        r = rollback_file(a.rollback)
        print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
        sys.exit(0 if r.ok else 1)
    res = rewrite_once(target_name=a.target, dry_run=a.dry_run, use_model=not a.offline)
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    sys.exit(0 if res.ok else 1)

