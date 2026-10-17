"""业务逻辑：内容查询、训练会话、报告、训练记录。与 Web 框架无关，便于测试。"""
import asyncio
import hashlib
import json
import os
import logging
import time
import uuid
from datetime import timedelta

from .. import config
from ..db import dumps, get_conn, loads, now, now_str, parse_time, row_to_dict, TIME_FMT
from . import metrics as metrics_svc
from . import report as report_svc
from .voice import get_provider

log = logging.getLogger("talktool")


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


from .quota import QuotaExceeded as TooMany  # noqa: E402  超限 → 429
from . import quota  # noqa: E402

# 后台任务（报告生成）：持有引用防止被回收；测试里可以 await drain_tasks()
_tasks = set()


def _spawn(coro):
    t = asyncio.get_running_loop().create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t


async def drain_tasks():
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


# ---------------- 内容 ----------------

def list_categories() -> list:
    """P1：公共分类 + 各分类下的场景大类（含训练卡片数量）。"""
    with get_conn() as conn:
        cats = [row_to_dict(r) for r in conn.execute(
            "SELECT * FROM category WHERE is_system = 0 ORDER BY sort_order, id")]
        rows = conn.execute(
            """SELECT s.*, (SELECT COUNT(*) FROM drill d WHERE d.scenario_id = s.id AND d.status='online'
                              AND d.owner_id IS NULL) AS drill_count
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
               WHERE s.id = ? AND c.is_system = 0""", (scenario_id,)).fetchone()
        if not s:
            raise NotFound("场景不存在")
        drills = conn.execute(
            """SELECT * FROM drill WHERE scenario_id = ? AND status='online' AND owner_id IS NULL
               ORDER BY sort_order, id""", (scenario_id,)
        ).fetchall()
    out = row_to_dict(s)
    out["drills"] = [_public_drill(row_to_dict(d)) for d in drills]
    return out


def _load_drill(conn, drill_id: int, user_id: str = None) -> dict:
    """读取训练；传入 user_id 时校验自定义场景只能本人访问。"""
    d = conn.execute(
        """SELECT d.*, s.title AS scenario_title, c.name AS category_name, c.id AS category_id
           FROM drill d JOIN scenario s ON s.id = d.scenario_id JOIN category c ON c.id = s.category_id
           WHERE d.id = ?""", (drill_id,)).fetchone()
    if not d:
        raise NotFound("训练不存在")
    d = row_to_dict(d)
    if user_id is not None and d.get("owner_id") and d["owner_id"] != user_id:
        raise NotFound("训练不存在")
    d["is_custom"] = bool(d.get("owner_id"))
    return d


def _public_drill(d: dict) -> dict:
    d = dict(d)
    d.pop("system_prompt", None)  # 不把内部 prompt 暴露给前端
    d.pop("owner_id", None)
    d.pop("sample_script", None)
    if isinstance(d.get("pitfalls"), str):
        d["pitfalls"] = loads(d["pitfalls"], [])
    return d


def get_drill(drill_id: int, user_id: str = None) -> dict:
    """P3：训练详情（附带推荐表达框架、常见误区，以及该用户在这个场景的最好成绩和练习次数）。"""
    from .frameworks import drill_guide
    with get_conn() as conn:
        d = _public_drill(_load_drill(conn, drill_id, user_id))
        d["frameworks"] = drill_guide(conn, drill_id)
        if user_id:
            r = conn.execute(
                """SELECT COUNT(*) AS times, MAX(r.total_score) AS best FROM session s
                   LEFT JOIN report r ON r.session_id = s.id
                   WHERE s.user_id = ? AND s.drill_id = ? AND s.status != 'in_progress'""",
                (user_id, drill_id)).fetchone()
            d["my_times"], d["my_best"] = r["times"], r["best"]
    return d


# ---------------- 语音 ----------------

def _audio_url(name: str) -> str:
    return f"{config.PUBLIC_BASE_URL}/media/audio/{name}"


async def _synthesize(provider, session_id, text: str, cache: bool = False):
    """合成语音并保存为文件；失败时不阻断（前端退化为按时长模拟）。cache=True 时同一文本复用文件。"""
    if cache:
        name = "t_" + hashlib.sha1(f"{config.TTS_VOICE}|{config.TTS_SPEED}|{text}".encode()).hexdigest()[:20] + ".mp3"
        path = config.AUDIO_DIR / name
        if path.exists():
            try:
                os.utime(path)  # 记录最近使用时间，清理任务只删很久没用的缓存
            except OSError:
                pass
            return _audio_url(name)
    else:
        name = f"s{session_id}_{uuid.uuid4().hex[:10]}.mp3"
    try:
        audio = await provider.synthesize(text)
    except Exception as e:  # noqa: BLE001
        log.warning("TTS 失败：%s", e)
        return None
    if not audio:
        return None
    (config.AUDIO_DIR / name).write_bytes(audio)
    return _audio_url(name)


