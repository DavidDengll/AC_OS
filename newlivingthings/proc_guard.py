# proc_guard.py
# -*- coding: utf-8 -*-
"""
proc_guard.py —— 进程树绞杀与受限编译（V6.1 物理防爆）

职责：
  run_with_timeout()：在子进程中执行命令，超过 timeout 秒则
                      **杀掉整个进程树**（含所有子进程），确保 CPU 立刻回落。

为什么需要：
  Docker 内执行 py_compile / 自检时，若子进程卡死或派生僵尸，
  单纯的 proc.kill() 只杀父进程，子进程会成为孤儿继续烧 CPU。
  这里用「子进程组 + 系统原生命令」做整树绞杀：
    - Windows：taskkill /T /F /PID（/T 递归终止子进程）
    - POSIX  ：start_new_session=True 建独立进程组，再 os.killpg 杀整组
    - 若环境有 psutil，则优先用 psutil 递归遍历子孙进程兜底清理
"""

import os
import signal
import subprocess
import sys

DEFAULT_TIMEOUT = 15.0


def _log(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass


def _kill_tree_psutil(pid):
    """优先方案：用 psutil 递归杀子孙进程。返回是否执行成功。"""
    try:
        import psutil
    except Exception:
        return False
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for c in children:
            try:
                c.kill()
            except Exception:
                pass
        try:
            parent.kill()
        except Exception:
            pass
        try:
            psutil.wait_procs(children + [parent], timeout=3)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _kill_tree_native(pid, proc=None):
    """原生兜底：Windows 用 taskkill /T /F；POSIX 用 killpg。"""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=10)
            return True
        # POSIX：优先杀进程组（start_new_session 已保证是独立组）
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return True
        except Exception:
            os.kill(pid, signal.SIGKILL)
            return True
    except Exception:
        # 最后手段：杀直接子进程
        try:
            if proc is not None:
                proc.kill()
        except Exception:
            pass
        return False


def kill_process_tree(pid, proc=None):
    """杀掉 pid 及其全部子进程。返回使用的方案名。"""
    if _kill_tree_psutil(pid):
        return "psutil"
    if _kill_tree_native(pid, proc):
        return "native"
    return "failed"


def run_with_timeout(cmd, timeout=DEFAULT_TIMEOUT, cwd=None):
    """执行命令，超时则绞杀整个进程树。

    返回 dict:
        ok        是否在超时前正常完成（returncode == 0）
        timed_out 是否超时被杀
        returncode
        stdout / stderr
        killed_by 绞杀方案（psutil / native / failed），未超时为 None
    """
    timeout = float(timeout) if timeout else DEFAULT_TIMEOUT
    popen_kw = {}
    if os.name != "nt":
        # 建独立进程组，便于整组绞杀
        popen_kw["start_new_session"] = True
    else:
        # Windows：独立进程组，避免 Ctrl+C 干扰；绞杀靠 taskkill /T
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=cwd, **popen_kw)
    except Exception as e:
        return {"ok": False, "timed_out": False, "returncode": -1,
                "stdout": "", "stderr": "启动失败: %s" % e, "killed_by": None}

    try:
        out, err = proc.communicate(timeout=timeout)
        return {"ok": proc.returncode == 0, "timed_out": False,
                "returncode": proc.returncode,
                "stdout": (out or b"").decode("utf-8", "replace"),
                "stderr": (err or b"").decode("utf-8", "replace"),
                "killed_by": None}
    except subprocess.TimeoutExpired:
        _log("[绞杀] 超过 %.1fs，开始终止进程树 PID=%s" % (timeout, proc.pid))
        killed_by = kill_process_tree(proc.pid, proc)
        # 回收管道，防止缓冲区占满
        try:
            out, err = proc.communicate(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            out, err = b"", b""
        _log("[绞杀] 进程树已终止（方案=%s）" % killed_by)
        return {"ok": False, "timed_out": True, "returncode": -9,
                "stdout": (out or b"").decode("utf-8", "replace"),
                "stderr": (err or b"").decode("utf-8", "replace"),
                "killed_by": killed_by}


def compile_file(path, timeout=DEFAULT_TIMEOUT):
    """受限编译：独立子进程执行编译，带进程树超时锁。"""
    code = "import sys,py_compile;py_compile.compile(sys.argv[1],doraise=True)"
    return run_with_timeout([sys.executable, "-c", code, path], timeout=timeout)
