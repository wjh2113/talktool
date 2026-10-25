"""问计效果统计（管理员看）：哪个智囊团、哪版提示词更受欢迎。

只统计数量和比例，不展示问计内容；“没用”的反馈原文单独列出，便于改提示词。
指标：
  问计数、出锦囊数、评价数、有用率（有用 / 已评价）、去演练率、复盘率、行动完成率
提示词版本：按每份锦囊记录的 prompt_versions（council.<code> / followup）分组统计评价。
"""
from datetime import timedelta

from ..db import TIME_FMT, get_conn, loads, now
from . import workflow


def _rate(a: int, b: int):
    return round(a / b, 3) if b else None


def overview(days: int = 30) -> dict:
    days = max(1, min(int(days or 30), 365))
    since = (now() - timedelta(days=days)).strftime(TIME_FMT)
    names = {c["code"]: c["name"] for c in workflow.councils(enabled_only=False)}
    by_council, by_prompt = {}, {}

    def bucket(code):
        return by_council.setdefault(code or "general", {
            "code": code or "general", "name": names.get(code or "general", code), "consults": 0, "planned": 0,
            "plans": 0, "rated": 0, "up": 0, "down": 0, "rehearsed": 0, "reviewed": 0, "roundtables": 0,
            "actions": 0, "actions_done": 0})

    with get_conn() as conn:
        for r in conn.execute(
                """SELECT c.id, c.council_code, c.status,
                          (SELECT COUNT(*) FROM consult_message m WHERE m.consult_id = c.id AND m.kind = 'review') AS reviews,
                          (SELECT COUNT(*) FROM consult_message m WHERE m.consult_id = c.id AND m.kind = 'roundtable') AS rts,
                          (SELECT COUNT(*) FROM plan p WHERE p.consult_id = c.id AND p.drill_id IS NOT NULL) AS drills,
                          (SELECT MAX(id) FROM plan p WHERE p.consult_id = c.id) AS last_plan
                   FROM consult c WHERE c.created_at >= ?""", (since,)):
            b = bucket(r["council_code"])
            b["consults"] += 1
            if r["last_plan"]:
                b["planned"] += 1
                b["reviewed"] += 1 if r["reviews"] else 0
                b["rehearsed"] += 1 if r["drills"] else 0
                b["roundtables"] += 1 if r["rts"] else 0
                a = conn.execute("SELECT COUNT(*), COALESCE(SUM(done), 0) FROM plan_action WHERE plan_id = ?",
                                 (r["last_plan"],)).fetchone()
                b["actions"] += a[0]
                b["actions_done"] += a[1]
        feedback = []
        for p in conn.execute(
                """SELECT p.rating, p.rating_reason, p.prompt_versions, p.rated_at, c.council_code FROM plan p
                   JOIN consult c ON c.id = p.consult_id WHERE p.created_at >= ?""", (since,)):
            b = bucket(p["council_code"])
            b["plans"] += 1
            versions = loads(p["prompt_versions"], {}) or {}
            for key, ver in versions.items():
                k = by_prompt.setdefault((key, ver), {"key": key, "version": ver, "plans": 0, "rated": 0, "up": 0, "down": 0})
                k["plans"] += 1
            if p["rating"] in (1, -1):
                b["rated"] += 1
                b["up" if p["rating"] == 1 else "down"] += 1
                for key, ver in versions.items():
                    k = by_prompt[(key, ver)]
                    k["rated"] += 1
                    k["up" if p["rating"] == 1 else "down"] += 1
                if p["rating"] == -1 and p["rating_reason"]:
                    feedback.append({"council": names.get(p["council_code"], p["council_code"]), "reason": p["rating_reason"],
                                     "versions": versions, "at": p["rated_at"]})

    councils = []
    for b in by_council.values():
        b.update({"up_rate": _rate(b["up"], b["rated"]), "rehearse_rate": _rate(b["rehearsed"], b["planned"]),
                  "review_rate": _rate(b["reviewed"], b["planned"]), "action_rate": _rate(b["actions_done"], b["actions"]),
                  "plan_rate": _rate(b["planned"], b["consults"])})
        councils.append(b)
    councils.sort(key=lambda x: -x["consults"])
    prompts = []
    for k in by_prompt.values():
        k["up_rate"] = _rate(k["up"], k["rated"])
        k["label"] = "默认版" if not k["version"] else f"v{k['version']}"
        prompts.append(k)
    prompts.sort(key=lambda x: (x["key"], -(x["version"] or 0)))
    total = {f: sum(b[f] for b in councils) for f in ("consults", "planned", "plans", "rated", "up", "down", "rehearsed",
                                                       "reviewed", "actions", "actions_done", "roundtables")}
    total.update({"up_rate": _rate(total["up"], total["rated"]), "rehearse_rate": _rate(total["rehearsed"], total["planned"]),
                  "review_rate": _rate(total["reviewed"], total["planned"]),
                  "action_rate": _rate(total["actions_done"], total["actions"])})
    feedback.sort(key=lambda x: x["at"] or "", reverse=True)
    return {"days": days, "total": total, "councils": councils, "prompts": prompts, "feedback": feedback[:20]}


def prompt_version_stats(key: str) -> dict:
    """某个提示词各版本的评价（提示词编辑页显示）：{version: {plans, rated, up, up_rate}}。"""
    out = {}
    with get_conn() as conn:
        for p in conn.execute("SELECT rating, prompt_versions FROM plan WHERE prompt_versions LIKE ?", (f'%"{key}"%',)):
            ver = (loads(p["prompt_versions"], {}) or {}).get(key)
            if ver is None:
                continue
            s = out.setdefault(str(ver), {"plans": 0, "rated": 0, "up": 0})
            s["plans"] += 1
            if p["rating"] in (1, -1):
                s["rated"] += 1
                s["up"] += 1 if p["rating"] == 1 else 0
    for s in out.values():
        s["up_rate"] = _rate(s["up"], s["rated"])
    return out