def _tts_allowed(user_id: str, text: str) -> bool:
    """只允许朗读系统生成过的内容：本人的收藏、本人报告里的逐句示范、场景示范稿、框架示例。
    分句预取时会传示范稿的连续子串（≥6 字），同样放行；防止被拿去合成任意文字。"""
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM note WHERE user_id = ? AND text = ?", (user_id, text)).fetchone():
            return True
        if conn.execute("SELECT 1 FROM drill WHERE sample_script = ? AND sample_script != ''", (text,)).fetchone():
            return True
        # 表达框架的示例（详情页超长示例只读前 480 字）
        if conn.execute("SELECT 1 FROM framework WHERE example = ? OR substr(example, 1, 480) = ?",
                        (text, text)).fetchone():
            return True
        rows = conn.execute(
            """SELECT r.turn_reviews FROM report r JOIN session s ON s.id = r.session_id
               WHERE s.user_id = ? AND r.turn_reviews NOT IN ('[]', 'null', '')
               ORDER BY r.id DESC LIMIT 200""", (user_id,)).fetchall()
    for r in rows:
        for item in loads(r[0], None) or []:
            if isinstance(item, dict) and item.get("better") == text:
                return True
    # 分句朗读：连续子串（与小树学堂首句先出声一致）
    if len(text) < 6:
        return False
    with get_conn() as conn:
        if conn.execute(
            "SELECT 1 FROM note WHERE user_id = ? AND instr(text, ?) > 0 LIMIT 1", (user_id, text)
        ).fetchone():
            return True
        if conn.execute(
            "SELECT 1 FROM drill WHERE sample_script != '' AND instr(sample_script, ?) > 0 LIMIT 1", (text,)
        ).fetchone():
            return True
        if conn.execute(
            "SELECT 1 FROM framework WHERE instr(example, ?) > 0 LIMIT 1", (text,)
        ).fetchone():
            return True
        rows = conn.execute(
            """SELECT r.turn_reviews FROM report r JOIN session s ON s.id = r.session_id
               WHERE s.user_id = ? AND r.turn_reviews NOT IN ('[]', 'null', '')
               ORDER BY r.id DESC LIMIT 200""", (user_id,)).fetchall()
    for r in rows:
        for item in loads(r[0], None) or []:
            better = item.get("better") if isinstance(item, dict) else None
            if isinstance(better, str) and text in better:
                return True
    return False


def _tts_cached(text: str) -> bool:
    name = "t_" + hashlib.sha1(f"{config.TTS_VOICE}|{config.TTS_SPEED}|{text}".encode()).hexdigest()[:20] + ".mp3"
    return (config.AUDIO_DIR / name).exists()


async def tts(text: str, user_id: str = None) -> dict:
    """示范话术朗读（练习本 / 报告逐句示范用），按文本缓存。"""
    text = (text or "").strip()
    if not text:
        raise BadRequest("文本为空")
    if len(text) > 500:
        raise BadRequest("文本过长（最多 500 字）")
    provider = get_provider()
    if user_id is not None and not _tts_cached(text):
        if not _tts_allowed(user_id, text):
            raise BadRequest("只能朗读示范话术")
        if not provider.mock:
            quota.hit(user_id, "tts", config.DAILY_TTS_LIMIT, "今天的示范朗读次数已用完，明天再来吧")
    return {"audio_url": await _synthesize(provider, None, text, cache=True), "mock": provider.mock}


# ---------------- 训练会话 ----------------

def _append(conn, session_id: int, role: str, text: str, extra: dict = None) -> list:
    row = conn.execute("SELECT transcript FROM session WHERE id = ?", (session_id,)).fetchone()
    transcript = loads(row["transcript"], [])
    item = {"role": role, "text": text, "at": now_str()}
    if extra:
        item.update(extra)
    transcript.append(item)
    conn.execute("UPDATE session SET transcript = ? WHERE id = ?", (dumps(transcript), session_id))
    return transcript


