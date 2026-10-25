# test_virtual.py
import sys
import os
import time
sys.path.insert(0, os.path.dirname(__file__))

from virtual_env import VirtualEnvironment
from main import ConsciousnessSystem
from planner import Planner

class VirtualTestRunner:
    def __init__(self, size=5, max_rounds=100):
        self.env = VirtualEnvironment(size=size)
        self.system = ConsciousnessSystem()
        self.system.visual.see = self.env.see
        self.system.visual.mode = "virtual"
        self.max_rounds = max_rounds
        self.round = 0
        self.planner = Planner()
        self.last_output = ""  # 记录熵灵上一轮的输出

    def _print_grid(self, state):
        size = state["size"]
        agent = state["agent"]
        items = state["items"]
        item_map = {}
        for item in items:
            item_map[(item["x"], item["y"])] = item["name"][0]

        print(f"┌{'───' * size}┐")
        for x in range(size):
            row = "│"
            for y in range(size):
                if [x, y] == [agent["x"], agent["y"]]:
                    row += " 🤖 "
                elif (x, y) in item_map:
                    row += f" {item_map[(x, y)]}  "
                else:
                    row += " ·  "
            row += "│"
            print(row)
        print(f"└{'───' * size}┘")

    def run(self):
        print("=" * 60)
        print("🧠 熵灵虚拟环境测试 (自然语言交互)")
        print(f"   网格大小: {self.env.size}×{self.env.size}")
        print(f"   最大轮数: {self.max_rounds}")
        print("=" * 60)

        scene = self.env.see()
        self.last_output = ""

        while self.round < self.max_rounds:
            self.round += 1
            print(f"\n🔂 第 {self.round} 轮")
            print("-" * 40)

            # 运行熵灵核心一轮
            self.system.run_once()
            new_output = getattr(self.system, "last_final_output", "")

            # 只用熵灵的输出做规划，第一轮不说话就不动
            if new_output and new_output != self.last_output:
                action_plan = self.planner.plan(new_output)
                self.last_output = new_output

                if action_plan.get("status") == "success":
                    for act in action_plan["actions"]:
                        verb = act.get("action", "")
                        target = act.get("target", "")

                        direction_map = {
                            "上移": "向北移动", "下移": "向南移动",
                            "左移": "向西移动", "右移": "向东移动",
                        }
                        if verb in direction_map:
                            action_text = direction_map[verb]
                        elif verb in ["抓", "拿", "取", "捡起", "抓取"]:
                            action_text = f"抓取{target}" if target else "抓取"
                        elif verb in ["放", "放下", "给出", "递"]:
                            action_text = f"放下{target}" if target else "放下"
                        elif verb in ["看", "观察", "查看", "检查"]:
                            action_text = "观察周围"
                        else:
                            action_text = f"{verb} {target}".strip()

                        scene, success = self.env.execute(action_text)
                        status = "✅" if success else "❌"
                        print(f"   {status} {action_text}")
            else:
                print("   🤫 熵灵本轮未发言，不执行动作")

            # 显示当前状态
            state = self.env.get_state()
            self._print_grid(state)
            print(f"👁️ {scene}")
            if new_output:
                print(f"💬 熵灵: {new_output[:200]}")
            emo = self.system.emotion.get_state()
            print(f"📊 精力:{emo['energy']:.2f} 好奇:{emo['curiosity']:.2f} 愉悦:{emo['pleasure']:.2f}")

            # 物品太少自动重置
            if len(state["items"]) <= 1 and len(state["inventory"]) == 0:
                print("\n🔄 物品稀少，自动重置...")
                scene = self.env.reset()
                self.system.visual.see = self.env.see
                self.last_output = ""

            time.sleep(0.3)

        print("\n" + "=" * 60)
        print("✅ 测试完成")
        self.system.close()


if __name__ == "__main__":
    runner = VirtualTestRunner(size=5, max_rounds=100)
    try:
        runner.run()
    except KeyboardInterrupt:
        print("\n👋 手动中断")
    finally:
        runner.system.close()