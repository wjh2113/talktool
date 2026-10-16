"""业务逻辑：内容查询、训练会话、报告、训练记录。与 Web 框架无关，便于测试。"""
import logging
import time
import uuid
from datetime import timedelta

from .. import config
from ..db import dumps, get_conn, loads, now, now_str, parse_time, row_to_dict, TIME_FMT
from . import report as report_svc
from .voice import get_provider

log = logging.getLogger("talktool")


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


# ---------------- 内容 ----------------

def list_categories() -> list:
    """P1：分类 + 各分类下的场景大类（含训练卡片数量）。"""
    with get_conn() as conn:
        cats = [row_to_dict(r) for r in conn.execute("SELECT * FROM category ORDER BY sort_order, id")]
        rows = conn.execute(
            """SELECT s.*, (SELECT COUNT(*) FROM drill d WHERE d.scenario_id = s.id AND d.status='online') AS drill_count
               FROM scenario s ORDER BY s.sort_order, s.id"""
        ).fetchall()
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category_id"], []).append(row_to_dict(r))
    for c in cats:
        c["scenarios"] = by_cat.get(c["id"], [])
    return cats


def get_scenario(scenario_id: int) -> dict:
    """P2：场景大类 + 训练卡片列表。"""
    with get_conn() as conn:
        s = conn.execute(
            """SELECT s.*, c.name AS category_name FROM scenario s JOIN category c ON c.id = s.category_id
               WHERE s.id = ?""", (scenario_id,)).fetchone()
        if not s:
            raise NotFound("场景不存在")
        drills = conn.execute(
            "SELECT * FROM drill WHERE scenario_id = ? AND status='online' ORDER BY sort_order, id", (scenario_id,)
        ).fetchall()
    out = row_to_dict(s)
    out["drills"] = [_public_drill(row_to_dict(d)) for d in drills]
    return out


def _load_drill(conn, drill_id: int) -> dict:
    d = conn.execute(
        """SELECT d.*, s.title AS scenario_title, c.name AS category_name, c.id AS category_id
           FROM drill d JOIN scenario s ON s.id = d.scenario_id JOIN category c ON c.id = s.category_id
           WHERE d.id = ?""", (drill_id,)).fetchone()
    if not d:
        raise NotFound("训练不存在")
    return row_to_dict(d)


def _public_drill(d: dict) -> dict:
    d = dict(d)
    d.pop("system_prompt", None)  # 不把内部 prompt 暴露给前端
    return d


def get_drill(drill_id: int) -> dict:
    """P3：训练详情。"""
    with get_conn() as conn:
        return _public_drill(_load_drill(conn, drill_id))


# ---------------- 训练会话 ----------------

def _audio_url(name: str) -> str:
    return f"{config.PUBLIC_BASE_URL}/media/audio/{name}"


async def _synthesize(provider, session_id: int, text: str):
    """合成语音并保存为文件；失败时不阻断对话（前端退化为按时长模拟）。"""
    try:
        audio = await provider.synthesize(text)
    except Exception as e:  # noqa: BLE001
        log.warning("TTS 失败：%s", e)
        return None
    if not audio:
        return None
    name = f"s{session_id}_{uuid.uuid4().hex[:10]}.mp3"
    (config.AUDIO_DIR / name).write_bytes(audio)
    return _audio_url(name)


def _append(conn, session_id: int, role: str, text: str) -> list:
    row = conn.execute("SELECT transcript FROM session WHERE id = ?", (session_id,)).fetchone()
    transcript = loads(row["transcript"], [])
    transcript.append({"role": role, "text": text, "at": now_str()})
    conn.execute("UPDATE session SET transcript = ? WHERE id = ?", (dumps(transcript), session_id))
    return transcript


