"""练习本（收藏）与自定义场景。"""
import logging

from .. import config
from ..db import get_conn, now_str, row_to_dict, set_drill_guide, system_scenario_id
from . import gateway, quota
from .prompts import build_custom_drill_messages
from .sessions import BadRequest, NotFound, _load_drill, _public_drill

log = logging.getLogger("talktool")

NOTE_KINDS = ("phrase", "tip", "script")


# ---------------- 练习本 ----------------

def list_notes(user_id: str, kind: str = None) -> list:
    where, params = ["n.user_id = ?"], [user_id]
    if kind in NOTE_KINDS:
        where.append("n.kind = ?")
        params.append(kind)
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT n.*, d.title AS drill_title FROM note n LEFT JOIN drill d ON d.id = n.drill_id
                WHERE {' AND '.join(where)} ORDER BY n.created_at DESC, n.id DESC LIMIT 500""", params).fetchall()
    return [row_to_dict(r) for r in rows]


def add_note(user_id: str, kind: str, text: str, source_text: str = "", drill_id: int = None,
             session_id: int = None) -> dict:
    text = (text or "").strip()
    if kind not in NOTE_KINDS:
        raise BadRequest("收藏类型不正确")
    if not text or len(text) > 2000:
        raise BadRequest("收藏内容为空或过长")
    with get_conn() as conn:
        if session_id:
            ok = conn.execute("SELECT drill_id FROM session WHERE id = ? AND user_id = ?",
                              (session_id, user_id)).fetchone()
            if not ok:
                raise NotFound("训练记录不存在")
            drill_id = drill_id or ok["drill_id"]
        if drill_id:
            _load_drill(conn, drill_id, user_id)
        dup = conn.execute("SELECT * FROM note WHERE user_id = ? AND kind = ? AND text = ?",
                           (user_id, kind, text)).fetchone()
        if dup:
            return row_to_dict(dup)
        nid = conn.execute(
            """INSERT INTO note(user_id, kind, text, source_text, drill_id, session_id, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, kind, text, (source_text or "")[:1000], drill_id, session_id, now_str())).lastrowid
        return row_to_dict(conn.execute("SELECT * FROM note WHERE id = ?", (nid,)).fetchone())


def delete_note(user_id: str, note_id: int) -> dict:
    with get_conn() as conn:
        n = conn.execute("DELETE FROM note WHERE id = ? AND user_id = ?", (note_id, user_id)).rowcount
    if not n:
        raise NotFound("收藏不存在")
    return {"ok": True}


# ---------------- 自定义场景 ----------------

PRESSURES = ("低压", "中压", "高压")


def _clip(v, n):
    return str(v or "").strip()[:n]


def _mock_custom(description: str, pressure: str) -> dict:
    short = description.strip().replace("\n", " ")
    return {
        "title": (short[:18] + "…") if len(short) > 18 else short,
        "description": f"你正在面对这样的情况：{short}。对方已经在你面前，开口说了第一句话。"
                       "请你清楚表达自己的立场和诉求，倾听对方的顾虑，争取一个双方都能接受的结果。",
        "ai_role": "与你沟通的对方，有自己的立场和顾虑，会根据你的表现调整态度",
        "user_role": "你自己",
        "training_goal": "清晰表达诉求、回应对方顾虑、推动达成共识",
        "opening_line": "你找我有什么事？我时间不多，直说吧。",
        "duration_min": 3,
        "frameworks": [{"code": "nvc", "example": "（Mock）先讲事实，再说感受和需要，最后提一个具体请求。"},
                       {"code": "trade", "example": "（Mock）让步可以，但要换一个条件。"}],
        "pitfalls": ["一上来就情绪化", "只讲自己的诉求", "没有具体的请求"],
    }


