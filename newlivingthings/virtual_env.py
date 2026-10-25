# virtual_env.py
import random

class VirtualEnvironment:
    """简单的 2D 网格虚拟世界，用自然语言与 AI 交互"""

    def __init__(self, size=5):
        self.size = size
        self.agent_pos = [0, 0]
        self.items = {}
        self.inventory = []
        self._next_uid = 0
        self._rewarded_uids = set()
        self._place_random_items(3)
        self.action_history = []

    def _place_random_items(self, n=3):
        positions = [(x, y) for x in range(self.size) for y in range(self.size)]
        if tuple(self.agent_pos) in positions:
            positions.remove(tuple(self.agent_pos))
        for pos in list(self.items.keys()):
            if pos in positions:
                positions.remove(pos)
        random.shuffle(positions)
        pool = [
            ("石头", "灰色、坚硬、表面粗糙"),
            ("猫", "橘色、毛茸茸、会喵喵叫"),
            ("苹果", "红色、圆形、散发着果香"),
            ("花朵", "红色、有香味"),
            ("杯子", "白色陶瓷、有把手")
        ]
        for i in range(min(n, len(positions))):
            x, y = positions[i]
            name, feature = pool[random.randint(0, len(pool)-1)]
            uid = self._next_uid
            self._next_uid += 1
            self.items[(x, y)] = {"name": name, "feature": feature, "uid": uid}

    def reset(self):
        self.agent_pos = [0, 0]
        self.items.clear()
        self.inventory.clear()
        self._rewarded_uids.clear()
        self._next_uid = 0
        self.action_history.clear()
        self._place_random_items(3)
        return self.see()

    def see(self):
        """用自然语言描述当前场景"""
        x, y = self.agent_pos
        parts = []

        if (x, y) in self.items:
            item = self.items[(x, y)]
            parts.append(f"你面前有一个{item['name']}，{item['feature']}")
        else:
            parts.append("当前格子空无一物")

        if self.inventory:
            parts.append(f"你背包里有：{'、'.join(self.inventory)}")

        neighbors = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.size and 0 <= ny < self.size:
                    if (nx, ny) in self.items:
                        name = self.items[(nx, ny)]["name"]
                        direction = self._get_direction(x, y, nx, ny)
                        neighbors.append(f"{direction}方有{name}")
        if neighbors:
            parts.append("附近: " + "，".join(neighbors))
        else:
            parts.append("附近没有其他物品")

        return "。".join(parts) + "。"

    def _get_direction(self, x, y, nx, ny):
        parts = []
        if nx < x: parts.append("北")
        elif nx > x: parts.append("南")
        if ny < y: parts.append("西")
        elif ny > y: parts.append("东")
        return "".join(parts) if parts else "这里"

    def execute(self, action_text):
        """
        执行一个自然语言动作，返回 (新的场景描述, 是否成功)。
        支持的动作格式：
          - "向北移动" / "向上走" / "往北走"
          - "抓取苹果" / "捡起石头"
          - "放下苹果" / "把苹果放下"
          - "观察周围" / "看看附近"
          - "吃苹果" / "喝牛奶"（新增）
        """
        action_text = action_text.strip()
        self.action_history.append(action_text)
        success = True
        feedback = ""

        # 严格方向解析
        direction = self._parse_direction(action_text)

        if direction:
            dx, dy = direction
            new_x = self.agent_pos[0] + dx
            new_y = self.agent_pos[1] + dy
            if 0 <= new_x < self.size and 0 <= new_y < self.size:
                self.agent_pos = [new_x, new_y]
                self.action_history.append(f"移动到 ({new_x}, {new_y})")
            else:
                self.action_history.append("移动失败：撞墙")
                success = False
                feedback = "前方是边界，无法移动"
            return self._build_scene_with_feedback(feedback), success

        # 抓取动作
        if any(w in action_text for w in ["抓", "拿", "捡", "取"]):
            target = self._extract_target(action_text)
            if not target:
                self.action_history.append("抓取失败：未指定目标")
                return self._build_scene_with_feedback("你没说要抓什么"), False
            cur = (self.agent_pos[0], self.agent_pos[1])
            if cur in self.items:
                item = self.items[cur]
                if item["name"] == target:
                    del self.items[cur]
                    self.inventory.append(item["name"])
                    if item["uid"] not in self._rewarded_uids:
                        self._rewarded_uids.add(item["uid"])
                    self.action_history.append(f"抓取了 {target}")
                    feedback = f"你成功抓起了{target}"
                else:
                    self.action_history.append(f"位置有 {item['name']}，不是 {target}")
                    success = False
                    feedback = f"你面前的是{item['name']}，不是{target}"
            else:
                self.action_history.append("当前位置没有物品")
                success = False
                feedback = "面前没有任何东西可以抓"
            return self._build_scene_with_feedback(feedback), success

        # 【新增】吃/喝动作（消耗掉当前格子的物品，或吃掉背包里的）
        if any(w in action_text for w in ["吃", "喝", "品尝"]):
            target = self._extract_target(action_text)
            cur = (self.agent_pos[0], self.agent_pos[1])
            # 1. 先看脚下有没有
            if cur in self.items:
                item = self.items[cur]
                if not target or target == item["name"]:
                    del self.items[cur]
                    self.action_history.append(f"吃掉了 {item['name']}")
                    feedback = f"你吃掉了{item['name']}，味道不错！"
                    return self._build_scene_with_feedback(feedback), True
            # 2. 再看背包里有没有
            if target and target in self.inventory:
                self.inventory.remove(target)
                self.action_history.append(f"吃掉了背包里的 {target}")
                feedback = f"你从背包里拿出{target}吃掉了"
                return self._build_scene_with_feedback(feedback), True
            # 3. 没有可吃的
            feedback = f"没有找到可以吃的东西" if not target else f"没有{target}可以吃"
            return self._build_scene_with_feedback(feedback), False

        # 放下动作
        if any(w in action_text for w in ["放", "丢", "扔", "给"]):
            target = self._extract_target(action_text)
            if target and target in self.inventory:
                self.inventory.remove(target)
                cur = (self.agent_pos[0], self.agent_pos[1])
                if cur not in self.items:
                    feature = self._get_feature_by_name(target)
                    self.items[cur] = {"name": target, "feature": feature, "uid": self._next_uid}
                    self._next_uid += 1
                    self.action_history.append(f"放下了 {target}")
                    feedback = f"你放下了{target}"
                else:
                    self.inventory.append(target)
                    self.action_history.append(f"放下失败：位置已有 {self.items[cur]['name']}")
                    success = False
                    feedback = f"地上已经有{self.items[cur]['name']}了，放不下"
            elif target:
                self.action_history.append(f"背包里没有 {target}")
                success = False
                feedback = f"你的背包里没有{target}"
            else:
                self.action_history.append("放下失败：未指定物品")
                success = False
                feedback = "你没说要放下什么"
            return self._build_scene_with_feedback(feedback), success

        # 观察动作
        if any(w in action_text for w in ["看", "观察", "查", "望"]):
            self.action_history.append("观察了周围")
            return self.see(), True

        self.action_history.append(f"无法识别动作: {action_text}")
        return self._build_scene_with_feedback("听不懂这个指令"), False

    def _parse_direction(self, text):
        """严格解析方向词，避免误判"""
        # 复合方向词（忽略，暂不支持对角线）
        compound = {
            ("东北", "NE"): (-1, 1),
            ("西北", "NW"): (-1, -1),
            ("东南", "SE"): (1, 1),
            ("西南", "SW"): (1, -1),
        }
        for (cn_key, en_key), vec in compound.items():
            if cn_key in text or en_key.upper() in text.upper():
                return None  # 暂不支持

        single = {
            ("向北", "往上", "朝北", "北", "up", "north"): (-1, 0),
            ("向南", "往下", "朝南", "南", "down", "south"): (1, 0),
            ("向西", "往左", "朝西", "西", "left", "west"): (0, -1),
            ("向东", "往右", "朝东", "东", "right", "east"): (0, 1),
        }
        for keywords, vec in single.items():
            for kw in keywords:
                if kw in text:
                    return vec
        return None

    def _extract_target(self, text):
        """从动作文本中提取目标物品名"""
        known_items = ["石头", "猫", "苹果", "花朵", "杯子"]
        for item in known_items:
            if item in text:
                return item
        return None

    def _get_feature_by_name(self, name):
        features = {
            "石头": "灰色、坚硬、表面粗糙",
            "猫": "橘色、毛茸茸、会喵喵叫",
            "苹果": "红色、圆形、散发着果香",
            "花朵": "红色、有香味",
            "杯子": "白色陶瓷、有把手"
        }
        return features.get(name, "未知物品")

    def _build_scene_with_feedback(self, feedback):
        """在场景描述后面追加动作反馈"""
        scene = self.see()
        if feedback:
            scene = scene + " " + feedback
        return scene

    def get_state(self):
        items_list = []
        for (x, y), item in self.items.items():
            items_list.append({
                "x": x, "y": y,
                "name": item["name"],
                "feature": item["feature"]
            })
        return {
            "size": self.size,
            "agent": {"x": self.agent_pos[0], "y": self.agent_pos[1]},
            "items": items_list,
            "inventory": list(self.inventory),
            "history": self.action_history[-10:]
        }