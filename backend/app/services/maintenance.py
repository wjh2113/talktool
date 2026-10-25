"""定时维护：清理旧音频、过期令牌、旧用量计数；整理长期记忆（搁置久未更新的事、压缩过长的卡片）。由 main.py 启动后台循环。"""
import asyncio
import logging
import time

from .. import config
from . import auth, quota

log = logging.getLogger("talktool")


def cleanup_audio(now_ts: float = None) -> dict:
    """
    s*.mp3  对话里 AI 的语音：只在训练当下播放，保留 AUDIO_RETENTION_DAYS 天
    t_*.mp3 缓存语音（开场白 / 示范朗读）：命中时会刷新修改时间，TTS_CACHE_DAYS 天没人用才删
    """
    now_ts = now_ts or time.time()
    removed = {"session": 0, "cache": 0, "bytes": 0}
    for f in config.AUDIO_DIR.glob("*.mp3"):
        try:
            st = f.stat()
        except OSError:
            continue
        age_days = (now_ts - st.st_mtime) / 86400
        if f.name.startswith("t_"):
            if age_days < config.TTS_CACHE_DAYS:
                continue
            kind = "cache"
        elif f.name.startswith("s"):
            if age_days < config.AUDIO_RETENTION_DAYS:
                continue
            kind = "session"
        else:
            continue
        try:
            f.unlink()
            removed[kind] += 1
            removed["bytes"] += st.st_size
        except OSError as e:
            log.warning("删除音频失败 %s：%s", f.name, e)
    return removed


def run_once() -> dict:
    out = cleanup_audio()
    out["tokens"] = auth.purge_tokens()
    out["counters"] = quota.purge(days=7)
    if out["session"] or out["cache"]:
        log.info("清理音频：对话 %s 个、缓存 %s 个，共 %.1f MB；过期令牌 %s 个",
                 out["session"], out["cache"], out["bytes"] / 1e6, out["tokens"])
    return out


async def loop():
    while True:
        try:
            await asyncio.get_running_loop().run_in_executor(None, run_once)
        except Exception as e:  # noqa: BLE001
            log.warning("定时清理失败：%s", e)
        try:
            from . import memory
            res = await memory.maintain()
            if res["dormant"] or res["compacted"]:
                log.info("整理记忆：搁置 %s 条事件线，压缩 %s 张卡片", res["dormant"], res["compacted"])
        except Exception as e:  # noqa: BLE001
            log.warning("整理记忆失败：%s", e)
        await asyncio.sleep(max(0.1, config.CLEANUP_INTERVAL_HOURS) * 3600)
