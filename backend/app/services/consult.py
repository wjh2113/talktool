"""问计：一次和智囊团的对话。

接口节奏（让用户尽快看到“已交给××团”）：
  POST /api/consults                 用户描述 → 意图识别 → 路由：追问 / 安全回复 / 选团 / 已分派(routed)
  POST /api/consults/{id}/messages   回答追问(answer) / 继续问(ask) / 复盘(review)
  POST /api/consults/{id}/plan       由分派到的（或用户指定的）智囊团出锦囊
  POST /api/consults/{id}/roundtable 圆桌会议：几位谋士辩论，军师裁决
跟进：出锦囊时按紧急程度定 follow_up_at；行动可设提醒日期；到期的出现在智囊首页“该跟进了”。
"""
import logging
import re
from datetime import timedelta

from .. import config
from ..db import TIME_FMT, dumps, get_conn, loads, now, now_str, row_to_dict, set_drill_guide, system_scenario_id
from . import memory, quota, workflow
from . import strategies as st
from .sessions import BadRequest, NotFound, _spawn

log = logging.getLogger("talktool.consult")

STATUS_TEXT = {"asking": "识别中", "clarifying": "等你补充", "routed": "已分派", "planned": "已出锦囊",
               "safety": "安全提醒", "failed": "生成失败"}


FOLLOW_UP_DAYS = {"high": 1, "normal": 3, "low": 7}   # 出锦囊后多久提醒回来复盘


def _after_days(days: float) -> str:
    return (now() + timedelta(days=days)).strftime(TIME_FMT)


def hint_date(hint: str):
    """把锦囊里的时机（今天 / 明天 / 本周内 / 下周……）粗略换成提醒日期；认不出来就不设。"""
    h = (hint or "").strip()
    if not h:
        return None
    today = now().date()
    days = None
    if re.search(r"今天|今晚|当天|马上|立刻|尽快", h):
        days = 0
    elif "后天" in h:
        days = 2
    elif re.search(r"明天|明早|次日", h):
        days = 1
    elif re.search(r"下周|下星期", h):
        days = 7 - today.weekday()      # 下周一
    elif re.search(r"本周|这周|这几天|一周内|7天内|七天内", h):
        days = max(1, 4 - today.weekday()) if today.weekday() < 4 else 1   # 本周五，周五以后给一天
    elif re.search(r"月底|本月", h):
        days = 10
    else:
        m = re.search(r"(\d+|[一二三两四五六七八九十]+)\s*天", h)
        if m:
            cn = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            v = m.group(1)
            days = int(v) if v.isdigit() else cn.get(v, None)
    if days is None:
        return None
    return (today + timedelta(days=min(days, 60))).isoformat()


# ---------------- 读 ----------------

def _get(conn, user_id: str, consult_id: int) -> dict:
    r = conn.execute("SELECT * FROM consult WHERE id = ? AND user_id = ?", (consult_id, user_id)).fetchone()
    if not r:
        raise NotFound("问计不存在")
    c = row_to_dict(r)
    c["intent"] = loads(c["intent"], {})
    c["extra_advisors"] = loads(c.get("extra_advisors"), []) or []
    return c


def _latest_plan(conn, consult_id: int) -> dict:
    r = conn.execute("SELECT * FROM plan WHERE consult_id = ? ORDER BY version DESC LIMIT 1", (consult_id,)).fetchone()
    return _plan_out(conn, r) if r else None


def _plan_out(conn, r) -> dict:
    p = row_to_dict(r)
    content = loads(p["content"], {})
    codes = [s["code"] for s in content.get("strategies", [])]
    details = {s["code"]: s for s in st.by_codes(codes)}
    for s in content.get("strategies", []):
        d = details.get(s["code"])
        if d:
            s.update({"name": d["name"], "school_name": d["school_name"], "origin": d["origin"], "caution": d["caution"]})
    fw_names = {}
    for ln in content.get("lines", []):
        if ln.get("framework") and ln["framework"] not in fw_names:
            f = conn.execute("SELECT name FROM framework WHERE code = ?", (ln["framework"],)).fetchone()
            fw_names[ln["framework"]] = f[0] if f else ""
        ln["framework_name"] = fw_names.get(ln.get("framework"), "")
    names = {r2["code"]: (r2["name"], r2["avatar"]) for r2 in conn.execute("SELECT code, name, avatar FROM advisor")}
    for v in content.get("advisor_views", []):
        v["name"], v["avatar"] = names.get(v["advisor"], (v["advisor"], ""))
    actions = [row_to_dict(a) for a in conn.execute(
        "SELECT id, text, due_hint, done, result, done_at, remind_at FROM plan_action WHERE plan_id = ? ORDER BY sort_order",
        (p["id"],))]
    for a in actions:
        a["done"] = bool(a["done"])
    versions = [v[0] for v in conn.execute("SELECT version FROM plan WHERE consult_id = ? ORDER BY version", (p["consult_id"],))]
    return {"id": p["id"], "version": p["version"], "versions": versions, "content": content, "actions": actions,
            "memory_refs": loads(p["memory_refs"], []), "drill_id": p["drill_id"], "created_at": p["created_at"],
            "rating": p.get("rating"), "rating_reason": p.get("rating_reason") or ""}