def _get_session_row(conn, session_id: int, user_id: str) -> dict:
    s = conn.execute("SELECT * FROM session WHERE id = ? AND user_id = ?", (session_id, user_id)).fetchone()
    if not s:
        raise NotFound("训练记录不存在")
    return row_to_dict(s)


def _check_daily_limit(conn, user_id: str, ip: str) -> None:
    """防刷：每个用户 / 每个 IP 每天能开始的训练数。用户 ID 由前端生成可以伪造，所以再按 IP 兜底。"""
    today = now().replace(hour=0, minute=0, second=0).strftime(TIME_FMT)
    if config.DAILY_SESSION_LIMIT:
        n = conn.execute("SELECT COUNT(*) FROM session WHERE user_id = ? AND started_at >= ?",
                         (user_id, today)).fetchone()[0]
        if n >= config.DAILY_SESSION_LIMIT:
            raise TooMany(f"今天已经练了 {n} 次，休息一下，明天再来吧")
    if config.DAILY_IP_SESSION_LIMIT and ip:
        n = conn.execute("SELECT COUNT(*) FROM session WHERE ip = ? AND started_at >= ?", (ip, today)).fetchone()[0]
        if n >= config.DAILY_IP_SESSION_LIMIT:
            raise TooMany("当前网络今天的训练次数已达上限，请明天再试")


async def start_session(user_id: str, drill_id: int, ip: str = None) -> dict:
    provider = get_provider()
    with get_conn() as conn:
        drill = _load_drill(conn, drill_id, user_id)
        if drill["status"] != "online":
            raise BadRequest("该场景已删除")
        _check_daily_limit(conn, user_id, ip)
        sid = conn.execute(
            "INSERT INTO session(user_id, drill_id, started_at, ip) VALUES (?,?,?,?)",
            (user_id, drill_id, now_str(), ip)
        ).lastrowid
    t0 = time.perf_counter()
    text = await provider.opening(drill)
    llm_ms = int((time.perf_counter() - t0) * 1000)
    with get_conn() as conn:
        _append(conn, sid, "ai", text)
    t1 = time.perf_counter()
    # 固定开场白按文字缓存：同一场景只合成一次
    audio_url = await _synthesize(provider, sid, text, cache=bool(drill.get("opening_line")))
    tts_ms = int((time.perf_counter() - t1) * 1000)
    return {
        "session_id": sid,
        "mock": provider.mock,
        "provider": provider.name,
        "ai": {"text": text, "audio_url": audio_url},
        "timings": {"llm_ms": llm_ms, "tts_ms": tts_ms},
    }


async def run_turn(user_id: str, session_id: int, audio: bytes, fmt: str, sample_rate: int) -> dict:
    """一轮对话：识别用户语音 → 计算表达数据 → 生成角色回复 → 合成语音。"""
    provider = get_provider()
    with get_conn() as conn:
        s = _get_session_row(conn, session_id, user_id)
        if s["status"] != "in_progress":
            raise BadRequest("训练已结束")
        drill = _load_drill(conn, s["drill_id"])
    turns = sum(1 for t in loads(s["transcript"], []) if t.get("role") == "user")
    if config.MAX_USER_TURNS and turns >= config.MAX_USER_TURNS:
        raise BadRequest("本次训练轮数已达上限，请点“结束训练”查看报告")
    if not audio or len(audio) < 1000:
        return {"empty": True, "user_text": "", "ai": None, "timings": {}}

    try:
        audio_info = metrics_svc.analyze_audio(audio, fmt, sample_rate)
    except Exception as e:  # noqa: BLE001  表达数据只是锦上添花，失败不影响对话
        log.warning("录音分析失败：%s", e)
        audio_info = {}
    # 录音里几乎没有人声（环境噪声、误触）→ 不送识别，省一次调用
    if audio_info and (audio_info.get("speech_ms") or 0) < config.ASR_MIN_SPEECH_MS:
        return {"empty": True, "reason": "no_speech", "user_text": "", "ai": None, "timings": {}}

    t0 = time.perf_counter()
    user_text = (await provider.transcribe(audio, fmt, sample_rate, session_id)).strip()
    asr_ms = int((time.perf_counter() - t0) * 1000)
    if not user_text:
        return {"empty": True, "user_text": "", "ai": None, "timings": {"asr_ms": asr_ms}}

    m = metrics_svc.turn_metrics(audio_info, user_text) if audio_info else None
    with get_conn() as conn:
        transcript = _append(conn, session_id, "user", user_text, {"metrics": m} if m else None)
    t1 = time.perf_counter()
    ai_text = await provider.reply(drill, transcript, session_id)
    llm_ms = int((time.perf_counter() - t1) * 1000)
    with get_conn() as conn:
        _append(conn, session_id, "ai", ai_text)
    t2 = time.perf_counter()
    audio_url = await _synthesize(provider, session_id, ai_text)
    tts_ms = int((time.perf_counter() - t2) * 1000)
    return {
        "empty": False,
        "user_text": user_text,
        "metrics": m,
        "ai": {"text": ai_text, "audio_url": audio_url},
        "timings": {"asr_ms": asr_ms, "llm_ms": llm_ms, "tts_ms": tts_ms},
    }


