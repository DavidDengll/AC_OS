# test_self_refactor.py
# -*- coding: utf-8 -*-
"""
test_self_refactor.py —— AC OS V6.0 自我重构验收测试

覆盖白皮书第六节全部验收标准：
  T1 错误文件拦截测试：制造 SyntaxError 临时文件
  T2 流水线正向测试：日志严格打印三行关键输出
  T3 熔断机制测试：无法修复 -> 重试 2 次 -> 优雅退出 -> 皮质醇上升
另含白皮书第二~五节的铁律回归：
  T4 权限白名单：Scout 不可写 / Surgeon 不可网 / 跨文件禁止
  T5 Judge 绝对不调大模型
  T6 搜索适配器三条铁律（致歉过滤 / 20 行截断 / 标识符校验）
"""
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
os.chdir(HERE)

import self_refactor as sr  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)


def make_broken_file(dirpath):
    """制造一个带 SyntaxError 的 Python 文件。"""
    p = os.path.join(dirpath, "broken_target.py")
    with open(p, "w", encoding="utf-8") as f:
        f.write("def greet():\n")
        f.write("    print(\"hello\"\n")   # 缺少右括号
        f.write("    return 1\n")
    return p


def capture(fn):
    buf = io.StringIO()
    old = sys.stdout
    try:
        sys.stdout = buf
        result = fn()
    finally:
        sys.stdout = old
    return result, buf.getvalue()


# ---------------------------------------------------------------- T1
def t1_broken_file():
    print("\n[T1] 错误文件拦截测试")
    tmp = tempfile.mkdtemp(prefix="ac_sr_")
    p = make_broken_file(tmp)
    scout = sr.Scout()
    report = scout.scan(p)
    issues = report.get("issues") or []
    check("T1.1 检出 1 个问题", len(issues) == 1, str(len(issues)))
    if issues:
        it = issues[0]
        check("T1.2 报告字段完整",
              all(k in it for k in ("file_path", "error_line", "evidence", "suggested_fix")))
        check("T1.3 记录到错误行号", int(it["error_line"]) > 0,
              "(line=%s)" % it["error_line"])
        check("T1.4 evidence 非空", bool(str(it["evidence"]).strip()))
    # 正常文件不应误报
    good = os.path.join(tmp, "good.py")
    with open(good, "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    check("T1.5 正常文件不报错",
          sr.Scout().scan(good).get("issues") == [])


# ---------------------------------------------------------------- T2
def t2_pipeline_ok():
    print("\n[T2] 流水线正向测试")
    tmp = tempfile.mkdtemp(prefix="ac_sr2_")
    p = make_broken_file(tmp)

    def fixer(source, task):
        # 真实修复：补上缺失的右括号
        return source.replace('print("hello"\n', 'print("hello")\n')

    endo = {"cortisol": 0.3}
    result, out = capture(lambda: sr.run_refactor(p, endo=endo, fixer=fixer))
    print("  ---- 终端输出 ----")
    for line in out.strip().splitlines():
        print("  | " + line)
    check("T2.1 重构成功", result.get("ok") is True, str(result))
    check("T2.2 打印 [Scout] 发现错误并输出报告...",
          "[Scout] 发现错误并输出报告..." in out)
    check("T2.3 打印 [Judge] 证据校验通过，截断长度至20行，派发任务...",
          "[Judge] 证据校验通过，截断长度至20行，派发任务..." in out)
    check("T2.4 打印 [Surgeon] 状态机 OBSERVED -> EDITED -> VERIFIED 验证通过。",
          "[Surgeon] 状态机 OBSERVED -> EDITED -> VERIFIED 验证通过。" in out)
    check("T2.5 修复后文件可编译",
          sr.Surgeon().py_compile(p).get("ok") is True)
    check("T2.6 成功路径不触发皮质醇上升", abs(endo["cortisol"] - 0.3) < 1e-9,
          "(%.3f)" % endo["cortisol"])


# ---------------------------------------------------------------- T3
def t3_circuit_breaker():
    print("\n[T3] 熔断机制测试")
    tmp = tempfile.mkdtemp(prefix="ac_sr3_")
    p = make_broken_file(tmp)

    def bad_fixer(source, task):
        # 修不好：换个同样语法错误的写法
        return source + "\nif True print(1)\n"

    endo = {"cortisol": 0.4}
    result, out = capture(lambda: sr.run_refactor(p, endo=endo, fixer=bad_fixer))
    print("  ---- 终端输出 ----")
    for line in out.strip().splitlines():
        print("  | " + line)
    check("T3.1 结果标记为熔断", result.get("reason") == "circuit-breaker",
          str(result.get("reason")))
    check("T3.2 ok 为 False", result.get("ok") is False)
    check("T3.3 皮质醇 +0.1", abs(endo["cortisol"] - 0.5) < 1e-9,
          "(0.4 -> %.3f)" % endo["cortisol"])
    retries = out.count("准备重试")
    check("T3.4 重试次数不超过 2", retries <= 2, "(retries=%d)" % retries)
    check("T3.5 抛出 RefactorFailedException 被捕获", "熔断" in out)

    # 直接验证异常类型
    surgeon = sr.Surgeon(fixer=bad_fixer, max_retries=2)
    task = sr.Task(p, "evidence", "fix")
    raised = False
    try:
        capture(lambda: surgeon.operate(task))
    except sr.RefactorFailedException:
        raised = True
    check("T3.6 operate 抛 RefactorFailedException", raised)


