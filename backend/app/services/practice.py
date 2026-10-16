"""跟读练习：示范稿生成 + 发音评测（网关 capability=pronunciation）。"""
import logging
import random

from .. import config
from ..db import get_conn
from . import gateway
from .prompts import build_script_messages
from .sessions import BadRequest, _load_drill
from .voice import normalize_audio

log = logging.getLogger("talktool")


async def drill_script(user_id: str, drill_id: int) -> dict:
    """场景的跟读示范稿：首次请求时由 LLM 生成并缓存到 drill.sample_script。"""
    with get_conn() as conn:
        d = _load_drill(conn, drill_id, user_id)
    if d.get("sample_script"):
        return {"drill_id": drill_id, "script": d["sample_script"]}
    if config.MOCK:
        script = (f"谢谢您给我这个机会。关于“{d['scenario_title']}”，我的想法有两点。第一，先把对方最关心的问题讲清楚；"
                  "第二，给出一个具体、可以马上落地的方案。如果您同意，我会后整理成文字发给大家。")
    else:
        script = (await gateway.chat(build_script_messages(d), capability=config.REPORT_CAPABILITY,
                                     temperature=0.6, max_tokens=500)).strip().strip('"“”')
    with get_conn() as conn:
        conn.execute("UPDATE drill SET sample_script = ? WHERE id = ?", (script, drill_id))
    return {"drill_id": drill_id, "script": script}


def _mock_pronounce(text: str) -> dict:
    score = random.randint(72, 93)
    return {"score": score, "accuracy": score / 100, "transcript": text[:-2] if len(text) > 4 else text,
            "issues": [{"quote": text[:8], "note": "（Mock）这一句语速略快，个别字没咬清"}],
            "note": "（Mock 评测）整体流畅，配置网关后返回真实发音评分", "mock": True}


async def pronounce(user_id: str, audio: bytes, fmt: str, sample_rate: int, text: str, note_id: int = None) -> dict:
    text = (text or "").strip()
    if not text:
        raise BadRequest("缺少要跟读的文本")
    if len(text) > 2000:
        raise BadRequest("文本过长")
    if not audio or len(audio) < 1000:
        raise BadRequest("没有录到声音，请再试一次")
    if config.MOCK:
        res = _mock_pronounce(text)
    else:
        data, filename, mime = normalize_audio(audio, fmt, sample_rate)
        raw = await gateway.pronounce(data, text, filename, mime)
        res = {
            "score": raw.get("score"),
            "accuracy": raw.get("accuracy"),
            "transcript": raw.get("transcript", ""),
            "issues": [i for i in (raw.get("issues") or []) if isinstance(i, dict)][:8],
            "note": raw.get("note", ""),
        }
    if note_id and isinstance(res.get("score"), (int, float)):
        with get_conn() as conn:
            conn.execute(
                "UPDATE note SET best_score = MAX(COALESCE(best_score, 0), ?) WHERE id = ? AND user_id = ?",
                (int(res["score"]), note_id, user_id))
    return res