def _save_report(conn, session_id: int, rep: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO report(session_id, scores, total_score, summary, highlights,
           improvements, detail_comment, turn_reviews, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (session_id, dumps(rep["scores"]), rep["total_score"], rep["summary"], dumps(rep["highlights"]),
         dumps(rep["improvements"]), rep["detail_comment"], dumps(rep.get("turn_reviews")), now_str()),
    )


async def _report_job(session_id: int, retry: bool = False) -> None:
    """后台生成报告：成功 → ready，失败 → failed（前端可点“重新生成”）。"""
    try:
        from .frameworks import guide_text
        with get_conn() as conn:
            s = row_to_dict(conn.execute("SELECT * FROM session WHERE id = ?", (session_id,)).fetchone())
            drill = _load_drill(conn, s["drill_id"])
            drill["guide_text"] = guide_text(conn, s["drill_id"])
        transcript = loads(s["transcript"], [])
        summary = loads(s.get("metrics"), {}) or metrics_svc.summarize(transcript)
        rep = await report_svc.generate_report(drill, transcript, s["duration_sec"], metrics_svc.describe(summary),
                                               session_id=session_id, retry=retry)
        with get_conn() as conn:
            _save_report(conn, session_id, rep)
            conn.execute("UPDATE session SET report_status = 'ready' WHERE id = ?", (session_id,))
    except Exception as e:  # noqa: BLE001
        log.exception("报告生成失败 session=%s：%s", session_id, e)
        with get_conn() as conn:
            conn.execute("UPDATE session SET report_status = 'failed' WHERE id = ?", (session_id,))


async def end_session(user_id: str, session_id: int, reason: str = "finish") -> dict:
    """结束训练：计算时长 → 判定状态 → 汇总表达数据 → completed 时在后台生成报告，接口立即返回。"""
    with get_conn() as conn:
        s = _get_session_row(conn, session_id, user_id)
        if s["status"] != "in_progress":  # 幂等：重复结束直接返回
            return get_session_detail(user_id, session_id)
        ended = now()
        duration = max(0, int((ended - parse_time(s["started_at"])).total_seconds()))
        transcript = loads(s["transcript"], [])
        user_turns = sum(1 for t in transcript if t["role"] == "user")
        status = report_svc.decide_status(reason, duration, user_turns)
        summary = metrics_svc.summarize(transcript)
        conn.execute(
            """UPDATE session SET ended_at = ?, duration_sec = ?, status = ?, metrics = ?, report_status = ?
               WHERE id = ?""",
            (ended.strftime(TIME_FMT), duration, status, dumps(summary),
             "pending" if status == "completed" else "none", session_id),
        )
    if status == "completed":
        _spawn(_report_job(session_id))
    return get_session_detail(user_id, session_id)


async def retry_report(user_id: str, session_id: int) -> dict:
    with get_conn() as conn:
        s = _get_session_row(conn, session_id, user_id)
        if s["status"] != "completed":
            raise BadRequest("该训练没有可生成的报告")
        if s.get("report_status") == "pending":
            return get_session_detail(user_id, session_id)
    if not config.MOCK:
        quota.hit(user_id, "review", config.DAILY_REVIEW_LIMIT, "今天的报告重新生成次数已用完")
    with get_conn() as conn:
        conn.execute("UPDATE session SET report_status = 'pending' WHERE id = ?", (session_id,))
    _spawn(_report_job(session_id, retry=True))
    return get_session_detail(user_id, session_id)


def recover_pending_reports() -> int:
    """服务重启时，把中断的“生成中”标为失败，用户可以重新生成。"""
    with get_conn() as conn:
        return conn.execute("UPDATE session SET report_status = 'failed' WHERE report_status = 'pending'").rowcount


async def get_turn_reviews(user_id: str, session_id: int) -> list:
    """逐句复盘：报告里展开时才生成，生成后存进报告，再看不再花钱。"""
    with get_conn() as conn:
        s = _get_session_row(conn, session_id, user_id)
        r = conn.execute("SELECT turn_reviews FROM report WHERE session_id = ?", (session_id,)).fetchone()
        if not r:
            raise BadRequest("这次训练没有报告")
        cached = loads(r["turn_reviews"], None)
        if cached:
            return cached
        from .frameworks import guide_text
        drill = _load_drill(conn, s["drill_id"])
        drill["guide_text"] = guide_text(conn, s["drill_id"])
    if not config.MOCK:
        quota.hit(user_id, "review", config.DAILY_REVIEW_LIMIT, "今天的复盘生成次数已用完，明天再来吧")
    reviews = await report_svc.generate_turn_reviews(drill, loads(s["transcript"], []), session_id)
    with get_conn() as conn:
        conn.execute("UPDATE report SET turn_reviews = ? WHERE session_id = ?", (dumps(reviews), session_id))
    return reviews


# ---------------- 记录 & 报告 ----------------

def _report_dict(r) -> dict:
    if not r:
        return None
    r = row_to_dict(r)
    for k, default in (("scores", {}), ("highlights", []), ("improvements", []), ("turn_reviews", None)):
        r[k] = loads(r.get(k), default)
    return r


def _report_status(status: str, stored: str, report) -> str:
    """报告状态：ready / pending / failed / none（旧数据没有该字段，按有无报告推断）。"""
    if status != "completed":
        return "none"
    if stored == "pending":  # 生成中（含“重新生成”时旧报告还在）
        return "pending"
    if report:
        return "ready"
    return stored if stored in ("pending", "failed") else "failed"


def _summary_line(status: str, report: dict, report_status: str = None) -> str:
    if report_status == "pending":
        return "报告生成中…"
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


def _previous_result(conn, user_id: str, s: dict):
    """同一场景上一次有报告的训练，用于进步对比。"""
    r = conn.execute(
        """SELECT s.id AS session_id, s.started_at, r.total_score, r.scores FROM session s
           JOIN report r ON r.session_id = s.id
           WHERE s.user_id = ? AND s.drill_id = ? AND s.status = 'completed'
             AND (s.started_at < ? OR (s.started_at = ? AND s.id < ?))
           ORDER BY s.started_at DESC, s.id DESC LIMIT 1""",
        (user_id, s["drill_id"], s["started_at"], s["started_at"], s["id"])).fetchone()
    if not r:
        return None
    r = row_to_dict(r)
    r["scores"] = loads(r["scores"], {})
    return r


def get_session_detail(user_id: str, session_id: int) -> dict:
    with get_conn() as conn:
        s = _get_session_row(conn, session_id, user_id)
        drill = _public_drill(_load_drill(conn, s["drill_id"]))
        from .frameworks import drill_guide
        drill["frameworks"] = drill_guide(conn, s["drill_id"])
        rep = _report_dict(conn.execute("SELECT * FROM report WHERE session_id = ?", (session_id,)).fetchone())
        prev = _previous_result(conn, user_id, s) if rep else None
        notes = [row_to_dict(n) for n in conn.execute(
            "SELECT id, kind, text FROM note WHERE user_id = ? AND session_id = ?", (user_id, session_id))]
    s["transcript"] = loads(s["transcript"], [])
    s["metrics"] = loads(s.get("metrics"), {}) or metrics_svc.summarize(s["transcript"])
    s["drill"] = drill
    s["report"] = rep
    s["previous"] = prev
    s["saved_notes"] = notes
    s["report_status"] = _report_status(s["status"], s.get("report_status"), rep)
    s["summary_line"] = _summary_line(s["status"], rep, s["report_status"])
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
            f"""SELECT s.id, s.drill_id, s.started_at, s.ended_at, s.duration_sec, s.status, s.report_status,
                       d.title AS drill_title, d.pressure_level, d.owner_id IS NOT NULL AS is_custom,
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
        r["is_custom"] = bool(r["is_custom"])
        rep = {"summary": r.pop("report_summary")} if r["total_score"] is not None else None
        r["report_status"] = _report_status(r["status"], r["report_status"], rep)
        r["summary_line"] = _summary_line(r["status"], rep, r["report_status"])
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
        notes = conn.execute("SELECT COUNT(*) FROM note WHERE user_id = ?", (user_id,)).fetchone()[0]
    return {"total": r["total"], "minutes": round(r["seconds"] / 60), "completed": r["completed"] or 0,
            "avg_score": round(avg) if avg is not None else None, "notes": notes}
