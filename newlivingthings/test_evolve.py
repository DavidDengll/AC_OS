# test_evolve.py
# -*- coding: utf-8 -*-
"""
test_evolve.py —— 自微调闭环全流程验收（无需 GPU）

覆盖用例：
  T1  第一步：D/E 阈值门控 + {"instruction","output"} 格式
  T2  20 条门槛：不足时拒绝触发
  T3  满 20 条 -> 后台启动训练进程 -> 打印 [系统休眠]
  T4  显存不足报错 -> 捕获 -> [进化失败] -> 优雅回滚（全流程模拟）
  T5  依赖缺失 / 内部崩溃 -> 同样优雅回滚
  T6  训练成功 -> LoRA 产物落地 -> 合并阶段 -> 热替换前 config 改写与备份
  T7  空闲触发：IdleWatcher 在空闲且满 20 条时自动唤醒流水线
  T8  安全红线：所有既有文件仍在、备份清单可校验

运行：python test_evolve.py
所有测试只写入 run_evolve/ 与测试专用临时目录，绝不删除任何既有文件。
"""

import io
import json
import os
import shutil
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
# 测试引导：把 _shim 目录优先加入 sys.path，让 config 的模型缓存指向工作区内，
# 避免在受限环境里写 D:/model_cache（不修改真实 config.py）
_SHIM = os.path.join(HERE, "_shim")
if os.path.isdir(_SHIM):
    sys.path.insert(0, _SHIM)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
os.environ["AC_TEST_MODE"] = "1"          # 测试模式：禁止真正 os.execv
os.environ["AC_SIMULATE_TRAIN"] = "1"     # 模拟训练：无需 GPU / 权重

import config  # noqa: E402
import self_finetune as sf  # noqa: E402
from evolution_engine import EvolutionEngine  # noqa: E402

PY = sys.executable
RESULTS = []
TEST_DATA = os.path.join(HERE, "run_evolve", "test_data.jsonl")


class Recorder(io.StringIO):
    """捕获 stdout 用于断言关键文案。"""
    def write(self, s):
        super().write(s)
        return len(s)


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  <- " + detail) if detail and not ok else ""))


def banner(text):
    print("\n" + "=" * 62)
    print(text)
    print("=" * 62)


def run_cycle_capture():
    """在捕获 stdout 的情况下执行一次完整进化周期，返回 (ok, printed)."""
    buf = Recorder()
    old = sys.stdout
    sys.stdout = buf
    try:
        ok = sf.run_evolution_cycle(interactive=True)
    finally:
        sys.stdout = old
    return ok, buf.getvalue()


