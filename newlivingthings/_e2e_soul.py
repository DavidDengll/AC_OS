# -*- coding: utf-8 -*-
"""真实端到端：真 Ollama + 真主循环，验证 [人格审查] 逻辑被触发。"""
import os, sys, tempfile
tmp = tempfile.mkdtemp(prefix="ac_e2e_")
os.environ["AC_DB_PATH"] = os.path.join(tmp, "e2e.db")
os.environ["AC_DEAD_LOCK"] = os.path.join(tmp, "dead.lock")
os.environ["AC_TEST_MODE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

import config
import soul_core
soul_core.REFLECT_EVERY_N = 4          # 为演示加速：每 4 轮审查一次
config.REAL_WORLD_ENABLED = False      # 验收期间不真的出网
import main

print("=" * 60, flush=True)
print(" 真实 E2E：轮数阈值=%d，模型=%s" % (soul_core.REFLECT_EVERY_N, config.MODEL_NAME), flush=True)
print(" 临时库: %s" % os.environ["AC_DB_PATH"], flush=True)
print("=" * 60, flush=True)

life = main.EntropyLife(interactive=False)
life._check_death()
try:
    for i in range(8):
        print("\n第 %d 轮:" % (i + 1), flush=True)
        try:
            res = life.run_cycle()
        except Exception as e:
            print("[容错] 本轮异常已隔离: %s" % e, flush=True)
            continue
        r = res.get("reflection")
        print("[E2E %02d] 生命值=%d | 审查=%s | top3=%s" % (
            i + 1, life.soul.vitality, (r or {}).get("action"), life.soul.tags_text(3)), flush=True)
finally:
    print("\n全景 Prompt 示例：", flush=True)
    print(life.build_panorama_prompt("猫"), flush=True)
    life.close()
print("\nE2E 结束：生命值=%d，人格=%s" % (life.soul.vitality, life.soul.tags_text(3)), flush=True)
