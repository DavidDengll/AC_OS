# tokenizer.py
"""
本地中文分词器，基于规则 + 简单词表，不依赖第三方库。
"""

COMMON_WORDS = {
    # 名词 - 动物
    "猫", "狗", "鸟", "鱼", "马", "牛", "羊", "猪", "鸡", "鸭", "鹅",
    "老虎", "狮子", "大象", "猴子", "兔子", "松鼠", "熊猫", "狐狸", "狼", "熊",
    "蝴蝶", "蜜蜂", "蚂蚁", "蜘蛛", "青蛙", "老鼠", "蛇", "乌龟", "金鱼",
    # 名词 - 植物
    "花", "草", "树", "叶", "玫瑰", "菊花", "梅花", "兰花", "竹子", "松树",
    "仙人掌", "向日葵",
    # 名词 - 自然
    "太阳", "月亮", "星星", "天空", "云", "雨", "雪", "风", "雷", "电",
    "山", "海", "河", "湖", "沙漠", "森林", "草原", "海滩", "石头", "沙子",
    "阳光", "月光", "星光",
    # 名词 - 建筑
    "房", "窗", "门", "墙", "屋顶", "院子", "厨房", "客厅", "卧室", "阳台",
    "楼梯", "电梯", "桥", "路", "街道", "公园", "城市",
    # 名词 - 物品
    "桌", "椅", "灯", "书", "笔", "纸", "杯", "碗", "盘", "筷子", "勺子",
    "手机", "电脑", "电视", "冰箱", "洗衣机", "空调", "风扇",
    "汽车", "火车", "飞机", "船", "自行车", "摩托车",
    "苹果", "香蕉", "西瓜", "葡萄", "草莓", "橘子", "柠檬",
    "面包", "牛奶", "咖啡", "茶", "水", "糖", "盐", "米饭", "面条",
    "书桌", "台灯", "沙发", "窗帘", "地毯", "镜子", "钟表", "花瓶",
    # 名词 - 人
    "人", "孩子", "老人", "妈妈", "爸爸", "朋友", "同学", "老师",
    # 形容词
    "大", "小", "高", "低", "长", "短", "快", "慢", "热", "冷", "暖", "凉",
    "漂亮", "美丽", "可爱", "可怕", "有趣", "无聊", "安静", "吵",
    "毛茸茸", "光滑", "粗糙", "软", "硬", "轻", "重",
    "开心", "伤心", "生气", "害怕", "紧张", "放松",
    "红色", "蓝色", "绿色", "黄色", "白色", "黑色", "紫色", "橙色", "粉色",
    # 动词
    "跑", "跳", "走", "飞", "游", "爬", "吃", "喝", "看", "听", "说", "笑", "哭", "睡",
    "趴", "蹲", "站", "坐", "躺", "挂", "放", "拿", "抓", "扔", "踢", "打",
    "发光", "照亮", "照耀", "反射", "闪烁",
    "唱歌", "跳舞", "画画", "写字", "读书",
}

SKIP_WORDS = {
    "一只", "一个", "一条", "一张", "一片", "这个", "那个", "这些", "那些",
    "的", "了", "在", "是", "有", "和", "与", "它", "他", "她", "我", "你",
    "着", "被", "把", "从", "到", "上", "中", "下", "里", "外", "都", "也", "很", "就", "还",
    "这", "那", "什么", "怎么", "为什么", "因为", "所以", "但是", "如果", "虽然",
    "上面", "下面", "里面", "外面", "旁边", "前面", "后面",
    "非常", "特别", "比较", "更", "最", "太",
    "正在", "已经", "刚才", "现在", "以前", "以后", "马上",
}


def tokenize(text):
    """简单中文分词。返回有意义的词列表。"""
    for sep in "，。！？、；：""''（）【】《》…—\n":
        text = text.replace(sep, " ")
    segments = text.split()
    words = []
    for seg in segments:
        if not seg:
            continue
        i = 0
        while i < len(seg):
            matched = False
            for length in range(min(6, len(seg) - i), 0, -1):
                candidate = seg[i:i+length]
                if candidate in COMMON_WORDS:
                    if candidate not in SKIP_WORDS:
                        words.append(candidate)
                    i += length
                    matched = True
                    break
            if not matched:
                char = seg[i]
                if char not in SKIP_WORDS and len(char.strip()) >= 1 and '\u4e00' <= char <= '\u9fff':
                    words.append(char)
                i += 1
    seen = set()
    result = []
    for w in words:
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result


def extract_keywords(text, max_keywords=5):
    """从文本中提取最多 max_keywords 个关键词。"""
    words = tokenize(text)
    if not words:
        for char in text:
            if char.strip() and char not in SKIP_WORDS and '\u4e00' <= char <= '\u9fff':
                return [char]
        return ["未知"]
    return words[:max_keywords]


def get_main_subject(text):
    """从文本中获取主要描述对象。"""
    words = tokenize(text)
    if words:
        return words[0]
    for char in text:
        if char.strip() and char not in SKIP_WORDS and '\u4e00' <= char <= '\u9fff':
            return char
    return "未知"


def get_last_word(text):
    """获取文本中最后一个有意义的词，用于 hint 截断。"""
    words = tokenize(text)
    if words:
        return words[-1]
    return text[-2:] if len(text) >= 2 else text