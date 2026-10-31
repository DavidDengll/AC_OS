# memory.py
import sqlite3
import datetime
import random
from config import SHORT_TO_LONG_COUNT, LONG_TO_PERMANENT_COUNT
import jieba

DB_PATH = "entropy_memory.db"

class MemorySystem:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self._create_table()

    def _create_table(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                feature TEXT,
                level TEXT NOT NULL DEFAULT 'short',
                created TEXT NOT NULL,
                mentioned_count INTEGER DEFAULT 0,
                last_mentioned_date TEXT
            )
        ''')
        self.conn.commit()
        self._migrate_emotion_color()

    def _migrate_emotion_color(self):
        """增量迁移：为老库补 emotion_color 列（幂等，不动已有数据语义）。"""
        try:
            cols = [r[1] for r in self.conn.execute("PRAGMA table_info(memories)")]
            if "emotion_color" not in cols:
                self.conn.execute(
                    "ALTER TABLE memories ADD COLUMN emotion_color TEXT NOT NULL DEFAULT 'neutral'")
                self.conn.commit()
                print("[记忆] 已补充 emotion_color 字段（历史记忆默认 neutral）")
        except Exception as e:
            print("[记忆] emotion_color 迁移失败（已降级运行）: %s" % e)

    @staticmethod
    def _today():
        return datetime.date.today().isoformat()

    @staticmethod
    def _same_day(d1, d2):
        return d1 == d2

    @staticmethod
    def _same_year(d1, d2):
        return d1[:4] == d2[:4]

    def _cleanup(self):
        today = self._today()
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM memories WHERE level='short' AND created != ?", (today,))
        cursor.execute("DELETE FROM memories WHERE level='long' AND substr(created,1,4) != ?", (today[:4],))
        self.conn.commit()
        if cursor.rowcount > 0:
            print("[清理] 过期记忆已清理")

    def search(self, keyword):
        self._cleanup()
        today = self._today()
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE name=?", (keyword,))
        row = cursor.fetchone()
        if row:
            mem = {
                "id": row[0], "name": row[1], "feature": row[2],
                "level": row[3], "created": row[4],
                "mentioned_count": row[5], "last_mentioned_date": row[6]
            }
            last_date = mem["last_mentioned_date"]
            if last_date and self._same_day(last_date, today):
                mem["mentioned_count"] += 1
            else:
                mem["mentioned_count"] = 1
            mem["last_mentioned_date"] = today

            self._try_upgrade(mem)

            cursor.execute("""
                UPDATE memories SET mentioned_count=?, last_mentioned_date=?, level=?
                WHERE id=?
            """, (mem["mentioned_count"], mem["last_mentioned_date"], mem["level"], mem["id"]))
            self.conn.commit()
            return mem["feature"]
        return None

    def _try_upgrade(self, mem):
        if mem["level"] == "short" and mem["mentioned_count"] >= SHORT_TO_LONG_COUNT:
            mem["level"] = "long"
            mem["mentioned_count"] = 0
            print(f"[升级] 短期 → 长期: {mem['name']}")
        elif mem["level"] == "long" and mem["mentioned_count"] >= LONG_TO_PERMANENT_COUNT:
            mem["level"] = "permanent"
            mem["mentioned_count"] = 0
            print(f"[升级] 长期 → 永久: {mem['name']}")

    def _extract_keywords(self, text):
        """从文本中提取关键词，用于特征合并"""
        words = jieba.lcut(text)
        skip_words = {"的", "了", "在", "是", "有", "它", "这", "那", "什么", "怎么", "为什么", "吗", "呢", "吧", "啊", "一只", "一个", "一条", "这个", "那个", "这些", "那些", "上面", "下面", "里面", "外面", "非常", "特别", "比较", "更", "最", "太", "正在", "已经", "马上", "刚才", "现在"}
        keywords = [w for w in words if w not in skip_words and len(w.strip()) >= 1]
        return list(set(keywords))

    def add_short(self, name, feature):
        """添加短期记忆，如果同名记忆已存在则合并特征"""
        # 【修复】添加新记忆前先清理过期记忆
        self._cleanup()

        cursor = self.conn.cursor()
        today = self._today()

        # 检查是否已存在同名记忆（任意级别）
        cursor.execute("SELECT id, feature, level FROM memories WHERE name=?", (name,))
        existing = cursor.fetchone()
        if existing:
            old_feature = existing[1] if existing[1] else ""
            old_keywords = self._extract_keywords(old_feature)
            new_keywords = self._extract_keywords(feature)
            all_keywords = list(set(old_keywords + new_keywords))[:5]
            merged_feature = "、".join(all_keywords) if all_keywords else feature
            cursor.execute("UPDATE memories SET feature=?, created=?, mentioned_count=0 WHERE id=?",
                           (merged_feature, today, existing[0]))
            self.conn.commit()
            print(f"🔄 特征合并: {name} → {merged_feature}")
            return

        cursor.execute("INSERT INTO memories (name, feature, level, created) VALUES (?,?,?,?)",
                       (name, feature, 'short', today))
        self.conn.commit()
        print(f"[新短期记忆] {name}（特征: {feature}）")

    def add_permanent(self, name, feature):
        today = self._today()
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO memories (name, feature, level, created) VALUES (?,?,?,?)",
                       (name, feature, 'permanent', today))
        self.conn.commit()
        print(f"[永久记忆] {name}（特征: {feature}）")

    def get_random_fragment(self, min_len=1, max_len=4):
        cursor = self.conn.cursor()
        cursor.execute("SELECT feature FROM memories WHERE level IN ('permanent','long') ORDER BY RANDOM() LIMIT 1")
        row = cursor.fetchone()
        if not row:
            cursor.execute("SELECT feature FROM memories ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
        if not row:
            return ""
        feature_text = row[0]
        words = [w.strip() for w in feature_text.replace("，", " ").replace("、", " ").split() if w.strip()]
        if not words:
            return ""
        chosen_word = random.choice(words)
        if len(chosen_word) <= min_len:
            return chosen_word
        max_start = max(0, len(chosen_word) - min_len)
        start = random.randint(0, max_start)
        end = min(start + random.randint(min_len, max_len), len(chosen_word))
        return chosen_word[start:end]

    def close(self):
        self.conn.close()

    # ==================== 纯数值心理层：情绪染色 / 偏置检索 / 睡眠代谢 ====================
    def _color_of(self, endo):
        """强制染色：D>0.6 或 E>0.6 -> positive；C>0.6 -> negative；其余 neutral。"""
        try:
            import soul_core
            return soul_core.emotion_color(endo)
        except Exception:
            return "neutral"

    def add_short_colored(self, name, feature, endo=None):
        """短期记忆入库并染色。不传 endo 时等价于原 add_short（向后兼容）。"""
        try:
            color = self._color_of(endo)
            cur = self.conn.cursor()
            cur.execute("SELECT id FROM memories WHERE name=?", (name,))
            existed = cur.fetchone()
            self.add_short(name, feature)
            if existed:
                cur.execute("UPDATE memories SET emotion_color=? WHERE name=?", (color, name))
            else:
                cur.execute("UPDATE memories SET emotion_color=? WHERE name=? AND level='short'",
                            (color, name))
            self.conn.commit()
            return color
        except Exception as e:
            print("[记忆] 染色失败（已忽略）: %s" % e)
            return "neutral"

    def add_long(self, name, feature, endo=None):
        """长期记忆入库并染色（睡眠代谢的产物走这里）。"""
        try:
            color = self._color_of(endo)
        except Exception:
            color = "neutral"
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO memories (name, feature, level, created, emotion_color) VALUES (?,?,?,?,?)",
            (name, feature, 'long', self._today(), color))
        self.conn.commit()
        print("[长期记忆] %s（%s，特征: %s）" % (name, color, feature))
        return color

    def list_memories(self, level=None, limit=200):
        """按级别读取记忆，供偏置检索与睡眠代谢使用。"""
        try:
            cursor = self.conn.cursor()
            if level:
                cursor.execute(
                    "SELECT id,name,feature,level,created,mentioned_count,emotion_color "
                    "FROM memories WHERE level=? ORDER BY id DESC LIMIT ?", (level, int(limit)))
            else:
                cursor.execute(
                    "SELECT id,name,feature,level,created,mentioned_count,emotion_color "
                    "FROM memories ORDER BY id DESC LIMIT ?", (int(limit),))
            rows = []
            for r in cursor.fetchall():
                rows.append({"id": r[0], "name": r[1], "feature": r[2], "level": r[3],
                             "created": r[4], "mentioned_count": r[5] or 0,
                             "color": r[6] or "neutral"})
            return rows
        except Exception as e:
            print("[记忆] 读取失败（已忽略）: %s" % e)
            return []

    def retrieve_memories(self, endo=None, text="", level=None, n_positive=2, n_negative=2):
        """带情绪偏置的检索（替代原先不存在的 retrieve_memories）。

        偏置与 max_cap 由 soul_core.retrieve_memories 统一计算，这里只负责取数据。
        """
        try:
            import soul_core
            rows = self.list_memories(level=level, limit=500)
            return soul_core.retrieve_memories(rows, endo or {}, text,
                                               n_positive=n_positive, n_negative=n_negative)
        except Exception as e:
            print("[记忆] 偏置检索失败（已降级）: %s" % e)
            return {"positive": [], "negative": [], "neutral": [],
                    "mult": {"positive": 1.0, "negative": 1.0}, "reason": ""}

    def sleep_candidates(self):
        """睡眠代谢取料：按染色均衡挑 2 条未固化的短期记忆。"""
        try:
            rows = [m for m in self.list_memories(level="short", limit=100)
                    if "睡眠固化" not in str(m.get("name") or "")]
            if len(rows) < 2:
                return []
            by_color = {}
            for m in rows:
                by_color.setdefault(m.get("color") or "neutral", []).append(m)
            picked = []
            for color in ("positive", "negative", "neutral"):
                if by_color.get(color) and len(picked) < 2:
                    picked.append(by_color[color][0])
            for m in rows:
                if len(picked) >= 2:
                    break
                if m not in picked:
                    picked.append(m)
            return picked[:2]
        except Exception as e:
            print("[记忆] 取料失败（已忽略）: %s" % e)
            return []

    def remove_memories(self, ids):
        try:
            cur = self.conn.cursor()
            for mid in ids:
                cur.execute("DELETE FROM memories WHERE id=?", (mid,))
            self.conn.commit()
            return True
        except Exception as e:
            print("[记忆] 删除失败（已忽略）: %s" % e)
            return False

    def close(self):
        self.conn.close()