def get_detail(user_id: str, consult_id: int, version: int = None) -> dict:
    with get_conn() as conn:
        c = _get(conn, user_id, consult_id)
        msgs = []
        for m in conn.execute("SELECT * FROM consult_message WHERE consult_id = ? ORDER BY id", (consult_id,)):
            d = row_to_dict(m)
            d["data"] = loads(d["data"], {})
            msgs.append(d)
        if version:
            r = conn.execute("SELECT * FROM plan WHERE consult_id = ? AND version = ?", (consult_id, version)).fetchone()
            plan = _plan_out(conn, r) if r else None
        else:
            plan = _latest_plan(conn, consult_id)
    council = workflow.get_council(c["council_code"]) if c["council_code"] else None
    with get_conn() as conn:
        mine = {r["code"]: row_to_dict(r) for r in conn.execute(
            "SELECT code, name, avatar, style FROM advisor WHERE owner_id = ?", (user_id,))}
    extra = [mine[x] for x in c["extra_advisors"] if x in mine]
    return {"id": c["id"], "title": c["title"], "status": c["status"], "status_text": STATUS_TEXT.get(c["status"], ""),
            "follow_up_at": c.get("follow_up_at"), "extra_advisors": extra,
            "intent": c["intent"], "summary": c["situation_summary"], "case_id": c["case_id"],
            "council": council and {"code": council["code"], "name": council["name"], "icon": council["icon"],
                                    "advisors": council["advisor_list"]},
            "candidates": [{"code": x["code"], "name": x["name"]} for x in workflow.councils()
                           if x["code"] in (c["intent"].get("candidates") or [])],
            "messages": msgs, "plan": plan, "created_at": c["created_at"], "updated_at": c["updated_at"]}


