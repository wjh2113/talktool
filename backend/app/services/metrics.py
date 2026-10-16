"""表达数据分析：不调大模型，直接从录音 + 识别文本计算。

单轮指标（存进 transcript 的 user 条目）：
  reaction_ms   开口反应时间：AI 说完 → 第一次出声
  speech_ms     从开口到说完的时长（去掉首尾静音）
  pauses        说话中间 ≥ PAUSE_MS 的长停顿次数
  chars         有效字数（汉字 + 英文单词 + 数字）
  rate          语速（字/分钟）
  fillers       口头禅 / 填充词计数 {"然后": 2, ...}
"""
import array
import io
import math
import re
import sys
import wave

FRAME_MS = 30
PAUSE_MS = 800
FILLERS = ["嗯", "呃", "额", "那个", "然后", "就是", "这个", "其实", "反正", "对吧", "怎么说"]

RATE_SLOW, RATE_FAST = 140, 270          # 字/分钟
REACTION_OK, REACTION_SLOW = 1500, 3000  # 毫秒


def _pcm_samples(data: bytes, fmt: str):
    """返回 (int16 样本数组, 采样率)；不支持的格式返回 (None, 0)。"""
    fmt = (fmt or "").lower()
    if fmt == "wav":
        try:
            with wave.open(io.BytesIO(data)) as w:
                if w.getsampwidth() != 2:
                    return None, 0
                rate, ch = w.getframerate(), w.getnchannels()
                raw = w.readframes(w.getnframes())
        except (wave.Error, EOFError):
            return None, 0
    elif fmt == "pcm":
        rate, ch, raw = None, 1, data
    else:
        return None, 0
    if len(raw) % 2:
        raw = raw[:-1]
    a = array.array("h")
    a.frombytes(raw)
    if sys.byteorder == "big":
        a.byteswap()
    if ch > 1:
        a = a[::ch]
    return a, rate


def analyze_audio(data: bytes, fmt: str, sample_rate: int = 16000) -> dict:
    samples, rate = _pcm_samples(data, fmt)
    rate = rate or sample_rate or 16000
    if not samples:
        return {}
    n = max(1, int(rate * FRAME_MS / 1000))
    rms = []
    for i in range(0, len(samples) - n + 1, n):
        seg = samples[i:i + n]
        rms.append(math.sqrt(sum(x * x for x in seg) / n) / 32768)
    if not rms:
        return {}
    srt = sorted(rms)
    noise = srt[int(len(srt) * 0.2)]
    thr = max(0.01, noise * 3)
    voiced = [r > thr for r in rms]
    if not any(voiced):
        return {"total_ms": len(rms) * FRAME_MS, "speech_ms": 0, "reaction_ms": None, "pauses": 0}
    first = voiced.index(True)
    last = len(voiced) - 1 - voiced[::-1].index(True)
    pauses, gap = 0, 0
    for v in voiced[first:last + 1]:
        if v:
            if gap * FRAME_MS >= PAUSE_MS:
                pauses += 1
            gap = 0
        else:
            gap += 1
    return {
        "total_ms": len(rms) * FRAME_MS,
        "speech_ms": (last - first + 1) * FRAME_MS,
        "reaction_ms": first * FRAME_MS,
        "pauses": pauses,
    }


def count_chars(text: str) -> int:
    cjk = len(re.findall(r"[一-鿿]", text))
    words = len(re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?", text))
    return cjk + words


def count_fillers(text: str) -> dict:
    out = {}
    for f in FILLERS:
        c = text.count(f)
        if c:
            out[f] = c
    return out


def turn_metrics(audio_info: dict, text: str) -> dict:
    chars = count_chars(text)
    m = {"chars": chars, "fillers": count_fillers(text)}
    sp = audio_info.get("speech_ms") or 0
    m["speech_ms"] = sp
    m["reaction_ms"] = audio_info.get("reaction_ms")
    m["pauses"] = audio_info.get("pauses", 0)
    m["rate"] = round(chars / sp * 60000) if sp >= 800 and chars else None
    return m


def _level(value, low, high, labels):
    if value is None:
        return None
    return labels[0] if value < low else labels[2] if value > high else labels[1]


def summarize(transcript: list) -> dict:
    """把每轮指标汇总成整场的“表达数据”。"""
    turns = [t.get("metrics") for t in transcript if t.get("role") == "user" and t.get("metrics")]
    if not turns:
        return {}
    chars = sum(t["chars"] for t in turns)
    speech = sum(t.get("speech_ms") or 0 for t in turns)
    rate = round(chars / speech * 60000) if speech >= 1500 and chars else None
    reactions = [t["reaction_ms"] for t in turns if t.get("reaction_ms") is not None]
    reaction = round(sum(reactions) / len(reactions)) if reactions else None
    fillers = {}
    for t in turns:
        for k, v in (t.get("fillers") or {}).items():
            fillers[k] = fillers.get(k, 0) + v
    top = sorted(fillers.items(), key=lambda kv: -kv[1])[:3]
    pauses = sum(t.get("pauses", 0) for t in turns)
    return {
        "turns": len(turns),
        "chars": chars,
        "speech_sec": round(speech / 1000),
        "rate": rate,
        "rate_level": _level(rate, RATE_SLOW, RATE_FAST, ["偏慢", "适中", "偏快"]),
        "reaction_ms": reaction,
        "reaction_level": _level(reaction, REACTION_OK, REACTION_SLOW, ["迅速", "正常", "偏慢"]),
        "filler_total": sum(fillers.values()),
        "filler_top": [{"word": k, "count": v} for k, v in top],
        "pauses": pauses,
        "longest_turn_chars": max(t["chars"] for t in turns),
    }


def describe(summary: dict) -> str:
    """给报告 Prompt 用的一段文字。"""
    if not summary:
        return "（无表达数据）"
    parts = [f"共发言 {summary['turns']} 次、{summary['chars']} 字"]
    if summary.get("rate"):
        parts.append(f"平均语速 {summary['rate']} 字/分钟（{summary['rate_level']}）")
    if summary.get("reaction_ms") is not None:
        parts.append(f"平均开口反应 {summary['reaction_ms'] / 1000:.1f} 秒（{summary['reaction_level']}）")
    if summary.get("filler_total"):
        top = "、".join(f"“{x['word']}”{x['count']}次" for x in summary["filler_top"])
        parts.append(f"口头禅共 {summary['filler_total']} 次（{top}）")
    parts.append(f"长停顿 {summary['pauses']} 次")
    return "；".join(parts)
