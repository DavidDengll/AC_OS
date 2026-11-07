# test_refactor_multi.py
# -*- coding: utf-8 -*-
"""
test_refactor_multi.py —— V6.1 多文件原子手术验收

覆盖任务书全部及格线：
  T1 跨两文件报错（A import B）被检出
  T2 协同手术日志：[Surgeon] 正在对 2 个文件进行协同手术...
  T3 回滚：编译失败后文件必须恢复到快照状态
  T4 超时：模拟慢编译，验证 15 秒后进程树被杀（本测试用短超时加速）
  T5 AST 拦截：引入循环依赖的补丁被法官拒绝
  T6 修改行数上限：超过 100 行拒绝
  T7 上限：最多 3 个文件，跨目标修改被拒
"""
import io
import os
import sys
import tempfile
import time

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


def capture(fn):
    buf, old = io.StringIO(), sys.stdout
    try:
        sys.stdout = buf
        r = fn()
    finally:
        sys.stdout = old
    return r, buf.getvalue()


def make_pair(dirpath, broken=True):
    """A import B；B 里有语法错误（可选）。"""
    a = os.path.join(dirpath, "mod_a.py")
    b = os.path.join(dirpath, "mod_b.py")
    with open(a, "w", encoding="utf-8") as f:
        f.write("import mod_b\n")
        f.write("VALUE = 1\n")
    with open(b, "w", encoding="utf-8") as f:
        if broken:
            f.write("def calc():\n    return (1 + 2\n")   # 缺右括号
        else:
            f.write("def calc():\n    return 3\n")
    return a, b


# ---------------------------------------------------------------- T1/T2
def t1_t2_multi_pipeline():
    print("\n[T1/T2] 跨文件报错 + 协同手术")
    tmp = tempfile.mkdtemp(prefix="ac_mf_")
    a, b = make_pair(tmp)
    scout = sr.Scout()
    report = scout.scan_multi([a, b])
    issues = report.get("issues") or []
    check("T1.1 检出语法错误", len(issues) >= 1, "(issues=%d)" % len(issues))
    if issues:
        check("T1.2 报告含 file_paths 批次",
              len(issues[0].get("file_paths") or []) == 2,
              str(issues[0].get("file_paths")))
        check("T1.3 指认到 mod_b.py",
              any(os.path.basename(i["file_path"]) == "mod_b.py" for i in issues))

    def fixer(source, task):
        return source.replace("return (1 + 2\n", "return (1 + 2)\n")

    endo = {"cortisol": 0.3}
    result, out = capture(lambda: sr.run_refactor_multi(
        [a, b], endo=endo, fixer=fixer))
    print("  ---- 终端输出 ----")
    for line in out.strip().splitlines():
        print("  | " + line)
    check("T2.1 流水线成功", result.get("ok") is True, str(result.get("reason")))
    check("T2.2 打印协同手术日志",
          "[Surgeon] 正在对 2 个文件进行协同手术..." in out)
    check("T2.3 打印状态机通过",
          "[Surgeon] 状态机 OBSERVED -> EDITED -> VERIFIED 验证通过。" in out)
    s_ok = sr.Surgeon()
    s_ok._lock_targets([b])
    check("T2.4 修复后 mod_b 可编译", s_ok.py_compile(b)["ok"] is True)
    with open(b, encoding="utf-8") as f:
        check("T2.5 文件内容已修复", "return (1 + 2)" in f.read())


# ---------------------------------------------------------------- T3
def t3_rollback():
    print("\n[T3] 回滚：编译失败必须恢复快照")
    tmp = tempfile.mkdtemp(prefix="ac_rb_")
    a, b = make_pair(tmp)
    originals = {}
    for p in (a, b):
        # 记录原始内容
        with open(p, encoding="utf-8") as f:
            originals[p] = f.read()

    def bad_fixer(source, task):
        # 改坏：引入新的语法错误
        return source + "\nif True print(1)\n"

    endo = {"cortisol": 0.4}
    result, out = capture(lambda: sr.run_refactor_multi(
        [a, b], endo=endo, fixer=bad_fixer))
    check("T3.1 结果为熔断", result.get("reason") == "circuit-breaker",
          str(result.get("reason")))
    same = True
    for p in (a, b):
        with open(p, encoding="utf-8") as f:
            if f.read() != originals[p]:
                same = False
    check("T3.2 两个文件都已回滚到原始内容", same)
    check("T3.3 打印回滚日志", "已回滚" in out)
    check("T3.4 皮质醇 +0.1", abs(endo["cortisol"] - 0.5) < 1e-9,
          "(%.3f)" % endo["cortisol"])


