"""管理后台：提示词试运行、智囊团配置。"""
import re

from ..db import dumps, get_conn
from ..strategies_data import DOMAINS, SCHOOLS
from . import memory, prompt_store, workflow
from .sessions import BadRequest, NotFound

CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,20}$")


async def test_prompt(key: str, message: str, body: dict = None, admin_uid: str = "admin") -> dict:
    """用草稿（或编辑框里还没保存的内容）跑一遍，只看结果，不写任何问计和记忆。"""
    message = (message or "").strip()
    if len(message) < 4:
        raise BadRequest("请输入一个测试用的问题")
    override = prompt_store.draft_override(key, body)
    mem_text, _ = memory.context(admin_uid, message)
    with prompt_store.use_override(override):
        intent, _ = await workflow.run_intent(admin_uid, message, "", mem_text, 0)
        out = {"intent": intent, "route": workflow.route(intent, clarified=False)}
        if key == "clarify":
            out["output"] = await workflow.run_clarify(admin_uid, message, intent, mem_text, 0)
        elif key == "safety":
            out["output"] = await workflow.run_safety(admin_uid, message, intent["risk"] if intent["risk"] != "none" else "safety", 0)
        elif key.startswith("council."):
            plan, _ = await workflow.run_council(admin_uid, key.split(".", 1)[1], message, mem_text, 0)
            out["output"] = plan
        elif key == "followup":
            plan, _ = await workflow.run_council(admin_uid, intent["council"], message, mem_text, 0)
            res, _ = await workflow.run_followup(admin_uid, intent["council"], intent["summary"], plan, "",
                                                 "如果对方当场拒绝，我该怎么办？", mem_text, 0, 0)
            out["output"] = res
        elif key == "roundtable":
            plan, _ = await workflow.run_council(admin_uid, intent["council"], message, mem_text, 0)
            out["output"], _ = await workflow.run_roundtable(admin_uid, intent["council"], intent["summary"], plan,
                                                             "", mem_text, 0)
        elif key == "memory_compact":
            items = [x.strip() for x in re.split(r"[\n；;]+", message) if x.strip()]
            out["output"] = await workflow.run_memory_compact(admin_uid, "person", "测试人物", items, 6, 0)
        elif key == "memory_extract":
            out["output"] = await workflow.run_memory_extract(admin_uid, message, "（暂无）", intent, (0, message))
        else:
            out["output"] = intent
    return out


def list_councils() -> list:
    status = {p["key"]: p for p in prompt_store.list_prompts()}
    out = []
    for c in workflow.councils(enabled_only=False):
        p = status.get(f"council.{c['code']}", {})
        c["prompt_version"] = p.get("active_version", 0)
        c["prompt_has_draft"] = p.get("has_draft", False)
        out.append(c)
    return out


def options() -> dict:
    with get_conn() as conn:
        advisors = [dict(code=r["code"], name=r["name"], style=r["style"]) for r in
                    conn.execute("SELECT code, name, style FROM advisor WHERE owner_id IS NULL ORDER BY sort_order, id")]
    from .strategies import schools
    custom = [{"code": x["code"], "name": x["name"]} for x in schools() if x["code"] not in SCHOOLS]
    return {"schools": [{"code": k, "name": v[0]} for k, v in SCHOOLS.items()] + custom, "domains": DOMAINS,
            "advisors": advisors}


def _clean_council(body: dict) -> dict:
    opts = options()
    advisors = [a for a in (body.get("advisors") or []) if a in {x["code"] for x in opts["advisors"]}]
    if not advisors:
        raise BadRequest("至少选一位谋士")
    name = (body.get("name") or "").strip()[:20]
    if not name:
        raise BadRequest("名称不能为空")
    return {
        "name": name, "icon": (body.get("icon") or name[:1])[:2],
        "description": (body.get("description") or "").strip()[:120],
        "advisors": advisors[:4],
        "schools": [s for s in (body.get("schools") or []) if s in {x["code"] for x in opts["schools"]}],
        "domains": [d for d in (body.get("domains") or []) if d in DOMAINS],
        "requirement": (body.get("requirement") or "").strip()[:300],
        "examples": [str(e).strip()[:40] for e in (body.get("examples") or []) if str(e).strip()][:5],
        "enabled": 0 if body.get("enabled") is False else 1,
    }


def update_council(code: str, body: dict) -> dict:
    v = _clean_council(body)
    if code == "general" and not v["enabled"]:
        raise BadRequest("综合团是兜底团，不能停用")
    with get_conn() as conn:
        n = conn.execute("""UPDATE council SET name=?, icon=?, description=?, advisors=?, schools=?, domains=?, requirement=?,
                            examples=?, enabled=?, customized=1 WHERE code=?""",
                         (v["name"], v["icon"], v["description"], dumps(v["advisors"]), dumps(v["schools"]),
                          dumps(v["domains"]), v["requirement"], dumps(v["examples"]), v["enabled"], code)).rowcount
    if not n:
        raise NotFound("智囊团不存在")
    return {"ok": True}


def create_council(body: dict) -> dict:
    code = (body.get("code") or "").strip()
    if not CODE_RE.match(code):
        raise BadRequest("代码只能用小写字母、数字和下划线，字母开头，2–21 位")
    v = _clean_council(body)
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM council WHERE code = ?", (code,)).fetchone():
            raise BadRequest("这个代码已经存在")
        order = (conn.execute("SELECT MAX(sort_order) FROM council WHERE code != 'general'").fetchone()[0] or 0) + 1
        conn.execute("UPDATE council SET sort_order = sort_order + 1 WHERE code = 'general'")
        conn.execute("""INSERT INTO council(code, name, icon, description, advisors, schools, domains, requirement, examples,
                        enabled, customized, sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)""",
                     (code, v["name"], v["icon"], v["description"], dumps(v["advisors"]), dumps(v["schools"]),
                      dumps(v["domains"]), v["requirement"], dumps(v["examples"]), v["enabled"], order))
    return {"ok": True, "code": code, "prompt_key": f"council.{code}"}
