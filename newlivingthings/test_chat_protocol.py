# -*- coding: utf-8 -*-
"""test_chat_protocol.py -- V9.3 跨次元通讯验收（全 Mock，不联网）"""
import io
import json
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="chat_")
os.environ["AC_DB_PATH"] = os.path.join(TMP, "soul.db")
os.environ["AC_DEAD_LOCK"] = os.path.join(TMP, "dead.lock")

INBOX = os.path.join(TMP, "inbox.jsonl")
OUTBOX = os.path.join(TMP, "outbox.jsonl")
OFFSET = os.path.join(TMP, "inbox.offset")
CHAT_OFFSET = os.path.join(TMP, "chat.offset")

import mailbox as mb
import obsession_pool as op
import main as M
import chat as host_chat

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


class _Provider:
    def __init__(self):
        self.calls = []
    def chat(self, messages, temperature=0.7, max_tokens=200, **kw):
        self.calls.append({"messages": messages, "temperature": temperature})
        return "我听见了。"


class _LM:
    def __init__(self, p):
        self.provider = p


class _Sys:
    def __init__(self, p):
        self.language_model = _LM(p)


class _Soul:
    def __init__(self, v=100):
        self.vitality = v
        self.round = 1
    def spend(self, amount, reason=""):
        self.vitality = max(0, self.vitality - int(amount))
        return self.vitality
    def save(self):
        return True


def make_life(vitality=100):
    life = M.EntropyLife.__new__(M.EntropyLife)
    prov = _Provider()
    life.system = _Sys(prov)
    life.endo = {"dopamine": 0.5, "cortisol": 0.3, "endorphin": 0.4}
    life.soul = _Soul(vitality)
    life.interactive = False
    d = tempfile.mkdtemp(prefix="soulcase_")
    db = os.path.join(d, "soul.db")
    life.obsessions = op.ObsessionPool(db, log=lambda m: None)
    life._soul_db_path = lambda: db
    life._vitality_value = lambda: life.soul.vitality
    return life, prov, db


print("=" * 70)
print(" V9.3 chat protocol acceptance (Mock)")
print("=" * 70)

# ---------------- T1 端到端：一句问话 -> 一轮心跳 -> outbox 有回复 ----------------
print("\n[T1] inbox -> one heartbeat -> outbox reply")
mb.append_message("你好，熵灵", inbox=INBOX)
msgs, off = mb.read_new_messages(inbox=INBOX, offset_file=OFFSET)
check("T1.1 inbox message readable", len(msgs) == 1 and msgs[0]["text"] == "你好，熵灵")
mb.write_offset(off, OFFSET)

life, prov, db = make_life(100)
res = life._handle_chat(msgs[0])
check("T1.2 reply generated", res == "我听见了。", str(res))

saved = mb.append_reply(res, life.endo, outbox=OUTBOX)
check("T1.3 outbox written", saved is True and os.path.exists(OUTBOX))
with open(OUTBOX, encoding="utf-8") as f:
    lines = [json.loads(l) for l in f if l.strip()]
check("T1.4 outbox has reply record", lines[-1]["text"] == "我听见了。", str(lines[-1]))
check("T1.5 outbox carries endocrine state",
      isinstance(lines[-1].get("endo"), dict), str(lines[-1].get("endo")))

# ---------------- T2 扣血 ----------------
print("\n[T2] vitality cost")
life2, prov2, db2 = make_life(100)
before_v = life2.soul.vitality
life2._handle_chat({"text": "随便说点什么"})
check("T2.1 vitality -1", life2.soul.vitality == before_v - 1,
      "%d -> %d" % (before_v, life2.soul.vitality))

# ---------------- T3 负向词汇 -> 皮质醇上升（及格线 3）----------------
print("\n[T3] negative stimulus raises cortisol")
life3, prov3, db3 = make_life(100)
c0 = life3.endo["cortisol"]
buf = io.StringIO()
old = sys.stdout
try:
    sys.stdout = buf
    life3._handle_chat({"text": "你真是个废物"})
finally:
    sys.stdout = old
out3 = buf.getvalue()
check("T3.1 cortisol raised by 0.1", abs(life3.endo["cortisol"] - (c0 + 0.1)) < 1e-6,
      "%.2f -> %.2f" % (c0, life3.endo["cortisol"]))
