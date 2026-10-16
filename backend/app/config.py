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
TTS_VOICE = _env("TTS_VOICE", "FunAudioLLM/CosyVoice2-0.5B:alex")  # alex/anna/bella/benjamin/charles/claire/david/diana
TTS_SPEED = float(_env("TTS_SPEED", "1.0"))

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

CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "*").split(",") if o.strip()]

DATA_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
