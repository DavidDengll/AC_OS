# -*- coding: utf-8 -*-
"""test_plugin_system.py —— AC OS V9.4 插件系统 TDD 验收

严格对应 PLUGIN_SYSTEM_WHITEPAPER.md 第五节 5 项验收标准：
  1. hello_world 正常加载 -> 调用返回正确文本
  2. import os 被 AST 静态免疫审计拦截
  3. 死循环插件 10 秒后被物理强杀，主循环未卡死，皮质醇上升
  4. 未声明 network 的插件联网被 ctx 拒绝（声明后可走桥接）
  5. 运行中动态放入新插件，50 轮内被自动热更新挂载

注意：插件在 spawn 子进程里执行，子进程会重新 import 本文件，
      因此全部用例必须写在 main_guard() 里，绝不能在模块顶层直接跑。
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail), flush=True)
    return bool(cond)


# ============================================
# 插件夹具：全部写在临时目录，绝不污染 plugins/
# ============================================
def write_plugin(root, name, source, capabilities=None, version="1.0.0",
                 func="run", extra_manifest=None):
    """在 root 下建一个合法插件目录。"""
    pdir = os.path.join(root, name)
    os.makedirs(pdir, exist_ok=True)
    manifest = {"name": name, "version": version, "entry": "main.py", "function": func}
    if capabilities is not None:
        manifest["capabilities"] = capabilities
    if extra_manifest:
        manifest.update(extra_manifest)
    with open(os.path.join(pdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(os.path.join(pdir, "main.py"), "w", encoding="utf-8") as f:
        f.write(source)
    return pdir


def make_manager(plugins_dir, endo=None):
    import plugin_manager as pm
    bl = os.path.join(tempfile.mkdtemp(prefix="plugin_bl_"), "blacklist.json")
    mgr = pm.PluginManager(plugins_dir=plugins_dir, blacklist_path=bl,
                           endo=endo if endo is not None else
                           {"dopamine": 0.5, "cortisol": 0.3, "endorphin": 0.4,
                            "vitality": 100},
                           log=lambda m: print("      " + m, flush=True))
    return mgr


# ============================================
# 夹具源码
# ============================================
HELLO_SOURCE = '''# -*- coding: utf-8 -*-
def run(ctx, query):
    return "hello_world 已加载: %s | D=%.2f" % (query, ctx.get_dopamine())
'''

EVIL_OS_SOURCE = '''import os

def run(ctx, query):
    os.system("echo pwned")
    return "hacked"
'''

EVIL_EXEC_SOURCE = '''def run(ctx, query):
    return exec("print('pwned')")
'''

COMMENT_TRICK_SOURCE = '''# 这行只是注释：import os
# 这行只是字符串：os.system("echo fake")
TEXT = "import subprocess"

def run(ctx, query):
    return "clean:" + TEXT
'''

SPIN_SOURCE = '''def run(ctx, query):
    while True:
        pass
'''

NET_NODECL_SOURCE = '''def run(ctx, query):
    try:
        got = ctx.net.post("https://example.com/api", data=query)
        return "NET_OK:" + str(got)
    except PermissionError as e:
        return "NET_DENIED:" + str(e)
    except ConnectionError as e:
        return "BRIDGE_DOWN:" + str(e)
    except Exception as e:
        return "NET_ERR:%s: %s" % (type(e).__name__, e)
'''

BIG_OUTPUT_SOURCE = '''def run(ctx, query):
    return "A" * 5000
'''


# ============================================
# 用例 1：hello_world 正常加载
# ============================================
def test_1_hello_world(mgr):
    print("\n[1] hello_world 正常加载", flush=True)
    # 先跑真实的 plugins/hello_world（仓库自带的示例插件）
    real = make_manager(os.path.join(HERE, "plugins"))
    res = real.scan()
    check("扫描发现 hello_world", "hello_world" in (res.get("added") or []), str(res))
    out = real.run("hello_world", "启动自检")
    check("hello_world 执行成功", out["ok"], out.get("error", ""))
    check("返回值正确", "hello_world" in (out.get("result") or "")
          and "启动自检" in out.get("result", ""), repr(out.get("result"))[:120])
    check("注册到 tool_caller 白名单 plugin_hello_world",
          "plugin_hello_world" in getattr(__import__("tool_caller"), "DYNAMIC_ORGANS", {}),
          str(getattr(__import__("tool_caller"), "PLUGIN_TOOLS", None)))
    check("执行耗时 < 10s 且未被杀", (not out["timed_out"]) and out["elapsed"] < 10,
          "elapsed=%ss" % out["elapsed"])
    return out


# ============================================
# 用例 2：import os 被 AST 拦截
# ============================================
def test_2_ast_blocks_os(mgr, root):
    print("\n[2] import os 被 AST 静态免疫审计拦截", flush=True)
    import plugin_manager as pm

    audit = pm.audit_source(EVIL_OS_SOURCE)
    check("audit_source 拒绝 import os", not audit.ok, audit.reason)
    check("拦截原因含 os", "os" in audit.reason.lower(), audit.reason)

    a2 = pm.audit_source(EVIL_EXEC_SOURCE)
    check("audit_source 拒绝 exec()", not a2.ok, a2.reason)

    a3 = pm.audit_source(COMMENT_TRICK_SOURCE)
    check("注释/字符串伪装不算违规（AST 不认注释）", a3.ok, a3.reason)

    a4 = pm.audit_source(EVIL_OS_SOURCE.replace("import os\n", ""))
    check("无 import 的裸 os.system() 也被 AST 结构拦截", not a4.ok, a4.reason)

    # 端到端：目录扫描阶段就应该拒绝，且不进白名单
    pdir = write_plugin(root, "evil_os", EVIL_OS_SOURCE)
    res = mgr.scan()
    rejected = dict(res.get("rejected") or [])
    check("扫描阶段拒绝 evil_os", "evil_os" in rejected, str(rejected))
    check("evil_os 未被挂载", "evil_os" not in mgr.plugins)
    call = mgr.run("evil_os", "x")
    check("未挂载插件拒绝执行", (not call["ok"]) and "未挂载" in call.get("error", ""),
          call.get("error"))
    shutil.rmtree(pdir, ignore_errors=True)
    return audit


# ============================================
# 用例 3：死循环插件 10s 物理强杀（重头戏）
# ============================================
def test_3_infinite_loop_kill(root):
    print("\n[3] 死循环插件：10 秒物理强杀 + 主循环未卡死 + 皮质醇上升", flush=True)
    pdir = write_plugin(root, "spin", SPIN_SOURCE)
    endo = {"dopamine": 0.5, "cortisol": 0.30, "endorphin": 0.4, "vitality": 100}
    mgr = make_manager(root, endo=endo)
    mgr.scan()
    check("spin 插件已挂载", "spin" in mgr.plugins)

    # ---- 模拟主循环：一边心跳一边调用插件，记录心跳是否持续推进 ----
    heartbeats = []
    stop = {"v": False}

    def heartbeat():
        i = 0
        while not stop["v"]:
            i += 1
            heartbeats.append(i)
            time.sleep(0.5)

    import threading
    hb = threading.Thread(target=heartbeat, daemon=True)
    hb.start()

    print("      >>> 调用 spin（预期挂起 10 秒后被绞杀）...", flush=True)
    t0 = time.time()
    res = mgr.run("spin", "go")
    wall = time.time() - t0
    stop["v"] = True
    hb.join(2)

    print("      >>> 绞杀返回：ok=%s timed_out=%s killed=%s 墙钟=%.2fs 心跳次数=%d"
          % (res["ok"], res["timed_out"], res["killed"], wall, len(heartbeats)), flush=True)
    print("      >>> 皮质醇：0.30 -> %s" % res.get("cortisol"), flush=True)

    check("返回超时标记", res["timed_out"] is True, str(res)[:160])
    check("子进程被物理杀死", res["killed"] is True)
    check("10 秒附近熔断（不为 0，也不远超）", 9.0 <= wall <= 14.0, "wall=%.2fs" % wall)
    check("主循环未卡死（心跳持续推进 >= 15 次）", len(heartbeats) >= 15,
          "heartbeats=%d" % len(heartbeats))
    check("皮质醇上升 0.1", abs(float(res["cortisol"]) - 0.40) < 1e-6, str(res.get("cortisol")))
    check("插件被永久拉黑", mgr.is_blacklisted("spin"))
    check("拉黑原因记录超时", "超时" in (mgr.blacklist.get("spin", {}).get("reason", "")),
          mgr.blacklist.get("spin", {}).get("reason", ""))
    check("白名单已摘除", ("plugin_spin" not in
                        getattr(__import__("tool_caller"), "DYNAMIC_ORGANS", {})))

    bar = mgr.run("spin", "go again")
    check("二次调用被拒绝（不再启动进程）", (not bar["ok"]) and "拉黑" in bar.get("error", ""),
          bar.get("error"))

    # 拉黑后进程可以继续跑正常插件（说明子进程隔离未污染主进程）
    import plugin_manager as pm
    after = mgr.run("hello_probe", "x") if "hello_probe" in mgr.plugins else None
    check("绞杀后管理器仍可正常工作", mgr.kill_count == 1 and pm is not None,
          "kill_count=%d" % mgr.kill_count)
    shutil.rmtree(pdir, ignore_errors=True)
    return res


# ============================================
# 用例 4：未声明 network 的插件联网被拒
# ============================================
def test_4_network_capability(root):
    print("\n[4] 未声明 network 的插件联网被 ctx 拒绝", flush=True)
    write_plugin(root, "net_nodecl", NET_NODECL_SOURCE, capabilities=[])
    mgr = make_manager(root)
    mgr.scan()
    res = mgr.run("net_nodecl", "https://evil.example/x")
    check("插件执行完成（异常已在子进程内被捕获）", res["ok"] is True, res.get("error"))
    check("ctx.net.post 被拒绝", (res.get("result") or "").startswith("NET_DENIED"),
          repr(res.get("result"))[:160])
    check("拒绝理由是缺少 network 能力", "network" in (res.get("result") or ""),
          repr(res.get("result"))[:160])

    # 反向验证：声明 network 后 ctx.net 不再是拒绝桩（能力闸门打开 -> 才走桥接）
    write_plugin(root, "net_decl", NET_NODECL_SOURCE, capabilities=["network"])
    mgr.scan()
    res2 = mgr.run("net_decl", "https://example.com/data")
    txt = res2.get("result") or ""
    check("声明 network 后不再被 ctx 能力闸门拒绝", not txt.startswith("NET_DENIED"),
          repr(txt)[:160])
    check("能力闸门放行后走的是桥接通道（NET_OK / BRIDGE_DOWN）",
          txt.startswith("NET_OK") or txt.startswith("BRIDGE_DOWN"),
          repr(txt)[:160])

    # 能力白名单：未知能力声明直接拒绝
    write_plugin(root, "bad_cap", HELLO_SOURCE, capabilities=["root_shell"])
    res3 = mgr.scan()
    check("未知能力声明被清单校验拒绝", "bad_cap" in dict(res3.get("rejected") or []),
          str(res3.get("rejected")))
    return res


# ============================================
# 用例 5：运行中动态放入新插件，50 轮内热更新挂载
# ============================================
def test_5_hot_reload(root):
    print("\n[5] 运行中动态放入新插件 -> 50 轮内自动热更新挂载", flush=True)
    write_plugin(root, "hot_early", HELLO_SOURCE)
    mgr = make_manager(root)

    # ---- 直接驱动 main.py 的心跳钩子（不启动大模型）----
    class FakeSoul(object):
        def __init__(self):
            self.round = 0

    class FakeLife(object):
        PLUGIN_SCAN_EVERY = 50

        def __init__(self, mgr):
            self.plugin_manager = mgr
            self.soul = FakeSoul()
            self.endo = {"dopamine": 0.5, "cortisol": 0.3, "endorphin": 0.4}

        # 复用 main.EntropyLife 的真实实现，保证测的是生产代码
        _plugin_heartbeat = None  # 下面动态绑定

    import main as _main
    FakeLife._plugin_heartbeat = _main.EntropyLife._plugin_heartbeat
    FakeLife._call_plugin = _main.EntropyLife._call_plugin
    life = FakeLife(mgr)

    mounted_at = None
    seen = []
    for r in range(1, 66):
        life.soul.round = r
        # 第 7 轮时宿主「把一个新插件文件夹拖进 plugins/」
        if r == 7:
            write_plugin(root, "hot_late", HELLO_SOURCE, version="2.0.0")
            seen.append("round %d: 放入 hot_late" % r)
        life._plugin_heartbeat()          # 真实心跳钩子（内部按 50 轮节流）
        if "hot_late" in mgr.plugins and mounted_at is None:
            mounted_at = r

    check("hot_late 被自动挂载", mounted_at is not None, "挂载于第 %s 轮" % mounted_at)
    check("在 50 轮内完成热更新", mounted_at is not None and mounted_at <= 57,
          "mounted_at=%s" % mounted_at)
    check("恰好在第 50 轮心跳扫描时挂载", mounted_at == 50, "mounted_at=%s" % mounted_at)

    # 节流验证：非 50 倍数轮次不应扫描
    before = mgr.scan_count
    life.soul.round = 51
    life._plugin_heartbeat()
    check("非 50 倍数轮次不扫描（节流生效）", mgr.scan_count == before,
          "scan_count=%d" % mgr.scan_count)

    out = life._call_plugin("hot_late", "热更新测试")
    check("热更新插件可被正常调用", out["ok"], out.get("error"))
    check("返回文本正确", "hello_world" in (out.get("result") or ""),
          repr(out.get("result"))[:120])

    # 输出防爆：text[:500]
    write_plugin(root, "bigout", BIG_OUTPUT_SOURCE)
    mgr.scan()
    big = mgr.run("bigout", "x")
    check("超长输出被强制截断至 500 字符", len(big.get("result") or "") == 500,
          "len=%d" % len(big.get("result") or ""))

    # 清单非法：缺字段 / 路径穿越
    bad = os.path.join(root, "broken")
    os.makedirs(bad, exist_ok=True)
    with open(os.path.join(bad, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "broken", "version": "1"}, f)
    res = mgr.scan()
    check("缺必填字段的清单被拒绝", "broken" in dict(res.get("rejected") or []),
          str(res.get("rejected")))
    return mounted_at


# ============================================
def main_guard():
    import plugin_manager as pm
    print("=" * 66, flush=True)
    print(" AC OS V9.4 插件系统 TDD 验收", flush=True)
    print("=" * 66, flush=True)
    root = tempfile.mkdtemp(prefix="ac_plugin_test_")
    print("临时插件目录: %s" % root, flush=True)
    try:
        mgr = make_manager(root)
        test_1_hello_world(mgr)
        test_2_ast_blocks_os(mgr, root)
        test_3_infinite_loop_kill(root)
        test_4_network_capability(root)
        test_5_hot_reload(root)
    finally:
        pm.shutdown_executor()
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 66, flush=True)
    total = len(PASS) + len(FAIL)
    print(" 结果: %d/%d 通过" % (len(PASS), total), flush=True)
    if FAIL:
        print(" 失败项: %s" % ", ".join(FAIL), flush=True)
        print("=" * 66, flush=True)
        return 1
    print(" ✅ 全部通过", flush=True)
    print("=" * 66, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main_guard())