def list_consults(user_id: str, limit: int = 50) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.id, c.title, c.status, c.council_code, c.updated_at, c.case_id,
                      (SELECT content FROM plan p WHERE p.consult_id = c.id ORDER BY version DESC LIMIT 1) AS plan
               FROM consult c WHERE c.user_id = ? ORDER BY c.updated_at DESC LIMIT ?""", (user_id, limit)).fetchall()
    names = {x["code"]: x["name"] for x in workflow.councils(enabled_only=False)}
    out = []
    for r in rows:
        d = row_to_dict(r)
        plan = loads(d.pop("plan"), {}) if d.get("plan") else {}
        d["headline"] = plan.get("headline", "")
        d["council_name"] = names.get(d["council_code"], "")
        d["status_text"] = STATUS_TEXT.get(d["status"], "")
        out.append(d)
    return out


def ongoing_cases(user_id: str) -> list:
    """智囊首页“进行中的事”：未完成的事件线 + 最近一次问计 + 未完成的行动。"""
    with get_conn() as conn:
        cases = [row_to_dict(r) for r in conn.execute(
            "SELECT id, name, summary, last_seen FROM memory_subject WHERE user_id = ? AND kind = 'case' AND status = 'open' "
            "ORDER BY last_seen DESC LIMIT 6", (user_id,))]
        for c in cases:
            r = conn.execute("SELECT id FROM consult WHERE user_id = ? AND case_id = ? ORDER BY updated_at DESC LIMIT 1",
                             (user_id, c["id"])).fetchone()
            c["consult_id"] = r[0] if r else None
            c["next_action"] = ""
            c["pending"] = 0
            if r:
                p = conn.execute("SELECT id FROM plan WHERE consult_id = ? ORDER BY version DESC LIMIT 1", (r[0],)).fetchone()
                if p:
                    todo = [a[0] for a in conn.execute(
                        "SELECT text FROM plan_action WHERE plan_id = ? AND done = 0 ORDER BY sort_order", (p[0],))]
                    c["pending"] = len(todo)
                    c["next_action"] = todo[0] if todo else ""
    return cases


# ---------------- 写 ----------------

def _add_msg(conn, consult_id: int, role: str, kind: str, text: str, data: dict = None, plan_id: int = None):
    conn.execute("""INSERT INTO consult_message(consult_id, role, kind, text, data, plan_id, created_at)
                    VALUES (?,?,?,?,?,?,?)""", (consult_id, role, kind, text or "", dumps(data or {}), plan_id, now_str()))
    conn.execute("UPDATE consult SET updated_at = ? WHERE id = ?", (now_str(), consult_id))


def _user_text(conn, consult_id: int, kinds=("ask", "answer", "review")) -> str:
    rows = conn.execute(f"SELECT text FROM consult_message WHERE consult_id = ? AND role = 'user' AND kind IN "
                        f"({','.join('?' * len(kinds))}) ORDER BY id", (consult_id, *kinds)).fetchall()
    return "\n".join(r[0] for r in rows)


def _history(conn, consult_id: int, last: int = 12) -> str:
    rows = conn.execute("SELECT role, kind, text FROM consult_message WHERE consult_id = ? AND kind != 'route' "
                        "ORDER BY id DESC LIMIT ?", (consult_id, last)).fetchall()
    out = []
    for r in reversed(rows):
        who = "用户" if r["role"] == "user" else "智囊"
        out.append(f"{who}：{(r['text'] or '')[:300]}")
    return "\n".join(out)


def _check_size(conn, consult_id: int):
    n = conn.execute("SELECT COUNT(*) FROM consult_message WHERE consult_id = ?", (consult_id,)).fetchone()[0]
    if n >= config.CONSULT_MAX_MESSAGES:
        raise BadRequest("这次问计聊得很长了，新开一次问计吧（智囊会记得之前的情况）")


async def _transcribe(audio: bytes, fmt: str, sample_rate: int) -> str:
    from .voice import get_provider
    text = (await get_provider().transcribe(audio, fmt, sample_rate, None)).strip()
    if config.MOCK and not text:
        text = "（Mock 语音）老板总在会上否定我的方案，我想争取下季度的项目负责人"
    if not text:
        raise BadRequest("没听清，请再说一次或改用文字")
    return text


async def resolve_text(text: str, audio: bytes = None, fmt: str = "wav", sample_rate: int = 16000) -> str:
    if audio:
        text = await _transcribe(audio, fmt, sample_rate)
    text = (text or "").strip()
    if len(text) < 2:
        raise BadRequest("请说说你遇到的情况")
    if len(text) > 2000:
        raise BadRequest("描述太长了，2000 字以内即可")
    return text


async def create(user_id: str, text: str, council_code: str = None, advisors: list = None, job_id: str = None) -> dict:
    """新问计：识别意图 → 路由。用户直接点了某个智囊团时跳过识别里的选团环节；advisors = 请来列席的私人谋士。"""
    quota.hit(user_id, "consult", config.DAILY_CONSULT_LIMIT, "今天的提问次数已用完，明天再来吧")
    extra = workflow.valid_extra(user_id, advisors)
    with get_conn() as conn:
        cid = conn.execute("""INSERT INTO consult(user_id, title, council_code, extra_advisors, created_at, updated_at)
                              VALUES (?,?,?,?,?,?)""",
                           (user_id, text[:16], council_code or "", dumps(extra), now_str(), now_str())).lastrowid
        if job_id:
            conn.execute("UPDATE generation_job SET consult_id=? WHERE id=? AND user_id=?", (cid, job_id, user_id))
        _add_msg(conn, cid, "user", "ask", text)
    await _route(user_id, cid, text, history="", clarified=False, forced=council_code)
    return get_detail(user_id, cid)


async def _route(user_id: str, cid: int, message: str, history: str, clarified: bool, forced: str = None,
                 skip_clarify: bool = False) -> None:
    mem_text, _ = memory.context(user_id, history + "\n" + message)
    try:
        intent, _ = await workflow.run_intent(user_id, message, history, mem_text, cid)
    except Exception as e:  # noqa: BLE001
        log.exception("意图识别失败：%s", e)
        with get_conn() as conn:
            conn.execute("UPDATE consult SET status = 'failed' WHERE id = ?", (cid,))
            _add_msg(conn, cid, "advisor", "error", "智囊暂时没接上，请稍后重试。")
        return
    if forced and forced in {c["code"] for c in workflow.councils()} and intent["risk"] == "none":
        intent["council"], intent["confidence"], intent["candidates"] = forced, 1.0, []
    step = workflow.route(intent, clarified, skip_clarify or bool(forced))
    with get_conn() as conn:
        conn.execute("UPDATE consult SET intent = ?, title = ?, situation_summary = ?, council_code = ? WHERE id = ?",
                     (dumps(intent), intent["title"], intent["summary"], intent["council"], cid))
    if step == "safety":
        reply = await workflow.run_safety(user_id, message, intent["risk"], cid)
        with get_conn() as conn:
            conn.execute("UPDATE consult SET status = 'safety' WHERE id = ?", (cid,))
            _add_msg(conn, cid, "advisor", "safety", reply, {"risk": intent["risk"]})
        return
    if step == "clarify":
        q = await workflow.run_clarify(user_id, message, intent, mem_text, cid)
        with get_conn() as conn:
            conn.execute("UPDATE consult SET status = 'clarifying' WHERE id = ?", (cid,))
            _add_msg(conn, cid, "advisor", "clarify", q["intro"], q)
        return
    council = workflow.get_council(intent["council"])
    with get_conn() as conn:
        conn.execute("UPDATE consult SET status = 'routed' WHERE id = ?", (cid,))
        if step == "choose":
            _add_msg(conn, cid, "advisor", "route", "这件事可以从几个角度看，你想听哪个智囊团的？",
                     {"council": council["code"], "candidates": [council["code"]] + intent["candidates"]})
        else:
            _add_msg(conn, cid, "advisor", "route", f"已交给「{council['name']}」，" +
                     "、".join(a["name"] for a in council["advisor_list"]) + " 正在商议……",
                     {"council": council["code"]})


async def make_plan(user_id: str, consult_id: int, council_code: str = None) -> dict:
    """由智囊团出锦囊（首次，或换一个智囊团重新出）。"""
    with get_conn() as conn:
        c = _get(conn, user_id, consult_id)
        if c["status"] == "safety":
            raise BadRequest("这个问题智囊不提供谋略建议")
        _check_size(conn, consult_id)
        situation = c["situation_summary"] or _user_text(conn, consult_id)
        full = _user_text(conn, consult_id)
    code = council_code or c["council_code"] or "general"
    if council_code and council_code != c["council_code"]:
        with get_conn() as conn:
            conn.execute("UPDATE consult SET council_code = ? WHERE id = ?", (council_code, consult_id))
            council = workflow.get_council(council_code)
            _add_msg(conn, consult_id, "advisor", "route", f"换成「{council['name']}」重新商议……", {"council": council_code})
    mem_text, refs = memory.context(user_id, full, c["intent"].get("people"), c["case_id"])
    situation_text = f"{situation}\n\n用户原话：{full[:1200]}"
    try:
        plan, meta = await workflow.run_council(user_id, code, situation_text, mem_text, consult_id,
                                                workflow.valid_extra(user_id, c["extra_advisors"]))
    except Exception as e:  # noqa: BLE001
        log.exception("出锦囊失败：%s", e)
        with get_conn() as conn:
            conn.execute("UPDATE consult SET status = 'failed' WHERE id = ?", (consult_id,))
            _add_msg(conn, consult_id, "advisor", "error", "锦囊没生成出来，点「重新生成」再试一次。")
        return get_detail(user_id, consult_id)
    _save_plan(user_id, consult_id, plan, refs, meta["prompt_versions"])
    _spawn(_remember(user_id, consult_id))
    return get_detail(user_id, consult_id)


def _save_plan(user_id: str, consult_id: int, plan: dict, refs: list, prompt_versions: dict) -> int:
    with get_conn() as conn:
        ver = (conn.execute("SELECT MAX(version) FROM plan WHERE consult_id = ?", (consult_id,)).fetchone()[0] or 0) + 1
        pid = conn.execute("""INSERT INTO plan(consult_id, version, content, strategy_codes, memory_refs, prompt_versions,
                              created_at) VALUES (?,?,?,?,?,?,?)""",
                           (consult_id, ver, dumps(plan), dumps([s["code"] for s in plan["strategies"]]), dumps(refs),
                            dumps(prompt_versions), now_str())).lastrowid
        for i, a in enumerate(plan["actions"]):
            conn.execute("INSERT INTO plan_action(plan_id, text, due_hint, sort_order, remind_at) VALUES (?,?,?,?,?)",
                         (pid, a["text"], a["when"], i, hint_date(a["when"])))
        urgency = (loads(conn.execute("SELECT intent FROM consult WHERE id = ?", (consult_id,)).fetchone()[0], {}) or {}).get("urgency")
        conn.execute("UPDATE consult SET status = 'planned', follow_up_at = ?, "
                     "situation_summary = CASE WHEN ? != '' THEN ? ELSE situation_summary END WHERE id = ?",
                     (_after_days(FOLLOW_UP_DAYS.get(urgency, 3)), plan.get("summary", ""), plan.get("summary", ""), consult_id))
        _add_msg(conn, consult_id, "advisor", "plan", plan["headline"], {"version": ver}, pid)
    return pid


async def add_message(user_id: str, consult_id: int, text: str, kind: str = "ask") -> dict:
    """answer：回答追问（重新识别后分派）；ask：对锦囊继续问；review：回来复盘执行结果。"""
    if kind not in ("answer", "ask", "review", "skip"):
        raise BadRequest("消息类型不正确")
    with get_conn() as conn:
        c = _get(conn, user_id, consult_id)
        _check_size(conn, consult_id)
        if kind != "skip":
            _add_msg(conn, consult_id, "user", kind, text)
        history = _history(conn, consult_id)
        first = _user_text(conn, consult_id, ("ask",)).split("\n")[0]
    quota.add(user_id, "consult_msg")
    if c["status"] in ("clarifying", "asking", "failed") and not _has_plan(consult_id):
        await _route(user_id, consult_id, text if kind != "skip" else first, history, clarified=True,
                     skip_clarify=kind == "skip")
        return get_detail(user_id, consult_id)
    if c["status"] == "safety":
        reply = await workflow.run_safety(user_id, text, c["intent"].get("risk", "safety"), consult_id)
        with get_conn() as conn:
            _add_msg(conn, consult_id, "advisor", "safety", reply)
        return get_detail(user_id, consult_id)
    with get_conn() as conn:
        plan = _latest_plan(conn, consult_id)
    if not plan:
        return await make_plan(user_id, consult_id)
    if kind == "review":
        text = f"（复盘）我照着做了，结果是：{text}"
    mem_text, _ = memory.context(user_id, text, c["intent"].get("people"), c["case_id"])
    turn = len(history)
    try:
        out, meta = await workflow.run_followup(user_id, c["council_code"] or "general", c["situation_summary"],
                                                plan["content"], history, text, mem_text, consult_id, turn,
                                                workflow.valid_extra(user_id, c["extra_advisors"]))
    except Exception as e:  # noqa: BLE001
        log.exception("追问失败：%s", e)
        with get_conn() as conn:
            _add_msg(conn, consult_id, "advisor", "error", "智囊暂时没接上，请稍后再问一次。")
        return get_detail(user_id, consult_id)
    with get_conn() as conn:
        _add_msg(conn, consult_id, "advisor", "reply", out["reply"])
        conn.execute("UPDATE consult SET situation_summary = ? WHERE id = ?", (out["summary"], consult_id))
        if kind == "review":  # 复盘过了：行动都做完就不再提醒，否则一周后再问
            pending = conn.execute("SELECT COUNT(*) FROM plan_action WHERE plan_id = ? AND done = 0", (plan["id"],)).fetchone()[0]
            conn.execute("UPDATE consult SET follow_up_at = ? WHERE id = ?", (_after_days(7) if pending else None, consult_id))
    if out["plan"]:
        _save_plan(user_id, consult_id, out["plan"], plan["memory_refs"], meta["prompt_versions"])
    _spawn(_remember(user_id, consult_id, review=text if kind == "review" else ""))
    return get_detail(user_id, consult_id)


def _has_plan(consult_id: int) -> bool:
    with get_conn() as conn:
        return bool(conn.execute("SELECT 1 FROM plan WHERE consult_id = ? LIMIT 1", (consult_id,)).fetchone())


async def _remember(user_id: str, consult_id: int, review: str = "") -> None:
    """后台：从这次问计里提取长期记忆，并把问计挂到事件线上。"""
    if memory.is_paused(user_id):
        return
    try:
        with get_conn() as conn:
            c = _get(conn, user_id, consult_id)
            convo = _user_text(conn, consult_id)
        data = await workflow.run_memory_extract(user_id, convo[-3000:], memory.brief_for_extract(user_id), c["intent"],
                                                 (consult_id, len(convo)))
        if review and isinstance(data, dict):
            case = data.get("case") if isinstance(data.get("case"), dict) else {}
            case.setdefault("update", review.replace("（复盘）我照着做了，结果是：", "复盘：")[:100])
            data["case"] = case
        res = memory.apply_extraction(user_id, data, consult_id, c["case_id"], source=f"问计「{c['title']}」{now_str()[:10]}")
        if res.get("case_id") and res["case_id"] != c["case_id"]:
            with get_conn() as conn:
                conn.execute("UPDATE consult SET case_id = ? WHERE id = ?", (res["case_id"], consult_id))
        for sid in res.get("subjects") or []:  # 卡片太长就顺手整理一下
            if memory.needs_compact(sid):
                await memory.compact_subject(user_id, sid)
    except Exception as e:  # noqa: BLE001  记忆失败不影响问计
        log.warning("记忆提取失败 consult=%s：%s", consult_id, e)


def update_action(user_id: str, action_id: int, done: bool = None, result: str = None, remind_at: str = None) -> dict:
    """勾选完成 / 写结果 / 设提醒日期（remind_at 传空字符串 = 取消提醒）。"""
    if remind_at and not re.match(r"^\d{4}-\d{2}-\d{2}$", remind_at):
        raise BadRequest("提醒日期格式应为 YYYY-MM-DD")
    with get_conn() as conn:
        r = conn.execute("""SELECT a.*, c.id AS consult_id, c.case_id, c.title FROM plan_action a
                            JOIN plan p ON p.id = a.plan_id JOIN consult c ON c.id = p.consult_id
                            WHERE a.id = ? AND c.user_id = ?""", (action_id, user_id)).fetchone()
        if not r:
            raise NotFound("行动不存在")
        if done is not None:
            conn.execute("UPDATE plan_action SET done = ?, done_at = ? WHERE id = ?",
                         (1 if done else 0, now_str() if done else None, action_id))
        if result is not None:
            conn.execute("UPDATE plan_action SET result = ? WHERE id = ?", (result.strip()[:300], action_id))
        if remind_at is not None:
            conn.execute("UPDATE plan_action SET remind_at = ? WHERE id = ?", (remind_at or None, action_id))
        if done:  # 最新一版的行动全部完成 → 马上提醒回来复盘
            latest = conn.execute("SELECT MAX(id) FROM plan WHERE consult_id = ?", (r["consult_id"],)).fetchone()[0]
            left = conn.execute("SELECT COUNT(*) FROM plan_action WHERE plan_id = ? AND done = 0", (latest,)).fetchone()[0]
            if latest == r["plan_id"] and not left:
                conn.execute("UPDATE consult SET follow_up_at = ? WHERE id = ?", (now_str(), r["consult_id"]))
    if done and r["case_id"]:
        memory.record_event(user_id, r["case_id"], f"完成：{r['text']}" + (f"，结果：{result.strip()[:80]}" if result else ""),
                            source=f"问计「{r['title']}」{now_str()[:10]}", consult_id=r["consult_id"])
    return {"ok": True}


def delete_consult(user_id: str, consult_id: int) -> dict:
    """删除问计，同时删除由它产生的记忆条目；生成过的对练场景保留在“我的场景”。"""
    with get_conn() as conn:
        _get(conn, user_id, consult_id)
        if conn.execute("SELECT 1 FROM generation_job WHERE consult_id=? AND status IN ('queued','running')", (consult_id,)).fetchone():
            raise BadRequest("生成进行中，请完成后再删除")
        memory.delete_by_consult(conn, user_id, consult_id)
        conn.execute("UPDATE drill SET consult_id = NULL WHERE consult_id = ?", (consult_id,))
        conn.execute("DELETE FROM consult WHERE id = ?", (consult_id,))
    return {"ok": True}


# ---------------- 去演练 ----------------

def rehearse(user_id: str, consult_id: int) -> dict:
    """用最新锦囊生成对练场景（不调大模型）：对方按人物卡和锦囊扮演，推荐框架和误区一并带上。"""
    with get_conn() as conn:
        c = _get(conn, user_id, consult_id)
        p = conn.execute("SELECT * FROM plan WHERE consult_id = ? ORDER BY version DESC LIMIT 1", (consult_id,)).fetchone()
        if not p:
            raise BadRequest("还没有锦囊，先让智囊出一份吧")
        if p["drill_id"] and conn.execute("SELECT 1 FROM drill WHERE id = ? AND status = 'online'", (p["drill_id"],)).fetchone():
            did = p["drill_id"]
        else:
            plan = loads(p["content"], {})
            reh = plan.get("rehearsal") or {}
            people = c["intent"].get("people") or []
            traits = ""
            for name in people[:1]:
                person = memory.find_person(conn, user_id, name)
                if person:
                    facts = [r[0] for r in conn.execute(
                        "SELECT text FROM memory_item WHERE subject_id = ? ORDER BY id DESC LIMIT 4", (person["id"],))]
                    traits = f"（{person['name']}：{'；'.join(facts)}）" if facts else ""
            ai_role = (reh.get("ai_role") or c["intent"].get("counterpart") or "和你沟通的对方") + traits
            desc = f"{c['situation_summary'] or c['title']}\n\n锦囊要点：{plan.get('headline', '')}"
            sid = system_scenario_id(conn)
            did = conn.execute(
                """INSERT INTO drill(scenario_id, title, description, pressure_level, duration_min, mode, ai_role, user_role,
                   training_goal, opening_line, status, sort_order, owner_id, consult_id)
                   VALUES (?,?,?,?,?,'纯语音',?,?,?,?,'online',0,?,?)""",
                (sid, f"演练：{c['title']}"[:40], desc[:600], "中压", 4, ai_role[:200], (reh.get("user_role") or "你自己")[:40],
                 (reh.get("goal") or plan.get("goal", {}).get("best") or "按锦囊把关键话说出来")[:80],
                 (reh.get("opening_line") or "你找我有什么事？")[:120], user_id, consult_id)).lastrowid
            fws = [(ln["framework"], ln["text"][:120]) for ln in plan.get("lines", []) if ln.get("framework")]
            set_drill_guide(conn, did, list(dict.fromkeys(fws))[:3], plan.get("donts", [])[:4])
            conn.execute("UPDATE plan SET drill_id = ? WHERE id = ?", (did, p["id"]))
    from .sessions import get_drill
    return get_drill(did, user_id)


def plan_points_for_drill(conn, drill: dict) -> str:
    """给训练报告用：这个对练来自哪份锦囊、要点是什么。"""
    cid = drill.get("consult_id")
    if not cid:
        return ""
    r = conn.execute("SELECT content FROM plan WHERE consult_id = ? ORDER BY version DESC LIMIT 1", (cid,)).fetchone()
    if not r:
        return ""
    plan = loads(r[0], {})
    lines = "；".join(f"{ln.get('moment', '')}：{ln.get('text', '')}" for ln in plan.get("lines", [])[:4])
    risks = "；".join(f"若{x.get('if', '')}则{x.get('then', '')}" for x in plan.get("risks", [])[:3])
    return f"判断：{plan.get('headline', '')}。关键话术：{lines}。风险预案：{risks}"[:900]


def after_report(drill: dict, session: dict, report: dict) -> None:
    """锦囊来的对练出了报告：写进事件线。"""
    cid = drill.get("consult_id")
    if not cid:
        return
    with get_conn() as conn:
        r = conn.execute("SELECT user_id, case_id, title FROM consult WHERE id = ?", (cid,)).fetchone()
    if r and r["case_id"]:
        memory.record_event(r["user_id"], r["case_id"], f"演练了一次，得分 {report.get('total_score', 0)}："
                            f"{(report.get('summary') or '')[:40]}", source=f"训练 {now_str()[:10]}", consult_id=cid)


def plan_texts(user_id: str, limit: int = 60) -> list:
    """锦囊里的话术原文（示范朗读白名单用）。"""
    with get_conn() as conn:
        rows = conn.execute("""SELECT p.content FROM plan p JOIN consult c ON c.id = p.consult_id
                               WHERE c.user_id = ? ORDER BY p.id DESC LIMIT ?""", (user_id, limit)).fetchall()
    out = []
    for r in rows:
        for ln in loads(r[0], {}).get("lines", []):
            if ln.get("text"):
                out.append(ln["text"])
    return out



# ---------------- 跟进提醒 ----------------

def due_followups(user_id: str, limit: int = 5) -> list:
    """到期该跟进的问计：约定的跟进时间到了，或有行动到了提醒日期还没做。"""
    today = now().date().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.id, c.title, c.council_code, c.follow_up_at, p.id AS plan_id FROM consult c
               JOIN plan p ON p.id = (SELECT MAX(id) FROM plan WHERE consult_id = c.id)
               WHERE c.user_id = ? AND c.status = 'planned' AND (
                     (c.follow_up_at IS NOT NULL AND c.follow_up_at <= ?)
                  OR EXISTS (SELECT 1 FROM plan_action a WHERE a.plan_id = p.id AND a.done = 0
                             AND a.remind_at IS NOT NULL AND a.remind_at <= ?))
               ORDER BY COALESCE(c.follow_up_at, c.updated_at) LIMIT ?""",
            (user_id, now_str(), today, limit)).fetchall()
        out = []
        for r in rows:
            acts = [row_to_dict(a) for a in conn.execute(
                "SELECT id, text, remind_at, done FROM plan_action WHERE plan_id = ? ORDER BY sort_order", (r["plan_id"],))]
            pending = [a for a in acts if not a["done"]]
            due_acts = [{"id": a["id"], "text": a["text"], "remind_at": a["remind_at"]} for a in pending
                        if a["remind_at"] and a["remind_at"] <= today]
            if acts and not pending:
                reason = "行动都做完了，回来复盘一下结果，智囊帮你看下一步"
            elif due_acts:
                reason = f"「{due_acts[0]['text'][:24]}」该做了" + (f"，还有 {len(due_acts) - 1} 项也到期了" if len(due_acts) > 1 else "")
            else:
                reason = "约定的跟进时间到了，事情进展得怎么样？"
            out.append({"consult_id": r["id"], "title": r["title"], "reason": reason, "due_actions": due_acts,
                        "pending": len(pending), "council_name": workflow.get_council(r["council_code"])["name"]
                        if r["council_code"] else ""})
    return out


