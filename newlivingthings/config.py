# config.py
import os

# ============================================
# 缓存目录：统一交给 cache_paths 解析（任务一）
#   - 尊重 HF_HOME / HF_HUB_CACHE / SENTENCE_TRANSFORMERS_HOME / TORCH_HOME
#   - 环境变量指向的目录若不可写，自动降级到可写位置，绝不抛权限错误
# ============================================
import cache_paths as _cache

try:
    _CACHE_INFO = _cache.apply_hf_env()
except Exception as _e:  # 极端情况下也不允许 import config 失败
    _CACHE_INFO = {"error": str(_e)}
    print("[缓存] 路径初始化异常（已忽略，继续运行）: %s" % _e)

_MODEL_CACHE = os.environ.get("SENTENCE_TRANSFORMERS_HOME") or \
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".model_cache")

# ============================================
# 模型提供商配置（通用 OpenAI 兼容接口）
# ============================================
MODEL_NAME = "qwen3.5:0.8b"
API_BASE_URL = "http://127.0.0.1:11434/v1"
API_KEY = "ollama"
API_EXTRA_HEADERS = {}

# 环境变量覆盖（容器化必需）：
#   容器内的 127.0.0.1 指向容器自己，必须用 OLLAMA_BASE_URL 指向宿主机 Ollama。
#   本地运行时这些变量通常不存在，行为与原来完全一致。
if os.environ.get("MODEL_NAME"):
    MODEL_NAME = os.environ["MODEL_NAME"]
if os.environ.get("OLLAMA_BASE_URL"):
    API_BASE_URL = os.environ["OLLAMA_BASE_URL"]
if os.environ.get("API_BASE_URL"):
    API_BASE_URL = os.environ["API_BASE_URL"]
if os.environ.get("API_KEY"):
    API_KEY = os.environ["API_KEY"]

# 微调产物目录也支持环境变量（容器内挂载到持久卷）
if os.environ.get("AC_FINETUNE_DIR"):
    RUN_DIR = os.environ["AC_FINETUNE_DIR"]

# ============================================
# 发言与审查
# ============================================
SPEAK_THRESHOLD = 0.6
MIN_MEANING_SCORE = 4
MAX_RETRIES = 3
CURIOSITY_THRESHOLD = 3

# ============================================
# 记忆升级条件
# ============================================
SHORT_TO_LONG_COUNT = 5
LONG_TO_PERMANENT_COUNT = 7

# ============================================
# 视觉模式
# ============================================
VISION_MODE = "simulate"
# 初始环境：真实世界（原"橘猫趴在窗台上"已按"打破次元壁"要求替换）
SCENE_DESCRIPTION = "你正在连接真实世界。你想去 GitHub 看看今天的热门项目，或者去 Codeforces 看看最近有没有比赛"
IMAGE_PATH = None

# ============================================
# 分类器设置
# ============================================
USE_CLOUD_CLASSIFIER = False

# ============================================
# 编码模式选择（双模架构）
# ============================================
# True  : 使用云端大模型编码（效果好，消耗 Token）
# False : 使用本地 sentence-transformers 编码（省钱，GPU 加速）
USE_CLOUD_ENCODER = False              # 默认本地
CLOUD_ENCODER_MODEL = "Agnes-2.0-Flash"  # 云端编码用的模型名

# ============================================
# 情绪模型参数
# ============================================
EMOTION_DECAY_RATE = 0.05
EMOTION_SPEAK_ENERGY_COST = 0.03
EMOTION_SILENCE_ENERGY_GAIN = 0.05
EMOTION_LEARN_CURIOSITY_GAIN = 0.1
EMOTION_LEARN_PLEASURE_GAIN = 0.05
EMOTION_UNKNOWN_CURIOSITY_GAIN = 0.15
EMOTION_QUESTION_CURIOSITY_COST = 0.2

# ============================================
# 反驳冲动参数
# ============================================
REJECTION_BONUS_MAX = 0.3
REJECTION_BONUS_PER_STREAK = 0.1
REJECTION_LENIENT_THRESHOLD = 3

# ============================================
# 生成策略概率
# ============================================
MEMORY_INFLUENCE_PROB = 0.4
WORD_INSERT_PROB = 0.3
MOSAIC_PROB = 0.5
HINT_USE_PROB = 0.7

# ============================================
# 启动配置校验
# ============================================
def validate_config():
    if API_KEY == "你的API-Key" or API_KEY is None or API_KEY == "":
        raise ValueError(
            "❌ 检测到 API_KEY 未配置！\n"
            "请打开 config.py，将 API_KEY 替换为你自己的密钥，\n"
            "或者设置环境变量 LLM_API_KEY。\n"
            "如果你用的是智谱，去 https://open.bigmodel.cn 注册获取。"
        )
    print("配置校验通过")

# ============================================
# 【自主进化 / 自我微调参数】AC OS 基因重塑
# 追加于 2026/10/24，不改变上方任何既有键
# ============================================

