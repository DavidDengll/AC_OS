# -*- coding: utf-8 -*-
"""test_bridge_bootstrap.py —— 启动脚本桥接自举验收（不拉容器、不联网）"""
import os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
PS1 = os.path.join(ROOT, "ensure_bridge.ps1")
BAT = os.path.join(ROOT, "start_ac_os.bat")
STOP = os.path.join(ROOT, "stop_ac_os.bat")

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))
    return bool(cond)

print("=" * 66)
print(" AC OS · 启动脚本桥接自举验收")
print("=" * 66)

# T1 文件存在
print("\n[T1] 文件就位")
check("T1.1 ensure_bridge.ps1 存在", os.path.exists(PS1))
check("T1.2 start_ac_os.bat 存在", os.path.exists(BAT))

# T2 PowerShell 语法可解析（BOM + 解析）
print("\n[T2] ensure_bridge.ps1 语法/编码")
raw = open(PS1, "rb").read()
check("T2.1 带 UTF-8 BOM（否则 PS5.1 解析中文报错）",
      raw[:3] == b"\xef\xbb\xbf", str(raw[:3]))
r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command",
                    "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$null,[ref]$e); if($e.Count){$e[0].Message}else{'OK'}" % PS1],
                   capture_output=True, text=True, timeout=60)
check("T2.2 PowerShell 解析通过", "OK" in (r.stdout or ""), (r.stdout or r.stderr)[:120])

# T3 start_ac_os.bat 在 compose up 之前调用桥接脚本
print("\n[T3] 启动顺序：先桥接，后容器")
bat = open(BAT, encoding="utf-8", errors="replace").read()
i_bridge = bat.find("ensure_bridge.ps1")
i_compose = bat.find("compose up -d")
check("T3.1 bat 中调用了 ensure_bridge.ps1", i_bridge >= 0)
check("T3.2 桥接调用在 compose up 之前", 0 <= i_bridge < i_compose,
      "bridge=%d compose=%d" % (i_bridge, i_compose))
check("T3.3 处理了返回码 0/1/2（含端口占用不死锁）",
      "BRC" in bat and '"2"' in bat and '"1"' in bat)
check("T3.4 无窗口静默（Bypass + NoProfile）",
      "-ExecutionPolicy Bypass" in bat and "-NoProfile" in bat)

# T4 stop 脚本会清理桥接
print("\n[T4] 停止脚本清理桥接")
stop = open(STOP, encoding="utf-8", errors="replace").read()
check("T4.1 stop 脚本会查找 host_agent_bridge 进程",
      "host_agent_bridge" in stop)

# T5 幂等：连续两次调用返回 0
print("\n[T5] 幂等性（连续两次都应 exit 0）")
codes = []
for i in range(2):
    p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", PS1, "-Quiet"],
                       capture_output=True, text=True, timeout=120)
    codes.append(p.returncode)
    print("  run #%d rc=%s" % (i + 1, p.returncode))
check("T5.1 两次调用均返回 0", codes == [0, 0], str(codes))

# T6 端口确实处于监听
print("\n[T6] 端口就绪")
out = subprocess.run(["powershell", "-NoProfile", "-Command",
                      "(Get-NetTCPConnection -LocalPort 5555 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count"],
                     capture_output=True, text=True, timeout=60)
check("T6.1 5555 正在监听", (out.stdout or "").strip().isdigit() and int(out.stdout.strip()) > 0,
      (out.stdout or "").strip())

print("\n" + "=" * 66)
print(" 结果: %d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL: print(" 失败项:", FAIL)
print("=" * 66)
sys.exit(0 if not FAIL else 1)