def snooze(user_id: str, consult_id: int, days: int = 2) -> dict:
    """稍后提醒：顺延问计的跟进时间，到期未做的行动也一起顺延。"""
    days = max(1, min(int(days or 2), 30))
    with get_conn() as conn:
        _get(conn, user_id, consult_id)
        conn.execute("UPDATE consult SET follow_up_at = ? WHERE id = ?", (_after_days(days), consult_id))
        new_day = (now().date() + timedelta(days=days)).isoformat()
        conn.execute("""UPDATE plan_action SET remind_at = ? WHERE done = 0 AND remind_at IS NOT NULL AND remind_at <= ?
                        AND plan_id IN (SELECT id FROM plan WHERE consult_id = ?)""",
                     (new_day, now().date().isoformat(), consult_id))
    return {"ok": True, "follow_up_at": _after_days(days)}


def stop_follow(user_id: str, consult_id: int) -> dict:
    """不用再提醒了（事情已经结束或不打算推进）。"""
    with get_conn() as conn:
        _get(conn, user_id, consult_id)
        conn.execute("UPDATE consult SET follow_up_at = NULL WHERE id = ?", (consult_id,))
        conn.execute("UPDATE plan_action SET remind_at = NULL WHERE done = 0 AND plan_id IN "
                     "(SELECT id FROM plan WHERE consult_id = ?)", (consult_id,))
    return {"ok": True}


