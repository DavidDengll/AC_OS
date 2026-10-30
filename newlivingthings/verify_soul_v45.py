# -*- coding: utf-8 -*-
"""
verify_soul_v45.py —— 熵灵 V4.5 灵魂级重构 · 一键验收

依次执行：
  1) 单元/集成验收：test_soul_v45.py（隔离临时库，不碰真实数据）
  2) 死亡与复活验证：真实 spend/terminate 路径 -> dead.lock -> 进程退出 -> 重启被拦截
  3) 真实大脑端到端：真 Ollama 跑主循环，观察 [人格审查] 日志（可选，慢）

用法：
    python verify_soul_v45.py              # 1 + 2
    python verify_soul_v45.py --with-e2e   # 1 + 2 + 3（需要本地 Ollama）
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(title, cmd, env=None):
    print("\n" + "=" * 70)
    print(" " + title)
    print("=" * 70, flush=True)
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    if env:
        e.update(env)
    p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=e)
    out = (p.stdout or "") + (p.stderr or "")
    print(out[-6000:], flush=True)
    print("[退出码] %s" % p.returncode, flush=True)
    return p.returncode, out


def death_and_resurrection():
    print("\n" + "=" * 70)
    print(" 死亡与复活验证（真实 spend -> terminate -> dead.lock -> 重启拦截）")
    print("=" * 70, flush=True)
    tmp = tempfile.mkdtemp(prefix="ac_verify_")
    env = {"AC_DB_PATH": os.path.join(tmp, "v.db"),
           "AC_DEAD_LOCK": os.path.join(tmp, "dead.lock")}
    lock = env["AC_DEAD_LOCK"]
    ok = True

    # 1) 真实扣血至 0 + 真实死亡链
    rc, out = run("步骤 1：生命值 25 -> 连续工具失败 -> 归零 -> terminate()",
                  [PY, "-X", "utf8", os.path.join(HERE, "_stress_death.py")], env)
    ok &= (rc != 0) and ("不应走到这里" not in out) and os.path.exists(lock)
    print("[检查] dead.lock 存在: %s" % os.path.exists(lock))

    # 2) 重启被拦截
    code = ("import os,sys;sys.path.insert(0,os.environ['AC_HERE']);"
            "import soul_core;sys.exit(0 if soul_core.guard_dead_lock() else 3)")
    rc2, out2 = run("步骤 2：模拟 Docker 重启 -> guard_dead_lock 拦截",
                    [PY, "-X", "utf8", "-c", code], dict(env, AC_HERE=HERE))
    ok &= (rc2 == 0) and ("熵灵已死" in out2)
    print("[检查] 重启被阻止: %s" % (rc2 == 0 and "熵灵已死" in out2))

    print("\n结果：%s" % ("PASS ✅" if ok else "FAIL ❌"))
    return ok


def main():
    argv = sys.argv[1:]
    rc1, _ = run("1) 单元/集成验收 test_soul_v45.py",
                 [PY, "-X", "utf8", os.path.join(HERE, "test_soul_v45.py")])
    ok2 = death_and_resurrection()
    ok3 = True
    if "--with-e2e" in argv:
        rc3, _ = run("3) 真实大脑端到端（真 Ollama，较慢）",
                     [PY, "-X", "utf8", os.path.join(HERE, "_e2e_soul.py")])
        ok3 = rc3 == 0

    print("\n" + "#" * 70)
    print("# 总体：单元=%s  死亡/复活=%s  端到端=%s" % (
        "PASS" if rc1 == 0 else "FAIL", "PASS" if ok2 else "FAIL",
        "SKIP" if "--with-e2e" not in argv else ("PASS" if ok3 else "FAIL")))
    print("#" * 70)
    return 0 if (rc1 == 0 and ok2 and ok3) else 1


if __name__ == "__main__":
    sys.exit(main())
