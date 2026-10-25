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