def _get_session_row(conn, session_id: int, user_id: str) -> dict:
    s = conn.execute("SELECT * FROM session WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
    if not s:
        raise NotFound("训练记录不存在")
    return row_to_dict(s)


async def start_session(user_id: str, drill_id: int) -> dict:
    provider = get_provider()
    with get_conn() as conn:
        drill = _load_drill(conn, drill_id)
        sid = conn.execute(
            "INSERT INTO session(user_id, drill_id, started_at) VALUES (?,?,?)", (user_id, drill_id, now_str())
        ).lastrowid
    t0 = time.perf_counter()
    text = await provider.opening(drill)
    llm_ms = int((time.perf_counter() - t0) * 1000)
    with get_conn() as conn:
        _append(conn, sid, "ai", text)
    t1 = time.perf_counter()
    audio_url = await _synthesize(provider, sid, text)
    tts_ms = int((time.perf_counter() - t1) * 1000)
    return {
        "session_id": sid,
        "mock": provider.mock,
        "provider": provider.name,
        "ai": {"text": text, "audio_url": audio_url},
        "timings": {"llm_ms": llm_ms, "tts_ms": tts_ms},
    }


async def run_turn(user_id: str, session_id: int, audio: bytes, fmt: str, sample_rate: int) -> dict:
    """一轮对话：识别用户语音 → 生成角色回复 → 合成语音。"""
    provider = get_provider()
    with get_conn() as conn:
        s = _get_session_row(conn, session_id, user_id)
        if s["status"] != "in_progress":
            raise BadRequest("训练已结束")
        drill = _load_drill(conn, s["drill_id"])
    if not audio or len(audio) < 1000:
        return {"empty": True, "user_text": "", "ai": None, "timings": {}}

    t0 = time.perf_counter()
    user_text = (await provider.transcribe(audio, fmt, sample_rate)).strip()
    asr_ms = int((time.perf_counter() - t0) * 1000)
    if not user_text:
        return {"empty": True, "user_text": "", "ai": None, "timings": {"asr_ms": asr_ms}}

    with get_conn() as conn:
        transcript = _append(conn, session_id, "user", user_text)
    t1 = time.perf_counter()
    ai_text = await provider.reply(drill, transcript)
    llm_ms = int((time.perf_counter() - t1) * 1000)
    with get_conn() as conn:
        _append(conn, session_id, "ai", ai_text)
    t2 = time.perf_counter()
    audio_url = await _synthesize(provider, session_id, ai_text)
    tts_ms = int((time.perf_counter() - t2) * 1000)
    return {
        "empty": False,
        "user_text": user_text,
        "ai": {"text": ai_text, "audio_url": audio_url},
        "timings": {"asr_ms": asr_ms, "llm_ms": llm_ms, "tts_ms": tts_ms},
    }


async def end_session(user_id: str, session_id: int, reason: str = "finish") -> dict:
    """结束训练：计算时长 → 判定状态 → completed 时调用 LLM 生成报告。"""
    with get_conn() as conn:
        s = _get_session_row(conn, session_id, user_id)
        if s["status"] != "in_progress":  # 幂等：重复结束直接返回
            return get_session_detail(user_id, session_id)
        drill = _load_drill(conn, s["drill_id"])
        ended = now()
        duration = max(0, int((ended - parse_time(s["started_at"])).total_seconds()))
        transcript = loads(s["transcript"], [])
        user_turns = sum(1 for t in transcript if t["role"] == "user")
        status = report_svc.decide_status(reason, duration, user_turns)
        conn.execute(
            "UPDATE session SET ended_at = ?, duration_sec = ?, status = ? WHERE id = ?",
            (ended.strftime(TIME_FMT), duration, status, session_id),
        )

    if status == "completed":
        try:
            rep = await report_svc.generate_report(drill, transcript, duration)
            with get_conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO report(session_id, scores, total_score, summary, highlights,
                       improvements, detail_comment, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                    (session_id, dumps(rep["scores"]), rep["total_score"], rep["summary"],
                     dumps(rep["highlights"]), dumps(rep["improvements"]), rep["detail_comment"], now_str()),
                )
        except Exception as e:  # noqa: BLE001
            log.exception("报告生成失败：%s", e)
    return get_session_detail(user_id, session_id)


async def retry_report(user_id: str, session_id: int) -> dict:
    with get_conn() as conn:
        s = _get_session_row(conn, session_id, user_id)
        if s["status"] != "completed":
            raise BadRequest("该训练没有可生成的报告")
        drill = _load_drill(conn, s["drill_id"])
    rep = await report_svc.generate_report(drill, loads(s["transcript"], []), s["duration_sec"])
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO report(session_id, scores, total_score, summary, highlights,
               improvements, detail_comment, created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (session_id, dumps(rep["scores"]), rep["total_score"], rep["summary"],
             dumps(rep["highlights"]), dumps(rep["improvements"]), rep["detail_comment"], now_str()),
        )
    return get_session_detail(user_id, session_id)


# ---------------- 记录 & 报告 ----------------

def _report_dict(r) -> dict:
    if not r:
        return None
    r = row_to_dict(r)
    for k, default in (("scores", {}), ("highlights", []), ("improvements", [])):
        r[k] = loads(r[k], default)
    return r


def _summary_line(status: str, report: dict) -> str:
    if status == "too_short":
        return report_svc.TOO_SHORT_TEXT
    if status == "abandoned":
        return report_svc.ABANDONED_TEXT
    if status == "in_progress":
        return "训练进行中。"
    if not report:
        return report_svc.FAILED_TEXT
    return report.get("summary") or "报告已生成。"


def _expire_stale(conn, user_id: str) -> None:
    """长时间未结束的会话（如直接杀掉小程序）标记为主动放弃。"""
    cutoff = (now() - timedelta(minutes=config.STALE_SESSION_MIN)).strftime(TIME_FMT)
    conn.execute(
        "UPDATE session SET status='abandoned' WHERE user_id = ? AND status='in_progress' AND started_at < ?",
        (user_id, cutoff),
    )


def get_session_detail(user_id: str, session_id: int) -> dict:
    with get_conn() as conn:
        s = _get_session_row(conn, session_id, user_id)
        drill = _public_drill(_load_drill(conn, s["drill_id"]))
        rep = _report_dict(conn.execute("SELECT * FROM report WHERE session_id = ?", (session_id,)).fetchone())
    s["transcript"] = loads(s["transcript"], [])
    s["drill"] = drill
    s["report"] = rep
    s["summary_line"] = _summary_line(s["status"], rep)
    return s


def list_sessions(user_id: str, range_: str = "all", page: int = 1, page_size: int = 20) -> dict:
    where, params = ["s.user_id = ?"], [user_id]
    today = now().replace(hour=0, minute=0, second=0)
    if range_ == "week":
        start = today - timedelta(days=today.weekday())
        where.append("s.started_at >= ?")
        params.append(start.strftime(TIME_FMT))
    elif range_ == "month":
        where.append("s.started_at >= ?")
        params.append(today.replace(day=1).strftime(TIME_FMT))
    page = max(1, page)
    page_size = max(1, min(50, page_size))
    with get_conn() as conn:
        _expire_stale(conn, user_id)
        total = conn.execute(f"SELECT COUNT(*) FROM session s WHERE {' AND '.join(where)}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT s.id, s.drill_id, s.started_at, s.ended_at, s.duration_sec, s.status,
                       d.title AS drill_title, d.pressure_level,
                       r.summary AS report_summary, r.total_score
                FROM session s JOIN drill d ON d.id = s.drill_id
                LEFT JOIN report r ON r.session_id = s.id
                WHERE {' AND '.join(where)}
                ORDER BY s.started_at DESC, s.id DESC LIMIT ? OFFSET ?""",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
    items = []
    for r in rows:
        r = row_to_dict(r)
        rep = {"summary": r.pop("report_summary")} if r["total_score"] is not None else None
        r["summary_line"] = _summary_line(r["status"], rep)
        items.append(r)
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "has_more": page * page_size < total}


def get_stats(user_id: str) -> dict:
    with get_conn() as conn:
        r = conn.execute(
            """SELECT COUNT(*) AS total, COALESCE(SUM(duration_sec),0) AS seconds,
                      SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed
               FROM session WHERE user_id = ?""", (user_id,)).fetchone()
        avg = conn.execute(
            """SELECT AVG(r.total_score) FROM report r JOIN session s ON s.id = r.session_id
               WHERE s.user_id = ?""", (user_id,)).fetchone()[0]
    return {"total": r["total"], "minutes": round(r["seconds"] / 60), "completed": r["completed"] or 0,
            "avg_score": round(avg) if avg is not None else None}
