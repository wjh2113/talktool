"""集中读取环境变量（.env）。所有 Key 只存在后端，前端拿不到。"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv 未安装时直接读系统环境变量
    pass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(_env("DATA_DIR", str(BASE_DIR / "data")))
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = Path(_env("DB_PATH", str(DATA_DIR / "talktool.db")))

APP_TIMEZONE = _env("APP_TIMEZONE", "Asia/Shanghai")
# 后端对外地址，用于拼接 TTS 音频的绝对 URL（真机/小程序必须是可访问的地址）
PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", "").rstrip("/")

# ---- AIapiMgr 网关（Bearer 租户 API Key + capability 选模型）----
GATEWAY_BASE_URL = _env("GATEWAY_BASE_URL", "https://aiapimgrapi.aidigitcloud.cn").rstrip("/")
GATEWAY_API_KEY = _env("GATEWAY_API_KEY")
GATEWAY_TENANT_ID = _env("GATEWAY_TENANT_ID")          # 可选，便于网关审计
GATEWAY_DATA_CLASS = _env("GATEWAY_DATA_CLASS", "internal")
GATEWAY_TIMEOUT = float(_env("GATEWAY_TIMEOUT", "75"))  # 网关建议业务超时 ≥ 70 秒

# 能力名（不要写上游模型名，换模型由网关管理员在「模型路由」里改）
LLM_CAPABILITY = _env("LLM_CAPABILITY", "fast-chat")          # 对练回复：低延迟
REPORT_CAPABILITY = _env("REPORT_CAPABILITY", "quality-chat")  # 训练报告：质量优先
ASR_CAPABILITY = _env("ASR_CAPABILITY", "speech")
TTS_CAPABILITY = _env("TTS_CAPABILITY", "tts")
PRONOUNCE_CAPABILITY = _env("PRONOUNCE_CAPABILITY", "pronunciation")
CUSTOM_CAPABILITY = _env("CUSTOM_CAPABILITY", "quality-chat")    # 自定义场景生成
LLM_TEMPERATURE = float(_env("LLM_TEMPERATURE", "0.8"))
ASR_LANGUAGE = _env("ASR_LANGUAGE", "zh")
# CosyVoice 音色：alex/anna/bella/benjamin/charles/claire/david/diana
TTS_VOICE = _env("TTS_VOICE", "FunAudioLLM/CosyVoice2-0.5B:alex")  # 兼容旧配置；男声默认回退到它
_male = _env("TTS_VOICE_MALE", "")
TTS_VOICE_MALE = _male or None
TTS_VOICE_FEMALE = _env("TTS_VOICE_FEMALE", "FunAudioLLM/CosyVoice2-0.5B:anna")
TTS_SPEED = float(_env("TTS_SPEED", "1.0"))
TTS_PREVIEW_TEXT = "你好，我是沟通表达演练场。接下来我会用这个声音给你示范。"

# 语音方案：pipeline = 方案B（ASR+LLM+TTS，已实现）；realtime = 方案A（预留）
VOICE_PROVIDER = _env("VOICE_PROVIDER", "pipeline")

# 未配置 Key 时自动进入 Mock 模式，可以完整走通流程
MOCK_MODE = _env("MOCK_MODE", "auto").lower()
if MOCK_MODE == "auto":
    MOCK = not GATEWAY_API_KEY
else:
    MOCK = MOCK_MODE in ("1", "true", "yes", "on")

# ---- 报告规则 ----
MIN_DURATION_SEC = int(_env("MIN_DURATION_SEC", "60"))       # 少于该时长 → too_short
MIN_USER_TURNS = int(_env("MIN_USER_TURNS", "1"))            # 用户有效发言少于该轮数 → too_short
STALE_SESSION_MIN = int(_env("STALE_SESSION_MIN", "120"))     # 超过该时长仍未结束 → abandoned
CUSTOM_DRILL_LIMIT = int(_env("CUSTOM_DRILL_LIMIT", "30"))    # 每个用户最多保留的自定义场景数

# ---- 省 Token / 防刷 ----
def _cost(name: str, default: str):
    v = _env(name, default)
    return float(v) if v else None            # 留空 = 不设单次成本上限

HISTORY_TURNS = int(_env("HISTORY_TURNS", "6"))            # 对练时只带最近 N 轮（AI+用户为 1 轮）
REPLY_MAX_TOKENS = int(_env("REPLY_MAX_TOKENS", "150"))    # 对练回复输出上限
REPORT_MAX_TOKENS = int(_env("REPORT_MAX_TOKENS", "1200")) # 报告输出上限（逐句复盘已拆出去）
SHORT_REPORT_TURNS = int(_env("SHORT_REPORT_TURNS", "3"))  # 用户发言 ≤ N 句的报告改用 LLM_CAPABILITY
REVIEW_CAPABILITY = _env("REVIEW_CAPABILITY", "fast-chat") # 逐句复盘（按需生成）
ASR_MIN_SPEECH_MS = int(_env("ASR_MIN_SPEECH_MS", "300"))  # 录音里有效人声少于该时长 → 不送识别
MAX_COST_REPLY = _cost("MAX_COST_REPLY", "0.03")           # 单次调用成本上限（元），对应网关 maxCostCny
MAX_COST_REPORT = _cost("MAX_COST_REPORT", "0.2")
MAX_COST_OTHER = _cost("MAX_COST_OTHER", "0.1")            # 自定义场景 / 示范稿 / 逐句复盘
MAX_COST_CONSULT = _cost("MAX_COST_CONSULT", "0.3")         # 智囊团单次调用（出锦囊用 quality-chat，输出较长）
DAILY_SESSION_LIMIT = int(_env("DAILY_SESSION_LIMIT", "30"))     # 每个用户每天最多开始的训练数（0 = 不限）
DAILY_IP_SESSION_LIMIT = int(_env("DAILY_IP_SESSION_LIMIT", "100"))  # 同一 IP 每天最多开始的训练数（防换 ID 刷）

# ---- 账号 ----
ADMIN_USERNAME = _env("ADMIN_USERNAME")          # 启动时若该用户不存在则创建为管理员
ADMIN_PASSWORD = _env("ADMIN_PASSWORD")
TOKEN_DAYS = int(_env("TOKEN_DAYS", "30"))        # 登录有效期
LOGIN_FAIL_LIMIT = int(_env("LOGIN_FAIL_LIMIT", "10"))  # 同一 IP 15 分钟内登录/注册失败次数上限

# ---- 每日用量上限（按账号，0 = 不限）----
DAILY_TTS_LIMIT = int(_env("DAILY_TTS_LIMIT", "300"))          # 示范朗读（未命中缓存才计数）
DAILY_PRONOUNCE_LIMIT = int(_env("DAILY_PRONOUNCE_LIMIT", "150"))
DAILY_CUSTOM_LIMIT = int(_env("DAILY_CUSTOM_LIMIT", "10"))      # 每天生成自定义场景次数
DAILY_REVIEW_LIMIT = int(_env("DAILY_REVIEW_LIMIT", "50"))      # 逐句复盘 / 示范稿 / 重新生成报告
MAX_USER_TURNS = int(_env("MAX_USER_TURNS", "30"))              # 单场训练最多发言轮数
DAILY_CONSULT_LIMIT = int(_env("DAILY_CONSULT_LIMIT", "0"))      # 智囊团每天提问次数（0 = 不限，只计数）
CONSULT_MAX_MESSAGES = int(_env("CONSULT_MAX_MESSAGES", "60"))  # 单次问计最多消息数

# ---- 音频清理 ----
AUDIO_RETENTION_DAYS = int(_env("AUDIO_RETENTION_DAYS", "7"))   # 对话中的 AI 语音保留天数
TTS_CACHE_DAYS = int(_env("TTS_CACHE_DAYS", "180"))             # 缓存语音（开场白/示范）多久没用就删
CLEANUP_INTERVAL_HOURS = float(_env("CLEANUP_INTERVAL_HOURS", "6"))

CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "*").split(",") if o.strip()]

DATA_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