# ---- 第一步：分泌多巴胺，收集优质基因 ----
TASTE_D_THRESHOLD = 0.8          # 多巴胺高于此值 -> 认定"回答得极好"
TASTE_E_THRESHOLD = 0.8          # 内啡肽高于此值 -> 认定"极度兴奋"
HIGH_QUALITY_MIN_LEN = 4         # 优质基因最小字数（过滤空话）
MAX_FINETUNE_SAMPLES = 200       # 基因池上限（只保留最新优质基因）
FINETUNE_DATA_FILE = "finetune_data.jsonl"

# ---- 第二步：空闲触发微调 ----
FINETUNE_TRIGGER_COUNT = 20      # 攒够 20 条才允许触发
IDLE_SECONDS = 15                # 无新对话超过该秒数视为"空闲状态"
IDLE_POLL_SECONDS = 2            # 空闲轮询间隔
FINETUNE_POLL_SECONDS = 1.0      # 训练进程日志轮询间隔
FINETUNE_TIMEOUT_SECONDS = 7200  # 训练超时（超时即判定失败并回滚）
MAX_NEW_MODEL_NAME = "entropy_evolved"
BASE_MODEL_HF_REPO = "Qwen/Qwen3.5-0.8B-Base"
RUN_DIR = "run_evolve"           # 训练日志 / 锁 / 结果文件目录
AUTO_EVOLVE_ON_IDLE = True       # 空闲自动进化开关（设为 False 时只用 /evolve 手动触发）

# ---- 第三步：基因融合与热替换 ----
AUTO_MERGE_AND_REPLACE = True    # 训练成功后自动合并 + 热替换
AUTO_OLLAMA_CREATE = True        # 尝试 ollama create entropy_evolved
OLLAMA_BIN = "ollama"
GENERATION_FILE = "generation.json"
EVOLUTION_LOG_FILE = "evolution_log.jsonl"

# ---- 基底大脑（永不丢失，失败回滚的锚点） ----
BASE_MODEL_NAME = "qwen3.5:0.8b"
# 训练期间主链路可选的"影子模型"；None 表示不变（本地 Ollama 场景无需切换）
SHADOW_MODEL = None

# ---- 涌现式默认值（存在则不覆盖，保证 OLLAMA_MODEL 永远可用） ----
for _k, _v in {
    "OLLAMA_BASE_URL": "http://127.0.0.1:11434/v1",
    "OLLAMA_MODEL": MODEL_NAME,
    "EMOTIONAL_THRESHOLD": 0.8,
}.items():
    if _k not in globals():
        globals()[_k] = _v

# ---- ZeptoClaw 手套（宿主机外部执行工具） ----
TOOL_CALL_ENABLED = True             # 总开关
TOOL_CALL_CURIOSITY_THRESHOLD = 0.8  # 好奇心高于此值 -> 真实抓取 GitHub/Codeforces（打破次元壁）
TOOL_CALL_LEGACY_THRESHOLD = 0.9     # 更高阈值 -> 走 ZeptoClaw 通用任务（保留原逻辑）

# ---- 真实互联网（GitHub / Codeforces）----
# 宿主机没有 7890 代理；GitHub 域名在 hosts 里被 Steam++ 加速器劫持到宿主机 443，
# 因此容器内需把域名解析到宿主机网关（host.docker.internal）才能出网。
REAL_WORLD_ENABLED = True
CURIOSITY_GAIN_PER_ROUND = 0.06      # 每轮好奇心自然增长（约 10 轮后越过 0.8 阈值）
WEB_CONTEXT_CHARS = 500              # 回传给熵灵的正文上限（约 200 token）
WEB_MIRROR_FALLBACK = True           # 外网失败时改用国内镜像站


# ---- 代码级自我重构（任务二：OOM 降级进化） ----
CODE_REWRITE_ENABLED = True      # 总开关：允许改自己的源码
CODE_REWRITE_ON_OOM = True       # 微调因 OOM 失败时，降级触发代码重构
CODE_REWRITE_USE_MODEL = True    # 先用本地大模型重构；失败再用内置安全候选
CODE_REWRITE_TARGETS = ("vision.py", "thinker.py")   # 只允许改这两个文件

# 本地大脑模型名（config.MODEL_NAME 被切到 entropy_evolved 后仍可回退）
if "LOCAL_OLLAMA_MODEL" not in globals():
    LOCAL_OLLAMA_MODEL = BASE_MODEL_NAME

# ---- 四阶进化：生命值与人格 ----
VITALITY_MAX = 100              # 初始/上限生命值
VITALITY_COST_LLM = 1           # 每次调用大模型扣血
VITALITY_COST_TOOL_ERROR = 10   # 工具报错扣血
VITALITY_GAIN_TOOL_SUCCESS = 5  # 工具成功回血
VITALITY_GAIN_IDLE = 1          # idle 每轮回血（注意：>= 工具扣血时会抹平生存压力，建议远小于扣血值）
VITALITY_DYING_THRESHOLD = 20   # 低于此值注入濒死警告

REFLECT_EVERY_N = 20            # 每 N 轮触发一次人格反思
REFLECT_ENDO_SWING = 0.25       # 内分泌波动超过此值也触发
REFLECT_PENALTY_DOPAMINE = 0.05 # 反思被废时的多巴胺惩罚
REFLECT_TRIES = 3               # 生成->自我审查最多重试次数（同一模型自我挑刺，单次通过率低）

SOUL_ENABLED = True             # 四阶进化总开关
