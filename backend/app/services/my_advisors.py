"""私人谋士：用户自己设定的顾问（人设 + 擅长的谋略体系），可以请进任何一次问计列席、参加圆桌会议。

- 每人最多 MAX_PER_USER 位；code 形如 my_xxxxxx，存在 advisor 表里（owner_id = 用户）
- 只有本人能看到和使用；管理员配置智囊团时看不到私人谋士
"""
import re
import secrets

from ..db import dumps, get_conn, loads, row_to_dict
from ..strategies_data import SCHOOLS
from .sessions import BadRequest, NotFound

MAX_PER_USER = 6
STYLES = ("稳健", "进取", "温和", "犀利", "务实", "长远")


def _out(r) -> dict:
    d = row_to_dict(r)
    d["schools"] = loads(d["schools"], [])
    d["school_names"] = [SCHOOLS[s][0] for s in d["schools"] if s in SCHOOLS]
    d.pop("owner_id", None)
    d.pop("customized", None)
    return d


def list_mine(user_id: str) -> list:
    with get_conn() as conn:
        return [_out(r) for r in conn.execute(
            "SELECT * FROM advisor WHERE owner_id = ? ORDER BY sort_order, id", (user_id,))]


def _clean(body: dict) -> dict:
    name = re.sub(r"\s+", "", body.get("name") or "")[:10]
    if not name:
        raise BadRequest("给谋士起个名字")
    persona = re.sub(r"\s+", " ", body.get("persona") or "").strip()[:300]
    if len(persona) < 6:
        raise BadRequest("写几句这位谋士的人设：他是谁、看问题的角度、说话风格")
    return {
        "name": name,
        "avatar": (body.get("avatar") or name[:1]).strip()[:2] or name[:1],
        "persona": persona,
        "style": (body.get("style") or "").strip()[:8],
        "schools": [s for s in (body.get("schools") or []) if s in SCHOOLS][:4],
    }


def create(user_id: str, body: dict) -> dict:
    v = _clean(body)
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM advisor WHERE owner_id = ?", (user_id,)).fetchone()[0]
        if n >= MAX_PER_USER:
            raise BadRequest(f"最多设 {MAX_PER_USER} 位私人谋士")
        code = "my_" + secrets.token_hex(3)
        while conn.execute("SELECT 1 FROM advisor WHERE code = ?", (code,)).fetchone():
            code = "my_" + secrets.token_hex(3)
        conn.execute("""INSERT INTO advisor(code, name, avatar, schools, persona, style, owner_id, customized, sort_order)
                        VALUES (?,?,?,?,?,?,?,1,?)""",
                     (code, v["name"], v["avatar"], dumps(v["schools"]), v["persona"], v["style"], user_id, 1000 + n))
        return _out(conn.execute("SELECT * FROM advisor WHERE code = ?", (code,)).fetchone())


def update(user_id: str, code: str, body: dict) -> dict:
    v = _clean(body)
    with get_conn() as conn:
        n = conn.execute("UPDATE advisor SET name=?, avatar=?, persona=?, style=?, schools=? WHERE code=? AND owner_id=?",
                         (v["name"], v["avatar"], v["persona"], v["style"], dumps(v["schools"]), code, user_id)).rowcount
        if not n:
            raise NotFound("谋士不存在")
        return _out(conn.execute("SELECT * FROM advisor WHERE code = ?", (code,)).fetchone())


def delete(user_id: str, code: str) -> dict:
    """删除后，历史锦囊里他的发言保留文字；正在列席的问计自动移除他。"""
    with get_conn() as conn:
        n = conn.execute("DELETE FROM advisor WHERE code = ? AND owner_id = ?", (code, user_id)).rowcount
        if not n:
            raise NotFound("谋士不存在")
        for r in conn.execute("SELECT id, extra_advisors FROM consult WHERE user_id = ? AND extra_advisors LIKE ?",
                              (user_id, f'%"{code}"%')).fetchall():
            conn.execute("UPDATE consult SET extra_advisors = ? WHERE id = ?",
                         (dumps([x for x in loads(r["extra_advisors"], []) if x != code]), r["id"]))
    return {"ok": True}


TEMPLATES = [
    {"name": "老周", "avatar": "周", "style": "务实", "schools": ["maoxuan", "zhanguoce"],
     "persona": "在国企干了二十多年的老处长，见过各种人事斗争。看问题先看人和关系，再看事；说话直白，爱用“我当年……”举例。"},
    {"name": "Linda", "avatar": "L", "style": "犀利", "schools": ["nego", "management"],
     "persona": "外企 HRD 出身，擅长谈薪、绩效和裁员沟通。只看利益和规则，提醒你留证据、走流程，讨厌情绪化表达。"},
    {"name": "妈妈", "avatar": "妈", "style": "温和", "schools": ["rujia", "xiushen"],
     "persona": "最了解你的人。总是先关心你累不累、值不值得，再帮你想办法；看重家庭和长远，不赞成为一时之气撕破脸。"},
]
