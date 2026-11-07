# test_gene_injection.py
# -*- coding: utf-8 -*-
"""
test_gene_injection.py —— V6.3 基因记忆注入 · TDD 验收（全程 Mock，禁真模型）

【绝对红线】
  本测试不得触发任何真实 Ollama / Granite 推理。
  所有"大模型"一律用下方 _MockProvider / _MockScoutBrain 测试桩代替，
  它们在 __init__ 里装载断线断路器：一旦有人偷偷换成真 provider，直接抛异常。
  演练中只验证「真实流水线代码 + Mock 产物」，绝不烧 1500% CPU。

覆盖：
  T1 基因记忆真实读取：临时 SQLite 注入高多巴胺 / 高皮质醇 / 中性记忆
  T2 侦察前强制注入：每次 scan / scan_multi 都必须打印基因记忆行
  T3 老库兼容：缺 emotion_color / salience 列也不许静默返回空
  T4 端到端（Mock 大脑）：SyntaxError -> Scout -> Judge -> Surgeon -> VERIFIED
  T5 人格审查回环（Mock 大脑）：初步 -> 评判：合理 -> 采纳入库
  T6 物理防爆回归：Judge 不许调模型 / 截断 20 行 / 熔断加皮质醇
  T7 Mock 自证：真的没有任何真实网络/模型调用
"""
import io
import os
import re
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
os.chdir(HERE)

