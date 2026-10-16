"""语音对话服务（独立封装）。

- PipelineVoiceProvider  方案B：ASR → LLM → TTS，走你的 OpenAI 兼容网关（已实现）
- MockVoiceProvider      未配置 Key 时使用，返回固定文本、无音频，用于走通流程
- RealtimeVoiceProvider  方案A：端到端实时语音（OpenAI Realtime / 豆包 / Qwen-Omni），接口预留

前端与后端的约定是“一轮一请求”：用户说完一句 → 上传音频 → 返回 AI 文本 + 音频 URL。
换成方案A时，前端改为 WebSocket 推流，后端在 RealtimeVoiceProvider 中做中继即可，
会话、计时、转写记录、报告生成等逻辑都不需要改。
"""
import io
import random
import wave

from .. import config
from . import gateway
from .prompts import build_system_prompt

# ---------- 音频工具 ----------

def pcm_to_wav(pcm: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


AUDIO_MIME = {
    "wav": "audio/wav", "mp3": "audio/mpeg", "aac": "audio/aac", "m4a": "audio/mp4",
    "webm": "audio/webm", "ogg": "audio/ogg",
}


def normalize_audio(data: bytes, fmt: str, sample_rate: int = 16000):
    """把前端上传的音频统一成 (bytes, filename, mime)。PCM 原始数据会被包成 WAV。"""
    fmt = (fmt or "wav").lower()
    if fmt == "pcm":
        return pcm_to_wav(data, sample_rate), "audio.wav", "audio/wav"
    return data, f"audio.{fmt}", AUDIO_MIME.get(fmt, "application/octet-stream")


def to_chat_messages(system_prompt: str, transcript: list) -> list:
    msgs = [{"role": "system", "content": system_prompt}]
    for t in transcript:
        msgs.append({"role": "assistant" if t["role"] == "ai" else "user", "content": t["text"]})
    return msgs


# ---------- Provider ----------

class VoiceProvider:
    name = "base"
    mock = False

    async def opening(self, drill: dict) -> str:
        raise NotImplementedError

    async def transcribe(self, audio: bytes, fmt: str, sample_rate: int) -> str:
        raise NotImplementedError

    async def reply(self, drill: dict, transcript: list) -> str:
        raise NotImplementedError

    async def synthesize(self, text: str):
        """返回 mp3 bytes；返回 None 表示无音频（前端会按文字长度模拟播放时长）。"""
        raise NotImplementedError


class PipelineVoiceProvider(VoiceProvider):
    name = "pipeline"

    async def opening(self, drill):
        if drill.get("opening_line"):
            return drill["opening_line"]
        msgs = [
            {"role": "system", "content": build_system_prompt(drill)},
            {"role": "user", "content": "（训练开始。请你作为角色先开口，用一句话把情境抛给我。）"},
        ]
        return await gateway.chat(msgs, max_tokens=150)

    async def transcribe(self, audio, fmt, sample_rate):
        data, filename, mime = normalize_audio(audio, fmt, sample_rate)
        return await gateway.transcribe(data, filename, mime)

    async def reply(self, drill, transcript):
        msgs = to_chat_messages(build_system_prompt(drill), transcript)
        return await gateway.chat(msgs, max_tokens=300)

    async def synthesize(self, text):
        return await gateway.speech(text)


MOCK_USER_LINES = [
    "（Mock 识别）我觉得可以先从客户跟进的频率入手，再把需求挖掘做细一点。",
    "（Mock 识别）我理解您的顾虑，我们可以先缩小范围，分两期来做。",
    "（Mock 识别）具体来说，第一步先梳理数据，第二步每周复盘一次。",
]
MOCK_AI_LINES = [
    "嗯，有点意思。那你具体打算怎么落地？",
    "这个想法不错，但资源从哪里来？你考虑过吗？",
    "好，那时间节点呢？下个月能看到效果吗？",
    "行，我基本明白你的意思了，会后你整理一份方案发给我。",
]


class MockVoiceProvider(VoiceProvider):
    name = "mock"
    mock = True

    async def opening(self, drill):
        return drill.get("opening_line") or "我们开始吧，你先说说你的想法？"

    async def transcribe(self, audio, fmt, sample_rate):
        return random.choice(MOCK_USER_LINES)

    async def reply(self, drill, transcript):
        user_turns = sum(1 for t in transcript if t["role"] == "user")
        return MOCK_AI_LINES[min(user_turns - 1, len(MOCK_AI_LINES) - 1)] if user_turns else MOCK_AI_LINES[0]

    async def synthesize(self, text):
        return None


class RealtimeVoiceProvider(VoiceProvider):
    """方案A 预留：端到端实时语音。

    实现建议：
      1. main.py 新增 WebSocket 路由 /ws/sessions/{id}，前端以 16k PCM 帧推流；
      2. 本类内部连接上游实时语音 API（如 OpenAI Realtime 的 wss://…/realtime，
         豆包实时语音、Qwen-Omni Realtime 协议类似），session.update 时把
         build_system_prompt(drill) 作为 instructions 下发；
      3. 上游返回的音频帧原样转发给前端播放，转写文本（input/output transcript）
         通过 sessions.append_turn() 写入 transcript，报告逻辑无需改动。
    """
    name = "realtime"

    async def opening(self, drill):
        raise NotImplementedError("方案A（实时语音）尚未接入，请设置 VOICE_PROVIDER=pipeline")

    transcribe = reply = synthesize = opening


def get_provider() -> VoiceProvider:
    if config.MOCK:
        return MockVoiceProvider()
    if config.VOICE_PROVIDER == "realtime":
        return RealtimeVoiceProvider()
    return PipelineVoiceProvider()