async def create_custom_drill(user_id: str, description: str, pressure: str = "中压") -> dict:
    description = (description or "").strip()
    if len(description) < 6:
        raise BadRequest("请多描述一点情况（至少 6 个字）")
    if len(description) > 600:
        raise BadRequest("描述太长了，600 字以内即可")
    pressure = pressure if pressure in PRESSURES else "中压"
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM drill WHERE owner_id = ? AND status = 'online'",
                             (user_id,)).fetchone()[0]
    if count >= config.CUSTOM_DRILL_LIMIT:
        raise BadRequest(f"自定义场景最多保留 {config.CUSTOM_DRILL_LIMIT} 个，请先删除一些")
    quota.hit(user_id, "custom", config.DAILY_CUSTOM_LIMIT, "今天生成自定义场景的次数已用完，明天再来吧")

    if config.MOCK:
        g = _mock_custom(description, pressure)
    else:
        with get_conn() as conn:
            menu = "、".join(f"{r[0]}:{r[1]}" for r in conn.execute(
                "SELECT code, name FROM framework WHERE category != '自媒体创作' ORDER BY sort_order"))
        text = await gateway.chat(build_custom_drill_messages(description, pressure, menu),
                                  capability=config.CUSTOM_CAPABILITY, temperature=0.7, max_tokens=900,
                                  user_id=user_id, max_cost=config.MAX_COST_OTHER,
                                  idempotency_key=gateway.idem_key("custom", user_id, description, pressure))
        g = gateway.extract_json(text)
        if g.get("error"):
            raise BadRequest(f"这个情境不适合生成训练：{_clip(g['error'], 60)}")
    fields = {
        "title": _clip(g.get("title"), 40) or _clip(description, 20),
        "description": _clip(g.get("description"), 600),
        "ai_role": _clip(g.get("ai_role"), 80),
        "user_role": _clip(g.get("user_role"), 40) or "你自己",
        "training_goal": _clip(g.get("training_goal"), 80),
        "opening_line": _clip(g.get("opening_line"), 120),
    }
    if not fields["description"] or not fields["ai_role"]:
        raise BadRequest("场景生成失败，请换个说法再试")
    try:
        duration = max(2, min(8, int(g.get("duration_min") or 3)))
    except (TypeError, ValueError):
        duration = 3
    with get_conn() as conn:
        sid = system_scenario_id(conn)
        did = conn.execute(
            """INSERT INTO drill(scenario_id, title, description, pressure_level, duration_min, mode, ai_role,
               user_role, training_goal, opening_line, status, sort_order, owner_id)
               VALUES (?,?,?,?,?,'纯语音',?,?,?,?,'online',0,?)""",
            (sid, fields["title"], fields["description"], pressure, duration, fields["ai_role"],
             fields["user_role"], fields["training_goal"], fields["opening_line"], user_id)).lastrowid
        fws = [(x.get("code"), _clip(x.get("example"), 120)) for x in (g.get("frameworks") or [])[:3]
               if isinstance(x, dict)]
        pits = [_clip(p, 40) for p in (g.get("pitfalls") or [])[:4] if p]
        set_drill_guide(conn, did, fws, pits)
    from .sessions import get_drill
    out = get_drill(did, user_id)
    out["source_description"] = description
    return out


def list_custom_drills(user_id: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT d.id, d.title, d.description, d.pressure_level, d.duration_min, d.training_goal,
                      (SELECT COUNT(*) FROM session s WHERE s.drill_id = d.id) AS times,
                      (SELECT MAX(r.total_score) FROM session s JOIN report r ON r.session_id = s.id
                        WHERE s.drill_id = d.id) AS best
               FROM drill d WHERE d.owner_id = ? AND d.status = 'online' ORDER BY d.id DESC""",
            (user_id,)).fetchall()
    return [row_to_dict(r) for r in rows]


def delete_custom_drill(user_id: str, drill_id: int) -> dict:
    """软删除：训练记录里还能看到，但不能再开始新训练。"""
    with get_conn() as conn:
        n = conn.execute("UPDATE drill SET status = 'offline' WHERE id = ? AND owner_id = ?",
                         (drill_id, user_id)).rowcount
    if not n:
        raise NotFound("场景不存在")
    return {"ok": True}