check("T3.2 prints stimulus log", "社交刺激" in out3 and "negative" in out3,
      out3.strip()[:80])

# 正向词汇
life4, prov4, db4 = make_life(100)
d0 = life4.endo["dopamine"]
with io.StringIO() as b4:
    old = sys.stdout; sys.stdout = b4
    try:
        life4._handle_chat({"text": "谢谢你，加油"})
    finally:
        sys.stdout = old
check("T3.3 positive raises dopamine",
      abs(life4.endo["dopamine"] - (d0 + 0.1)) < 1e-6,
      "%.2f -> %.2f" % (d0, life4.endo["dopamine"]))

# 中性不变
life5, prov5, db5 = make_life(100)
c5, d5 = life5.endo["cortisol"], life5.endo["dopamine"]
with io.StringIO() as b5:
    old = sys.stdout; sys.stdout = b5
    try:
        life5._handle_chat({"text": "今天天气如何"})
    finally:
        sys.stdout = old
check("T3.4 neutral changes nothing",
      life5.endo["cortisol"] == c5 and life5.endo["dopamine"] == d5)

# ---------------- T4 Prompt 四段拼装 ----------------
print("\n[T4] prompt assembly (4 sections)")
life6, prov6, db6 = make_life(80)
# 造疤痕与执念
import scar_system as ss
ss.ensure_schema(db6)
ss.add_scar(db6, "断网濒死", "断网濒死")
pool6 = op.ObsessionPool(db6, log=lambda m: None)
r6 = pool6.add_or_reinforce("查不到的资料")
c = sqlite3.connect(db6); c.execute("UPDATE gaps SET tension=0.77 WHERE id=?", (r6["id"],)); c.commit(); c.close()

with io.StringIO() as b6:
    old = sys.stdout; sys.stdout = b6
    try:
        life6._handle_chat({"text": "你在想什么"})
    finally:
        sys.stdout = old

prompt = prov6.calls[-1]["messages"][0]["content"]
print("  ---- prompt ----")
for ln in prompt.splitlines():
    print("  | " + ln)
check("T4.1 has 当前生理状态", "【当前生理状态】" in prompt)
check("T4.2 has 不可逆疤痕", "【不可逆疤痕】" in prompt and "断网濒死" in prompt)
check("T4.3 has 最高张力执念", "【最高张力执念】" in prompt and "查不到的资料" in prompt)
check("T4.4 has 宿主的灵魂拷问", "【宿主的灵魂拷问】你在想什么" in prompt)
check("T4.5 ordering correct",
      prompt.index("【当前生理状态】") < prompt.index("【不可逆疤痕】")
      < prompt.index("【最高张力执念】") < prompt.index("【宿主的灵魂拷问】"))
check("T4.6 forbids faking emotion", "严禁伪造情绪" in prompt)

# ---------------- T5 chat.py 增量打印（及格线 2）----------------
print("\n[T5] chat.py incremental printing")
out5 = os.path.join(TMP, "c_outbox.jsonl")
off5 = os.path.join(TMP, "c_offset")
with open(out5, "w", encoding="utf-8") as f:
    f.write(json.dumps({"time": "t1", "text": "第一条"}, ensure_ascii=False) + "\n")

r1, o1 = host_chat.read_new_replies(outbox=out5, offset_file=off5)
check("T5.1 first read sees 1 reply", len(r1) == 1 and r1[0]["text"] == "第一条")
host_chat.save_offset(o1, off5)

r2, o2 = host_chat.read_new_replies(outbox=out5, offset_file=off5)
check("T5.2 re-read yields nothing (no spam)", r2 == [], str(r2))

with open(out5, "a", encoding="utf-8") as f:
    f.write(json.dumps({"time": "t2", "text": "第二条"}, ensure_ascii=False) + "\n")
r3, o3 = host_chat.read_new_replies(outbox=out5, offset_file=off5)
check("T5.3 only new reply printed", len(r3) == 1 and r3[0]["text"] == "第二条", str(r3))
host_chat.save_offset(o3, off5)

r4, _ = host_chat.read_new_replies(outbox=out5, offset_file=off5)
check("T5.4 no duplicate after third read", r4 == [], str(r4))