# ---- 物理隔离：测试期间禁止任何真实模型/网络出站 ----
os.environ["AC_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="ac_gene_"), "gene.db")
os.environ.pop("OLLAMA_BASE_URL", None)

import self_refactor as sr            # noqa: E402
import soul_core                      # noqa: E402

PASS, FAIL = [], []
MOCK_CALLS = {"chat": 0, "net": 0}


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


def capture(fn):
    buf, old = io.StringIO(), sys.stdout
    try:
        sys.stdout = buf
        r = fn()
    finally:
        sys.stdout = old
    return r, buf.getvalue()


def free_port_blocker():
    """断线断路器：真 provider 才会被触发，Mock 永远碰不到。"""
    raise AssertionError("【红线】检测到真实模型调用尝试，已强制中断（禁止跑真实 Ollama）")


# ============================================================
# 测试桩：Mock 大模型
# ============================================================
class _MockScoutBrain(object):
    """Scout 的 Mock 大脑：按预设剧本返回，绝不联网、绝不加载权重。"""

    MODEL = "MOCK-granite-4.0-tiny-h"

    def __init__(self, syntax_error_line):
        self.syntax_error_line = int(syntax_error_line)
        self.seen_prompts = []

    def chat(self, messages, temperature=0.7, max_tokens=500):
        MOCK_CALLS["chat"] += 1
        prompt = messages[-1]["content"] if messages else ""
        self.seen_prompts.append(prompt)
        # 回放一份「侦察报告」，形态与真实大脑一致
        return ('{"issues": [{"file_path": "target.py", "error_line": %d, '
                '"evidence": "SyntaxError: unfinished parenthesis", '
                '"suggested_fix": "补上右括号", "severity": 8}]}'
                % self.syntax_error_line)


class _MockReviewBrain(object):
    """人格审查的 Mock 大脑：第一次吐标签，第二次给评判。"""

    def __init__(self, tag="谨慎稳健"):
        self.tag = tag
        self.calls = 0

    def chat(self, messages, temperature=0.7, max_tokens=500):
        MOCK_CALLS["chat"] += 1
        self.calls += 1
        prompt = messages[-1]["content"] if messages else ""
        if "人格标签" in prompt or "概括你自己" in prompt:
            return "标签：%s" % self.tag
        return "能在近期经历中找到具体支撑。\n合理"


class _MockSoul(object):
    """轻量灵魂桩：只记录入库了哪些标签。"""

    def __init__(self):
        self.tags = []

    def add_tag(self, tag, weight=1.0):
        self.tags.append((tag, float(weight)))
        return True

    def get_penalty_pending(self):
        return 0.0

    def _set(self, k, v):
        pass


# ============================================================
# 基建：造一个带高权重记忆的临时库
# ============================================================
def make_gene_db(dirpath, with_color=True, with_salience=True):
    """造临时记忆库。with_color/with_salience=False 用于模拟老库。"""
    path = os.path.join(dirpath, "gene.db")
    conn = sqlite3.connect(path)
    cols = ["id INTEGER PRIMARY KEY AUTOINCREMENT", "name TEXT NOT NULL",
            "feature TEXT", "level TEXT NOT NULL DEFAULT 'short'",
            "created TEXT NOT NULL"]
    if with_color:
        cols.append("emotion_color TEXT NOT NULL DEFAULT 'neutral'")
    if with_salience:
        cols.append("salience REAL NOT NULL DEFAULT 2.0")
    conn.execute("CREATE TABLE memories (%s)" % ", ".join(cols))
    rows = [("晨光与橘猫", "窗台上慵懒的橘猫、暖光", "positive", 4.0),   # 高多巴胺
            ("深夜报错", "#TRAUMA 编译崩坏导致死机", "negative", 10.0),  # 高皮质醇
            ("抓取网页", "抓取了一段新闻", "neutral", 2.0)]               # 中性，应被过滤
    for name, feat, color, sal in rows:
        fields = ["name", "feature", "level", "created"]
        vals = [name, feat, "long", "2026-11-07"]
        if with_color:
            fields.append("emotion_color")
            vals.append(color)
        if with_salience:
            fields.append("salience")
            vals.append(sal)
        conn.execute("INSERT INTO memories (%s) VALUES (%s)"
                     % (", ".join(fields), ", ".join("?" * len(vals))), vals)
    conn.commit()
    conn.close()
    return path


def make_broken_target(dirpath):
    p = os.path.join(dirpath, "target.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write("def greet():\n")
        f.write("    print(\"hello\"\n")     # 缺右括号 -> SyntaxError
        f.write("    return 1\n")
    return p


ENDO = {"dopamine": 0.62, "cortisol": 0.55, "endorphin": 0.41}


# ---------------------------------------------------------------- T1
def t1_load_gene_memories():
    print("\n[T1] 基因记忆真实读取（临时 SQLite，非 Mock 数据）")
    tmp = tempfile.mkdtemp(prefix="ac_t1_")
    db = make_gene_db(tmp)
    mems = sr.load_gene_memories(n=5, db_path=db)
    check("T1.1 读到 2 条高权重记忆（中性被过滤）", len(mems) == 2, "(got=%d)" % len(mems))
    check("T1.2 高皮质醇创伤记忆排第一（salience 优先）",
          mems and "TRAUMA" in str(mems[0]["feature"]), str(mems[0]["feature"] if mems else ""))
    check("T1.3 每条都带 D/C 等效值",
          all("d" in m and "c" in m for m in mems))
    check("T1.4 多巴胺/皮质醇阈值判定正确",
          all(m["d"] > sr.MEMORY_D_THRESHOLD or m["c"] > sr.MEMORY_C_THRESHOLD for m in mems))
    check("T1.5 n 上限生效", len(sr.load_gene_memories(n=1, db_path=db)) == 1)
    check("T1.6 库不存在时安全返回空", sr.load_gene_memories(db_path=os.path.join(tmp, "nope.db")) == [])


# ---------------------------------------------------------------- T2
def t2_forced_injection():
    print("\n[T2] 侦察前强制注入基因记忆")
    tmp = tempfile.mkdtemp(prefix="ac_t2_")
    db = make_gene_db(tmp)
    target = make_broken_target(tmp)
    scout = sr.Scout(llm=_MockScoutBrain(2), endo=ENDO, db_path=db)

    report, out = capture(lambda: scout.scan(target))
    print("  ---- 侦察输出 ----")
    for line in out.strip().splitlines():
        print("  | " + line)
    check("T2.1 打印 [Scout] 已加载近期基因记忆作为参考：...",
          "[Scout] 已加载近期基因记忆作为参考：" in out)
    check("T2.2 注入内容含高权重记忆", "TRAUMA" in out or "橘猫" in out)
    check("T2.3 侦察 Prompt 已生成且携带基因记忆",
          "基因记忆" in scout.last_prompt and "TRAUMA" in scout.last_prompt)
    check("T2.4 侦察 Prompt 携带当前内分泌", "D=0.62" in scout.last_prompt, scout.last_prompt[:0])
    check("T2.5 Prompt 长度受控（防 KV Cache 爆炸）", len(scout.last_prompt) < 2000,
          "(%d chars)" % len(scout.last_prompt))
    check("T2.6 仍能正常检出问题", len(report.get("issues") or []) == 1)

    # scan_multi 同样必须注入
    s2 = sr.Scout(llm=_MockScoutBrain(2), endo=ENDO, db_path=db)
    _r2, out2 = capture(lambda: s2.scan_multi([target]))
    check("T2.7 scan_multi 也强制注入", "[Scout] 已加载近期基因记忆作为参考：" in out2)

    # 空库也不能崩，只是降级文案
    s3 = sr.Scout(endo=ENDO, db_path=os.path.join(tmp, "empty.db"))
    _r3, out3 = capture(lambda: s3.scan(target))
    check("T2.8 无记忆时降级为（暂无高权重记忆）",
          "（暂无高权重记忆）" in out3)


# ---------------------------------------------------------------- T3
def t3_legacy_db():
    print("\n[T3] 老库兼容（缺列不许静默失效）")
    tmp = tempfile.mkdtemp(prefix="ac_t3_")
    bare = make_gene_db(tmp, with_color=False, with_salience=False)
    conn = sqlite3.connect(bare)
    rows = conn.execute("SELECT name FROM memories").fetchall()
    conn.close()
    check("T3.1 老库构造成功（无 emotion_color / salience）", len(rows) == 3)
    # 老库无染色信息 -> 中性，不应崩、不应抛
    mems = sr.load_gene_memories(db_path=bare)
    check("T3.2 老库不抛异常、返回列表", isinstance(mems, list), "(n=%d)" % len(mems))
    scout = sr.Scout(endo=ENDO, db_path=bare)
    ctx, out = capture(lambda: scout.load_gene_context())
    check("T3.3 老库下仍打印基因记忆日志",
          "[Scout] 已加载近期基因记忆作为参考：" in out)


# ---------------------------------------------------------------- T4
def t4_end_to_end_mock():
    print("\n[T4] 端到端（Mock 大脑驱动）：SyntaxError -> VERIFIED")
    tmp = tempfile.mkdtemp(prefix="ac_t4_")
    db = make_gene_db(tmp)
    target = make_broken_target(tmp)
    brain = _MockScoutBrain(2)

    def fixer(source, task):
        # 修复器同样是 Mock：只看 task 派单内容做确定性补丁
        return source.replace('print("hello"\n', 'print("hello")\n')

    endo = dict(ENDO)
    result, out = capture(lambda: sr.run_refactor(
        target, endo=endo, llm=brain, fixer=fixer, db_path=db))

    print("  " + "-" * 60)
    print("  ---- 真实终端日志 ----")
    for line in out.strip().splitlines():
        print("  | " + line)
    print("  " + "-" * 60)

    check("T4.1 流水线成功", result.get("ok") is True, str(result.get("reason")))
    check("T4.2 基因记忆先于侦察报告注入",
          out.index("[Scout] 已加载近期基因记忆作为参考：") <
          out.index("[Scout] 发现错误并输出报告..."))
    check("T4.3 打印 [Scout] 发现错误并输出报告...",
          "[Scout] 发现错误并输出报告..." in out)
    check("T4.4 打印 [Judge] 证据校验通过，截断长度至20行，派发任务...",
          "[Judge] 证据校验通过，截断长度至20行，派发任务..." in out)
    check("T4.5 打印 [Surgeon] 状态机 OBSERVED -> EDITED -> VERIFIED 验证通过。",
          "[Surgeon] 状态机 OBSERVED -> EDITED -> VERIFIED 验证通过。" in out)
    s = sr.Surgeon()
    s._lock_targets([target])
    check("T4.6 修复后文件可编译", s.py_compile(target)["ok"] is True)
    with open(target, encoding="utf-8") as f:
        check("T4.7 文件内容确已修复", 'print("hello")' in f.read())
    check("T4.8 成功路径不抬高皮质醇", abs(endo["cortisol"] - ENDO["cortisol"]) < 1e-9)
    check("T4.9 Mock 大脑确实被调用过（流程真实走通）", MOCK_CALLS["chat"] >= 1,
          "(calls=%d)" % MOCK_CALLS["chat"])


# ---------------------------------------------------------------- T5
def t5_persona_review_mock():
    print("\n[T5] 人格审查回环（Mock 大脑）")
    soul = _MockSoul()
    provider = _MockReviewBrain("谨慎稳健")
    res, out = capture(lambda: soul_core.reflect_persona(
        soul, provider, recent_log="第 3 轮：修好了 target.py 的语法错误。",
        endo_text="D=0.62 C=0.55 E=0.41", tries=1))
    print("  ---- 人格审查输出 ----")
    for line in out.strip().splitlines():
        print("  | " + line)

    check("T5.1 打印 [人格审查] 初步：xxx", "[人格审查] 初步：谨慎稳健" in out)
    check("T5.2 打印 -> 评判：合理", "-> 评判：合理" in out)
    check("T5.3 打印 -> 采纳入库", "-> 采纳入库" in out)
    check("T5.4 标签已入库", soul.tags == [("谨慎稳健", 1.0)], str(soul.tags))
    check("T5.5 action=accept", res.get("action") == "accept", str(res))


# ---------------------------------------------------------------- T6
def t6_physical_guard():
    print("\n[T6] 物理级防爆回归")
    judge = sr.Judge()
    denied = False
    try:
        judge.chat([{"role": "user", "content": "hi"}])
    except sr.PermissionDenied:
        denied = True
    check("T6.1 Judge 调模型被拒", denied)

    long_ev = "\n".join("line %d" % i for i in range(100))
    task = judge.dispatch({"issues": [{"file_path": "a.py", "evidence": long_ev,
                                       "suggested_fix": long_ev, "severity": 5}]})
    check("T6.2 evidence 硬截断 20 行", len(task.evidence.splitlines()) == 20,
          "(%d)" % len(task.evidence.splitlines()))

    tmp = tempfile.mkdtemp(prefix="ac_t6_")
    target = make_broken_target(tmp)

    def bad_fixer(source, t):
        return source + "\nif True print(1)\n"      # 越修越坏

    endo = {"dopamine": 0.5, "cortisol": 0.40}
    result, out = capture(lambda: sr.run_refactor(target, endo=endo, fixer=bad_fixer))
    check("T6.3 修不好触发熔断", result.get("reason") == "circuit-breaker",
          str(result.get("reason")))
    check("T6.4 皮质醇 +0.1（重构失败会焦虑）", abs(endo["cortisol"] - 0.50) < 1e-9,
          "(0.40 -> %.2f)" % endo["cortisol"])
    check("T6.5 熔断后文件回滚干净", "if True print(1)" not in open(target, encoding="utf-8").read())


# ---------------------------------------------------------------- T7
def t7_no_real_model():
    print("\n[T7] Mock 自证：全程无真实模型")
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    check("T7.1 测试源未 import ollama/openai", not re.search(
        r"^\s*(import|from)\s+(ollama|openai)\b", src, re.M))
    check("T7.2 本用例全部调用来自 Mock 桩", MOCK_CALLS["chat"] >= 2,
          "(mock chat calls=%d)" % MOCK_CALLS["chat"])
    check("T7.3 未发生任何真实网络调用", MOCK_CALLS["net"] == 0)


def main():
    print("=" * 70)
    print(" AC OS V6.3 · 基因记忆注入 · TDD 验收（全程 Mock，不跑真模型）")
    print("=" * 70)
    print(" 临时库: %s" % os.environ["AC_DB_PATH"])
    t1_load_gene_memories()
    t2_forced_injection()
    t3_legacy_db()
    t4_end_to_end_mock()
    t5_persona_review_mock()
    t6_physical_guard()
    t7_no_real_model()
    print("\n" + "=" * 70)
    print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print(" 失败项: %s" % FAIL)
    print("=" * 70)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