# ---------------------------------------------------------------- T4
def t4_timeout_kill():
    print("\n[T4] 超时：进程树绞杀")
    import proc_guard
    t0 = time.time()
    res = proc_guard.run_with_timeout(
        [sys.executable, "-c", "import time;time.sleep(30)"],
        timeout=2.0)
    cost = time.time() - t0
    print("     实际耗时 %.2fs" % cost)
    check("T4.1 判定为超时", res.get("timed_out") is True)
    check("T4.2 在超时点附近被终止", cost < 12.0, "(%.2fs)" % cost)
    check("T4.3 记录了绞杀方案", res.get("killed_by") in ("psutil", "native"),
          str(res.get("killed_by")))

    # 派生孙进程：验证整树被杀
    code = ("import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            "time.sleep(60)")
    t1 = time.time()
    res2 = proc_guard.run_with_timeout([sys.executable, "-c", code], timeout=2.0)
    cost2 = time.time() - t1
    check("T4.4 带子进程也能及时终止", res2.get("timed_out") is True and cost2 < 12.0,
          "(%.2fs)" % cost2)


# ---------------------------------------------------------------- T5
def t5_ast_cycle():
    print("\n[T5] AST 拦截：循环依赖")
    tmp = tempfile.mkdtemp(prefix="ac_cy_")
    a = os.path.join(tmp, "mod_a.py")
    b = os.path.join(tmp, "mod_b.py")
    with open(a, "w", encoding="utf-8") as f:
        f.write("x = 1\n")
    with open(b, "w", encoding="utf-8") as f:
        f.write("y = 2\n")

    # 补丁让 a->b 且 b->a，形成环
    proposed = {
        a: "import mod_b\nx = 1\n",
        b: "import mod_a\ny = 2\n",
    }
    ok, cycle = sr.check_circular_import([a, b], new_sources=proposed)
    check("T5.1 检测到环", ok is False and cycle is not None, str(cycle))
    check("T5.2 环路径正确",
          cycle is not None and cycle[0] == cycle[-1] and len(cycle) >= 3, str(cycle))

    report = {"issues": [{"file_path": a, "file_paths": [a, b],
                          "evidence": "SyntaxError: x", "suggested_fix": "fix",
                          "severity": 5}]}
    task, out = capture(lambda: sr.Judge().dispatch_multi(
        report, proposed_sources=proposed))
    check("T5.3 法官拒绝派发", task is None, str(task))
    check("T5.4 打印拒绝原因", "引入循环依赖" in out)

    # 无环补丁应放行
    clean = {a: "import mod_b\nx = 1\n", b: "y = 2\n"}
    task2, _ = capture(lambda: sr.Judge().dispatch_multi(
        report, proposed_sources=clean))
    check("T5.5 无环补丁正常派发", task2 is not None)


# ---------------------------------------------------------------- T6
def t6_edit_line_cap():
    print("\n[T6] 修改行数上限 100")
    tmp = tempfile.mkdtemp(prefix="ac_cap_")
    p = os.path.join(tmp, "big.py")
    # 必须带语法错误，才会进入 Surgeon 并触发行数上限
    with open(p, "w", encoding="utf-8") as f:
        f.write("def f():\n    return (1 + 2\n")
    orig = open(p, encoding="utf-8").read()

    def huge_fixer(source, task):
        # 先修好语法，再塞入 200 行 —— 总改动超过 100 行上限
        fixed = source.replace("return (1 + 2\n", "return (1 + 2)\n")
        return fixed + "\n" + "\n".join("extra_%d = 1" % i for i in range(200))

    endo = {"cortisol": 0.2}
    result, out = capture(lambda: sr.run_refactor_multi(
        [p], endo=endo, fixer=huge_fixer))
    check("T6.1 超限被拒绝", result.get("ok") is False, str(result.get("reason")))
    check("T6.2 打印超限提示", "超过上限" in out)
    check("T6.3 文件未被改动", open(p, encoding="utf-8").read() == orig)


# ---------------------------------------------------------------- T7
def t7_limits():
    print("\n[T7] 文件数上限与跨目标限制")
    tmp = tempfile.mkdtemp(prefix="ac_lim_")
    paths = []
    for i in range(4):
        p = os.path.join(tmp, "f%d.py" % i)
        with open(p, "w", encoding="utf-8") as f:
            f.write("x = %d\n" % i)
        paths.append(p)
    t = sr.Task(paths[0], "ev", "fix", file_paths=paths)
    check("T7.1 Task 最多保留 3 个文件", len(t.file_paths) == 3,
          "(%d)" % len(t.file_paths))

    s = sr.Surgeon()
    s._lock_targets(paths[:3])
    denied = False
    try:
        s.read_file(paths[3])
    except sr.PermissionDenied:
        denied = True
    check("T7.2 超出目标集合被拒绝", denied)
    check("T7.3 快照可回滚", callable(getattr(s, "rollback", None)))


def main():
    print("=" * 70)
    print(" V6.1 多文件原子手术 · 验收测试")
    print("=" * 70)
    t1_t2_multi_pipeline()
    t3_rollback()
    t4_timeout_kill()
    t5_ast_cycle()
    t6_edit_line_cap()
    t7_limits()
    print("\n" + "=" * 70)
    print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
    if FAIL:
        print(" 失败项: %s" % FAIL)
    print("=" * 70)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())