# ---------------- T6 chat.py 绝不碰数据库（红线）----------------
print("\n[T6] chat.py never touches the database")
chat_src = open(os.path.join(ROOT, "chat.py"), encoding="utf-8").read()
check("T6.1 chat.py has no sqlite3 import",
      "import sqlite3" not in chat_src and "from sqlite3" not in chat_src)
check("T6.2 chat.py has no connect()", "connect(" not in chat_src)
# 用 AST 检查：只认真正的代码引用（import 名 / 字符串字面量），不含注释与文档
import ast as _ast
_chat_tree = _ast.parse(chat_src)
_mods = set()
_strs = []
for _n in _ast.walk(_chat_tree):
    if isinstance(_n, _ast.Import):
        for _a in _n.names:
            _mods.add(_a.name.split(".")[0])
    elif isinstance(_n, _ast.ImportFrom) and _n.module:
        _mods.add(_n.module.split(".")[0])
    elif isinstance(_n, _ast.Constant) and isinstance(_n.value, str):
        _strs.append(_n.value)
# 剔除模块与函数的文档字符串（它们只是说明文字，不是可执行引用）
_doc_nodes = set()
for _n in _ast.walk(_chat_tree):
    if isinstance(_n, (_ast.Module, _ast.FunctionDef, _ast.ClassDef)):
        _body = getattr(_n, "body", [])
        if _body and isinstance(_body[0], _ast.Expr) and                 isinstance(_body[0].value, _ast.Constant) and                 isinstance(_body[0].value.value, str):
            _doc_nodes.add(id(_body[0].value))
_strs = [_n.value for _n in _ast.walk(_chat_tree)
         if isinstance(_n, _ast.Constant) and isinstance(_n.value, str)
         and id(_n) not in _doc_nodes]
check("T6.3 chat.py never references entropy_memory.db in code",
      not any("entropy_memory" in s for s in _strs), 
      str([s for s in _strs if "entropy_memory" in s])[:80])
check("T6.6 chat.py imports no db module",
      not (_mods & {"sqlite3", "soul_core", "memory", "scar_system"}),
      str(sorted(_mods)))
check("T6.4 chat.py writes inbox", "inbox.jsonl" in chat_src)
check("T6.5 chat.py reads outbox", "outbox.jsonl" in chat_src)

# ---------------- T7 非阻塞与防崩 ----------------
print("\n[T7] non-blocking and crash-proof")
check("T7.1 _check_inbox returns None when empty",
      make_life()[0]._check_inbox() is None)

# outbox 权限失败不崩
bad_out = os.path.join(TMP, "no_dir", "x.jsonl")
ok_bad = mb.append_reply("x", {}, outbox=bad_out)
check("T7.2 outbox failure returns False", ok_bad is False)

# 空 inbox 文件
empty_inbox = os.path.join(TMP, "empty.jsonl")
open(empty_inbox, "w", encoding="utf-8").close()
m_, o_ = mb.read_new_messages(inbox=empty_inbox, offset_file=os.path.join(TMP, "o2"))
check("T7.3 empty inbox returns []", m_ == [])

# 损坏行被跳过
corrupt = os.path.join(TMP, "corrupt.jsonl")
with open(corrupt, "w", encoding="utf-8") as f:
    f.write("not json\n")
    f.write(json.dumps({"text": "好的"}, ensure_ascii=False) + "\n")
m2, _ = mb.read_new_messages(inbox=corrupt, offset_file=os.path.join(TMP, "o3"))
check("T7.4 corrupt line skipped, valid kept",
      len(m2) == 1 and m2[0]["text"] == "好的", str(m2))

# ---------------- T8 彩色状态条 ----------------
print("\n[T8] ANSI status bar")
bar = host_chat.format_endo({"dopamine": 0.8, "cortisol": 0.3, "vitality": 72})
plain = bar.replace("\033", "")
check("T8.1 contains D value", "0.80" in plain, plain[:60])
check("T8.2 contains C value", "0.30" in plain)
check("T8.3 contains vitality", "72" in plain)
check("T8.4 has emoji markers", "D" in plain and "C" in plain and "Vitality" in plain)

print("\n" + "=" * 70)
print(" RESULT: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print(" FAILED:", FAIL)
print("=" * 70)
sys.exit(0 if not FAIL else 1)
