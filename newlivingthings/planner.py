# planner.py
from model_provider import get_provider
import json
import re
import time

class Planner:
    ACTION_VERBS = {
        "移动", "走", "跑", "跳", "爬", "前进", "后退", "转", "停",
        "抓", "拿", "放", "推", "拉", "举", "搬", "扔", "抛", "取", "递",
        "看", "观察", "查看", "检查", "摸", "触摸", "碰",
        "按", "压", "拧", "转动", "旋转",
        "打开", "关闭", "开启", "合上",
        "捡起", "放下", "拿起", "给出", "接住",
        "走向", "来到", "靠近", "离开",
    }

    ACTION_ORDER = {
        "移动": 1, "走": 1, "跑": 1, "前进": 1, "后退": 1,
        "走向": 1, "来到": 1, "靠近": 1, "离开": 1,
        "看": 2, "观察": 2, "查看": 2, "检查": 2,
        "摸": 3, "触摸": 3, "碰": 3,
        "抓": 4, "拿": 4, "取": 4, "捡起": 4, "拿起": 4,
        "举": 5, "搬": 5, "推": 5, "拉": 5,
        "放": 6, "放下": 6, "给出": 6, "递": 6, "接住": 6,
        "按": 7, "压": 7, "拧": 7, "转动": 7, "旋转": 7,
        "打开": 8, "关闭": 8, "开启": 8, "合上": 8,
    }

    def __init__(self):
        self.provider = get_provider()

    def _has_physical_action(self, text):
        return any(verb in text for verb in self.ACTION_VERBS)

    def _sort_actions(self, actions):
        return sorted(actions, key=lambda x: self.ACTION_ORDER.get(x.get("action", ""), 99))

    def plan(self, text, scene_description=""):
        print(f"规划者正在分析: {text}")
        if not self._has_physical_action(text):
            print("规则判断：无需物理动作，跳过 API 调用")
            return {"intent": "无需物理动作", "actions": [], "status": "no_physical_action"}

        for attempt in range(2):
            try:
                prompt = f"""你是一个机器人动作规划师。
你的任务是根据一段话，推理出说话者的意图，并将其拆解为具体的可执行动作步骤。

当前场景：{scene_description if scene_description else "未知"}

说话内容：{text}

请严格按以下JSON格式返回（不要其他内容）：
{{"intent":"意图描述","actions":[{{"action":"动作名称","target":"操作对象","reason":"原因"}}],"status":"success/cannot_execute"}}

注意：actions 列表中的每个元素不需要包含 step 字段，只需要 action、target、reason。status 为 success 表示可以执行，cannot_execute 表示无法执行。"""

                result_text = self.provider.chat(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=500
                )
                if not result_text:
                    continue

                result_text = self._clean_json_text(result_text)
                json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    intent = result.get("intent", "")
                    actions = result.get("actions", [])
                    status = result.get("status", "success")
                    if actions:
                        actions = self._sort_actions(actions)
                        print(f"🎯 意图: {intent} | 动作: {len(actions)} 步 | 状态: {status}")
                        return {"intent": intent, "actions": actions, "status": status}
                if attempt == 0:
                    print("解析结果为空，重试中...")
                else:
                    print("重试后仍为空，返回无法解析")
                    return {"intent": "无法解析", "actions": [], "status": "cannot_execute"}
            except Exception as e:
                if attempt == 0:
                    print(f"规划失败 (第1次): {e}，重试中...")
                else:
                    print(f"❌ 规划失败 (第2次): {e}")
                    return {"intent": "分析失败", "actions": [], "status": "cannot_execute"}
        return {"intent": "分析失败", "actions": [], "status": "cannot_execute"}

    def generate_action_prompt(self, action_plan):
        if not action_plan.get("actions"):
            return "无需执行物理动作。"
        lines = [f"意图: {action_plan['intent']}", "动作序列:"]
        for i, act in enumerate(action_plan["actions"], 1):
            action = act.get("action", "未知动作")
            target = act.get("target", "")
            reason = act.get("reason", "")
            target_str = f" {target}" if target else ""
            reason_str = f"（{reason}）" if reason else ""
            lines.append(f"  {i}. {action}{target_str}{reason_str}")
        return "\n".join(lines)

    def simulate_execution(self, action_plan):
        if not action_plan or not action_plan.get("actions"):
            print("无物理动作需要执行。")
            return
        print(f"\n🎬 开始模拟执行...")
        for i, act in enumerate(action_plan["actions"], 1):
            action = act.get("action", "未知动作")
            target = act.get("target", "")
            target_str = f" → {target}" if target else ""
            print(f"  [{i}/{len(action_plan['actions'])}] 执行: {action}{target_str}")
            time.sleep(0.6)
        print(f"✅ 模拟执行完成。\n")

    def _clean_json_text(self, text):
        if not text:
            return ""
        text = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
        text = re.sub(r'\n?```$', '', text)
        return text.strip()