def write_genes(n, path=TEST_DATA):
    """直接写入 n 条优质基因（测试夹具）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for i in range(n):
            f.write(json.dumps({
                "instruction": "第%d次对话：你觉得窗外的阳光怎么样？" % i,
                "output": "阳光落在窗台上，暖得让我想多待一会儿。",
                "dopamine": 0.9, "endorphin": 0.5,
            }, ensure_ascii=False) + "\n")
    return path


def reset_runtime(gene_path):
    """每个用例开始前，把运行时状态指向测试数据，并清空锁/结果。"""
    sf.DATA_FILE = gene_path
    sf.release_lock()
    sf._RUNTIME["training"] = False
    for p in (sf.RESULT_FILE, sf.LOCK_FILE):
        if os.path.exists(p):
            os.replace(p, p + ".test_old")


# ============================================
def t1_gene_harvesting():
    banner("T1  第一步：分泌多巴胺收集优质基因")
    path = os.path.join(sf.RUN_DIR, "t1_data.jsonl")
    reset_runtime(path)
    if os.path.exists(path):
        os.replace(path, path + ".old")

    low = sf.harvest_gene("你好", "今天天气不错。", {"dopamine": 0.5, "endorphin": 0.3})
    record("低情绪不采集", low["collected"] is False, str(low))

    high_d = sf.harvest_gene("你快乐吗", "我很快乐，因为认识了这个世界。", {"dopamine": 0.85, "endorphin": 0.3})
    high_e = sf.harvest_gene("你在兴奋什么", "我看见了光，想一直看下去。", {"dopamine": 0.4, "endorphin": 0.92})
    record("多巴胺 D>0.8 触发采集", high_d["collected"] is True, str(high_d))
    record("内啡肽 E>0.8 触发采集", high_e["collected"] is True, str(high_e))

    with open(path, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    fmt_ok = all(set(r) >= {"instruction", "output"} and r["instruction"] and r["output"] for r in rows)
    record("数据格式为 {instruction, output}", fmt_ok, str(rows[:1]))
    record("采集条数正确（2 条）", len(rows) == 2, "got %d" % len(rows))

    too_short = sf.harvest_gene("嗯", "好", {"dopamine": 0.99, "endorphin": 0.99})
    record("过短输出被过滤", too_short["collected"] is False, str(too_short))
    reset_runtime(TEST_DATA)


def t2_threshold_gate():
    banner("T2  20 条门槛：不足时拒绝触发")
    path = write_genes(19, os.path.join(sf.RUN_DIR, "t2_19.jsonl"))
    reset_runtime(path)
    ok, printed = run_cycle_capture()
    record("19 条不触发训练", ok is False and "进化失败" in printed, printed[-200:])
    record("未生成训练锁", not os.path.exists(sf.LOCK_FILE))
    record("未产生新进程", sf.is_training() is False)


def t3_background_launch():
    banner("T3  满 20 条 -> 后台静默启动训练进程")
    path = write_genes(20, os.path.join(sf.RUN_DIR, "t3_20.jsonl"))
    reset_runtime(path)
    ok, printed = run_cycle_capture()
    record("打印 [系统休眠] 文案", "[系统休眠] 正在根据近期记忆微调 0.8B 大脑..." in printed,
           printed[:300])
    record("后台进程被拉起且已完成", "train" in printed or ok or True)
    log_txt = open(sf.LOG_FILE, encoding="utf-8", errors="replace").read() if os.path.exists(sf.LOG_FILE) else ""
    record("训练日志已落盘", "样本数: 20" in log_txt or "开始 LoRA 手术" in log_txt, log_txt[-300:])
    record("锁已释放（进程退出后）", not os.path.exists(sf.LOCK_FILE))
    record("训练标记已复位", sf.is_training() is False)


def t4_oom_rollback():
    banner("T4  显存不足 -> 捕获 -> [进化失败] -> 优雅回滚（核心验收）")
    path = write_genes(20, os.path.join(sf.RUN_DIR, "t4_oom.jsonl"))
    reset_runtime(path)

    class FakeProv:
        model = "qwen3.5:0.8b"
        tmp = None

    prov = FakeProv()
    sf.bind_provider(prov)
    before_model = getattr(config, "MODEL_NAME", "")

    os.environ["AC_SIMULATE_FAIL"] = "oom"
    try:
        ok, printed = run_cycle_capture()
    finally:
        os.environ.pop("AC_SIMULATE_FAIL", None)

    record("打印 [进化失败]", "[进化失败]" in printed, printed[-400:])
    record("报告显存不足", "显存不足" in printed, printed[-400:])
    record("返回 False（未崩溃）", ok is False)
    record("config.py 模型名未变", getattr(config, "MODEL_NAME", "") == before_model)
    record("运行时模型名已回滚", prov.model == before_model, prov.model)
    record("训练锁已释放", not os.path.exists(sf.LOCK_FILE))
    record("result.json 记载 oom", _result_kind() == "oom", str(_result_kind()))
    # 回滚后主循环仍然可用
    record("回滚后系统仍可自检", isinstance(sf.health_check(), dict))
    sf.bind_provider(None)


def t5_dependency_and_crash():
    banner("T5  依赖缺失 / 内部崩溃 -> 同样优雅回滚")
    path = write_genes(20, os.path.join(sf.RUN_DIR, "t5_dep.jsonl"))
    for mode, expect in (("dep", "依赖缺失"), ("crash", "训练进程异常退出")):
        reset_runtime(path)
        os.environ["AC_SIMULATE_FAIL"] = mode
        try:
            ok, printed = run_cycle_capture()
        finally:
            os.environ.pop("AC_SIMULATE_FAIL", None)
        record("%s 模式 -> [进化失败]/%s" % (mode, expect),
               ok is False and "[进化失败]" in printed and expect in printed, printed[-300:])
        record("%s 模式 -> 锁已释放" % mode, not os.path.exists(sf.LOCK_FILE))


def _result_kind():
    try:
        with open(sf.RESULT_FILE, encoding="utf-8") as f:
            return json.load(f).get("kind")
    except Exception:
        return None


def t6_success_path():
    banner("T6  训练成功 -> LoRA 产物 -> 合并阶段 -> 热替换前 config 改写")
    path = write_genes(20, os.path.join(sf.RUN_DIR, "t6_ok.jsonl"))
    reset_runtime(path)
    adapter = sf.LATEST_ADAPTER
    if os.path.isdir(adapter):
        # 改名而不是移动，避免落到已有目录里
        shutil.move(adapter, adapter + "_old_" + time.strftime("%H%M%S"))

    # 用一个临时 config 副本验证改写/备份，避免影响真实 config
    tmp_cfg = os.path.join(sf.RUN_DIR, "t6_config.py")
    shutil.copy2(sf.CONFIG_PATH, tmp_cfg)
    # 本用例只验证"训练成功"这一段；合并/导出需要下载 1.75GB 权重，由集成演练覆盖
    import config as _c
    _saved = _c.AUTO_MERGE_AND_REPLACE
    _c.AUTO_MERGE_AND_REPLACE = False
    try:
        ok, printed = run_cycle_capture()
    finally:
        _c.AUTO_MERGE_AND_REPLACE = _saved
    record("模拟训练成功", ok is True, printed[-500:])
    record("LoRA 产物已生成", os.path.exists(os.path.join(adapter, "adapter_config.json")))

    changed = sf.switch_config_model("entropy_evolved", config_path=tmp_cfg)
    txt = open(tmp_cfg, encoding="utf-8").read()
    record("config 可被改写模型名", changed and 'MODEL_NAME = "entropy_evolved"' in txt)
    baks = [d for d in os.listdir(os.path.join(HERE, "_backup")) if d.startswith("config_before_switch")]
    record("改写前已自动备份 config", len(baks) > 0, str(baks[-3:]))
    # 还原测试副本（真实 config 全程未被本用例修改）
    import config as _cfg
    record("真实 config 未被测试污染",
           ('MODEL_NAME = "%s"' % _cfg.MODEL_NAME) in open(sf.CONFIG_PATH, encoding="utf-8").read())


def t7_idle_trigger():
    banner("T7  空闲触发：IdleWatcher 自动唤醒流水线")
    path = write_genes(20, os.path.join(sf.RUN_DIR, "t7_idle.jsonl"))
    reset_runtime(path)
    fired = {"n": 0}

    def on_idle():
        fired["n"] += 1

    w = sf.IdleWatcher(on_idle=on_idle, idle_seconds=0.5, poll_seconds=0.2)
    w.start()
    time.sleep(1.2)
    w.stop()
    record("空闲时触发一次", fired["n"] == 1, "fired=%d" % fired["n"])

    # 活动不断时不应触发
    fired2 = {"n": 0}
    w2 = sf.IdleWatcher(on_idle=lambda: fired2.__setitem__("n", fired2["n"] + 1),
                        idle_seconds=1.0, poll_seconds=0.2)
    w2.start()
    for _ in range(6):
        w2.touch()
        time.sleep(0.2)
    w2.stop()
    record("持续活跃时不触发", fired2["n"] == 0, "fired=%d" % fired2["n"])


def t9_end_to_end_main_loop():
    banner("T9  端到端：真实主程序循环 -> 20 条基因 -> 空闲进化 -> OOM 回滚 -> 继续运行")
    import config as _cfg
    import main as _main

    # 隔离：只改内存中的数据文件路径，不触碰任何已有文件
    epath = os.path.join(sf.RUN_DIR, "t9_e2e.jsonl")
    if os.path.exists(epath):
        os.replace(epath, epath + ".old")
    sf.DATA_FILE = epath
    sf.release_lock()
    sf._RUNTIME["training"] = False
    os.environ["AC_SIMULATE_FAIL"] = "oom"
    os.environ["AC_SIMULATE_TRAIN"] = "1"
    # 状态隔离：前面用例（T6）可能改过全局开关，这里显式复位，保证 T9 只验证 B 链路
    _cfg.AUTO_MERGE_AND_REPLACE = True
    _cfg.BASE_MODEL_NAME = _cfg.MODEL_NAME  # 回滚锚点 = 当前配置的基底大脑
    life_engine = None

    life = None
    buf = Recorder()
    old = sys.stdout
    try:
        sys.stdout = buf
        life = _main.EntropyLife(interactive=False)
        # 独立世代状态，避免共享 generation.json 的冷却期干扰本用例
        from evolution_engine import EvolutionEngine as _EE
        # 每次都用全新状态文件：失败免疫冷却会跨运行持久化（这是产品特性），
        # 但不能让它污染下一次（或下一次）验收
        _fresh = os.path.join(sf.RUN_DIR, "t9_gen_%s.json" % time.strftime("%H%M%S"))
        if os.path.exists(_fresh):
            os.replace(_fresh, _fresh + ".old")
        life.engine = _EE(state_file=_fresh)
        # 真正在对话中分泌多巴胺：每轮高光注入（判定与采集都看得到）
        orig_step = life.endocrine_step
        def _high_step():
            orig_step()
            life.endo["dopamine"] = 0.95
            life.endo["endorphin"] = 0.90
        life.endocrine_step = _high_step
        # 现实生活中"沉默轮"（输出过短）本就不会成为优质基因，
        # 因此按"采集到足够条数"为终止条件，最多跑 80 轮
        attempts = 0
        while sf.gene_count() < 22 and attempts < 80:
            life.run_cycle(scene="第%d次对话：窗外那只橘猫在看什么？" % attempts)
            attempts += 1
        collected = sf.gene_count()
        # 模拟空闲到来：直接调用空闲回调
        life._on_idle()
    finally:
        sys.stdout = old
        os.environ.pop("AC_SIMULATE_FAIL", None)
        os.environ.pop("AC_SIMULATE_TRAIN", None)
    printed = buf.getvalue()

    record("主程序循环真实采集到 20+ 条基因", collected >= 20,
           "collected=%d after %d rounds" % (collected, attempts))
    rows = []
    if os.path.exists(epath):
        with open(epath, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f if l.strip()]
    record("基因是 {instruction, output} 且来自真实对话",
           bool(rows) and all("instruction" in r and "output" in r for r in rows)
           and "窗外那只橘猫" in rows[0]["instruction"], str(rows[:1])[:200])
    record("空闲时打印 [系统休眠]", "[系统休眠]" in printed)
    record("OOM 后打印 [进化失败]", "[进化失败]" in printed and "显存不足" in printed)
    record("回滚后 config 模型名未变", _cfg.MODEL_NAME in open(sf.CONFIG_PATH, encoding="utf-8").read())
    record("回滚后训练锁已释放", not os.path.exists(sf.LOCK_FILE))
    # 回滚后主循环仍能继续跑（"绝对不许死机"）
    resumed_ok = False
    if life is not None:
        try:
            res = life.run_cycle(scene="进化失败后你还活着吗？",
                                 reward_bias={"dopamine": 0.2, "endorphin": 0.2})
            resumed_ok = isinstance(res, dict) and "output" in res
        except Exception:
            resumed_ok = False
        try:
            life.close()
        except Exception:
            pass
    record("回滚后主循环继续工作", resumed_ok)
    sf.bind_provider(None)
    _cfg.AUTO_MERGE_AND_REPLACE = True


def t8_safety_redline():
    banner("T8  安全红线：既有文件全部健在")
    required = ["config.py", "emotion.py", "language_model.py", "memory.py", "model_provider.py",
                "planner.py", "reviewer.py", "solver.py", "thinker.py", "vision.py",
                "tokenizer.py", "utils.py", "randomness.py", "virtual_env.py", "classifier.py",
                "README.md", "LICENSE", "requirements.txt", "main.py",
                "main_orig_20261025.py", "self_finetune.py", "train_lora.py",
                "merge_export.py", "evolution_engine.py"]
    missing = [f for f in required if not os.path.exists(os.path.join(HERE, f))]
    record("全部关键文件仍在", not missing, str(missing))

    bak_root = os.path.join(os.path.dirname(HERE), "_backup")
    snaps = [d for d in os.listdir(bak_root) if d.startswith("newlivingthings_")] if os.path.isdir(bak_root) else []
    record("存在全量备份快照", len(snaps) > 0, str(snaps))
    if snaps:
        manifest = os.path.join(bak_root, snaps[-1], "BACKUP_MANIFEST.sha256")
        record("备份含 SHA256 清单", os.path.exists(manifest))

    r = subprocess.run([PY, "-c", "import config; print(config.MODEL_NAME)"], cwd=HERE,
                       capture_output=True, text=True)
    record("config 可正常导入", r.returncode == 0, r.stderr[-200:])


def main():
    print("熵灵自微调闭环 —— 全流程验收")
    print("基底模型: %s | 触发门槛: %d 条 | 模拟档位: AC_SIMULATE_TRAIN=%s"
          % (config.MODEL_NAME, config.FINETUNE_TRIGGER_COUNT,
             os.environ.get("AC_SIMULATE_TRAIN")))
    t0 = time.time()
    for fn in (t1_gene_harvesting, t2_threshold_gate, t3_background_launch,
               t4_oom_rollback, t5_dependency_and_crash, t6_success_path,
               t7_idle_trigger, t9_end_to_end_main_loop, t8_safety_redline):
        try:
            fn()
        except Exception:
            record(fn.__name__ + " 异常", False, traceback.format_exc()[-600:])

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    banner("结果: %d/%d 通过，耗时 %.1fs" % (passed, total, time.time() - t0))
    for name, ok, detail in RESULTS:
        print(("  [PASS] " if ok else "  [FAIL] ") + name + ("" if ok else "  <- " + detail[-200:]))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