# ---------------------------------------------------------------- T4
def t4_permissions():
    print("\n[T4] 权限白名单（物理隔离）")
    scout = sr.Scout()
    for act in ("edit_file", "write_file", "shell"):
        denied = False
        try:
            getattr(scout, act)("x")
        except sr.PermissionDenied:
            denied = True
        check("T4.1 Scout 禁止 %s" % act, denied)

    surgeon = sr.Surgeon()
    net_denied = False
    try:
        surgeon.web_search("q")
    except sr.PermissionDenied:
        net_denied = True
    check("T4.2 Surgeon 禁止 web_search", net_denied)

    # 跨文件修改必须拦截
    tmp = tempfile.mkdtemp(prefix="ac_sr4_")
    a = os.path.join(tmp, "a.py")
    b = os.path.join(tmp, "b.py")
    for f in (a, b):
        open(f, "w", encoding="utf-8").write("x=1\n")
    s2 = sr.Surgeon()
    s2.read_file(a)
    cross = False
    try:
        s2.edit_file(b, "y=2\n")
    except sr.PermissionDenied:
        cross = True
    check("T4.3 Surgeon 禁止跨文件修改", cross)


# ---------------------------------------------------------------- T5
def t5_judge_no_llm():
    print("\n[T5] Judge 绝对不调大模型")
    judge = sr.Judge()
    check("T5.1 Judge 无 llm 属性", not hasattr(judge, "llm"))
    denied = False
    try:
        judge.chat([{"role": "user", "content": "hi"}])
    except sr.PermissionDenied:
        denied = True
    check("T5.2 Judge.chat 直接拒绝", denied)
    set_denied = False
    try:
        judge.llm = object()
    except sr.PermissionDenied:
        set_denied = True
    check("T5.3 禁止挂载 llm 属性", set_denied)

    # 清洗：剔除空证据与致歉信
    report = {"issues": [
        {"file_path": "a.py", "evidence": "", "severity": 9},
        {"file_path": "a.py", "evidence": "I'm sorry, network error", "severity": 9},
        {"file_path": "a.py", "error_line": 3,
         "evidence": "SyntaxError: invalid syntax", "suggested_fix": "fix", "severity": 5},
    ]}
    task = sr.Judge().dispatch(report)
    check("T5.4 剔除空证据与致歉信后派发", task is not None,
          str(task and task.error_line))
    check("T5.5 只派发 1 个任务", isinstance(task, sr.Task))

    # 截断至 20 行
    long_ev = "\n".join("line %d" % i for i in range(100))
    t2 = sr.Judge().dispatch({"issues": [{"file_path": "a.py", "evidence": long_ev,
                                          "suggested_fix": long_ev, "severity": 5}]})
    check("T5.6 evidence 截断至 20 行", len(t2.evidence.splitlines()) == 20,
          "(%d 行)" % len(t2.evidence.splitlines()))
    check("T5.7 suggested_fix 截断至 20 行", len(t2.suggested_fix.splitlines()) == 20)


# ---------------------------------------------------------------- T6
def t6_search_utils():
    print("\n[T6] 搜索适配器铁律")
    import search_utils as su
    check("T6.1 致歉信被过滤",
          su.web_search("q", bridge=lambda q, timeout=None: {
              "ok": True, "result": "I'm sorry, network error happened"}) == "")
    many = "\n".join("row %d" % i for i in range(60))
    out = su.web_search("q", bridge=lambda q, timeout=None: {"ok": True, "result": many})
    check("T6.2 结果截断至 20 行", len(out.splitlines()) == 20,
          "(%d 行)" % len(out.splitlines()))
    check("T6.3 普通英文单词不算模块", su.is_valid_identifier("Would") is False)
    check("T6.4 合法模块通过", su.is_valid_identifier("q_proj") is True)
    mods = su.extract_modules("use q_proj and k_proj; Would you like more?")
    check("T6.5 只提取合法模块", mods == ["q_proj", "k_proj"], str(mods))
    check("T6.6 空结果返回空串",
          su.web_search("q", bridge=lambda q, timeout=None: {"ok": False, "error": "x"}) == "")


def main():
    print("=" * 70)
    print(" AC OS V6.0 自我重构 · 验收测试")
    print("=" * 70)
    t1_broken_file()
    t2_pipeline_ok()
    t3_circuit_breaker()
    t4_permissions()
    t5_judge_no_llm()
    t6_search_utils()
    print("\n" + "=" * 70)
    print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print(" 失败项: %s" % FAIL)
    print("=" * 70)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