# ---------------- 圆桌会议 ----------------

async def roundtable(user_id: str, consult_id: int, topic: str = "") -> dict:
    """几位谋士围绕锦囊（或用户指定的焦点）辩论，军师裁决；结果作为一条消息存下来。"""
    topic = (topic or "").strip()[:100]
    with get_conn() as conn:
        c = _get(conn, user_id, consult_id)
        if c["status"] == "safety":
            raise BadRequest("这个问题智囊不提供谋略建议")
        _check_size(conn, consult_id)
        plan = _latest_plan(conn, consult_id)
        if not plan:
            raise BadRequest("先让智囊出一份锦囊，再开圆桌会议")
        turn = conn.execute("SELECT COUNT(*) FROM consult_message WHERE consult_id = ?", (consult_id,)).fetchone()[0]
        _add_msg(conn, consult_id, "user", "roundtable_ask", topic or "开一场圆桌会议，听听各位谋士的不同意见")
    quota.add(user_id, "consult_msg")
    mem_text, _ = memory.context(user_id, (c["situation_summary"] or "") + topic, c["intent"].get("people"), c["case_id"])
    try:
        rt, meta = await workflow.run_roundtable(user_id, c["council_code"] or "general", c["situation_summary"] or c["title"],
                                                 plan["content"], topic, mem_text, consult_id,
                                                 workflow.valid_extra(user_id, c["extra_advisors"]), turn)
    except Exception as e:  # noqa: BLE001
        log.exception("圆桌会议失败：%s", e)
        with get_conn() as conn:
            _add_msg(conn, consult_id, "advisor", "error", "圆桌会议没开起来，请稍后再试。")
        return get_detail(user_id, consult_id)
    rt["prompt_versions"] = meta["prompt_versions"]
    with get_conn() as conn:
        _add_msg(conn, consult_id, "advisor", "roundtable", rt["verdict"]["text"], rt, plan["id"])
    return get_detail(user_id, consult_id)


# ---------------- 私人谋士列席 ----------------

def set_extra_advisors(user_id: str, consult_id: int, codes: list) -> dict:
    extra = workflow.valid_extra(user_id, codes)
    with get_conn() as conn:
        _get(conn, user_id, consult_id)
        conn.execute("UPDATE consult SET extra_advisors = ? WHERE id = ?", (dumps(extra), consult_id))
    return get_detail(user_id, consult_id)


# ---------------- 锦囊评价 ----------------

def rate_plan(user_id: str, plan_id: int, rating: int, reason: str = "") -> dict:
    if rating not in (1, -1, 0):
        raise BadRequest("评价只能是有用或没用")
    with get_conn() as conn:
        r = conn.execute("SELECT p.id FROM plan p JOIN consult c ON c.id = p.consult_id WHERE p.id = ? AND c.user_id = ?",
                         (plan_id, user_id)).fetchone()
        if not r:
            raise NotFound("锦囊不存在")
        conn.execute("UPDATE plan SET rating = ?, rating_reason = ?, rated_at = ? WHERE id = ?",
                     (rating or None, (reason or "").strip()[:200] if rating else "", now_str() if rating else None, plan_id))
    return {"ok": True}
