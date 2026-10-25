"""谋略库：列表 / 详情 / 按智囊团取子库 / 关联表达框架。"""
import re

from ..db import get_conn, loads, row_to_dict
from ..strategies_data import DOMAINS, SCHOOLS
from .sessions import NotFound

JSON_FIELDS = (("domains", []), ("how_to_do", []), ("framework_codes", []))
CATALOG_MIN, CATALOG_MAX = 40, 100


def _st(row) -> dict:
    s = row_to_dict(row)
    for k, d in JSON_FIELDS:
        if k in s:
            s[k] = loads(s[k], d)
    s["school_name"] = SCHOOLS.get(s["school"], (s["school"],))[0]
    s["caution"] = bool(s.get("caution"))
    return s


def schools() -> list:
    with get_conn() as conn:
        counts = {r[0]: r[1] for r in conn.execute("SELECT school, COUNT(*) FROM strategy WHERE enabled = 1 GROUP BY school")}
    out = [{"code": k, "name": v[0], "group": v[1], "intro": v[2], "count": counts.get(k, 0)}
           for k, v in SCHOOLS.items() if counts.get(k)]
    # 导入时新建的体系（库里有、代码里没有）
    out += [{"code": k, "name": k, "group": "自定义", "intro": "后台导入", "count": n}
            for k, n in counts.items() if k not in SCHOOLS]
    return out


def list_strategies(school: str = None, domain: str = None, q: str = None) -> dict:
    where, params = ["enabled = 1"], []
    if school:
        where.append("school = ?")
        params.append(school)
    if domain:
        where.append("domains LIKE ?")
        params.append(f'%"{domain}"%')
    if q:
        like = f"%{q.strip()}%"
        where.append("(name LIKE ? OR plain LIKE ? OR origin LIKE ? OR code LIKE ?)")
        params += [like] * 4
    with get_conn() as conn:
        items = [_st(r) for r in conn.execute(
            f"SELECT id, code, school, name, sub, plain, domains, caution FROM strategy WHERE {' AND '.join(where)} "
            "ORDER BY sort_order, id", params)]
    return {"schools": schools(), "domains": DOMAINS, "items": items, "total": len(items)}


def get_strategy(code: str) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM strategy WHERE code = ? OR CAST(id AS TEXT) = ?", (code, str(code))).fetchone()
        if not row:
            raise NotFound("谋略不存在")
        s = _st(row)
        fws = []
        for c in s["framework_codes"]:
            f = conn.execute("SELECT code, name, summary FROM framework WHERE code = ?", (c,)).fetchone()
            if f:
                fws.append(row_to_dict(f))
        s["frameworks"] = fws
        s["councils"] = [row_to_dict(r) for r in conn.execute(
            "SELECT code, name FROM council WHERE enabled = 1 AND schools LIKE ? ORDER BY sort_order",
            (f'%"{s["school"]}"%',))]
    return s


def by_codes(codes: list) -> list:
    if not codes:
        return []
    with get_conn() as conn:
        rows = conn.execute(f"SELECT * FROM strategy WHERE code IN ({','.join('?' * len(codes))})", codes).fetchall()
    found = {r["code"]: _st(r) for r in rows}
    return [found[c] for c in codes if c in found]


def related_to_framework(framework_code: str) -> list:
    with get_conn() as conn:
        return [_st(r) for r in conn.execute(
            "SELECT id, code, school, name, sub, plain, caution FROM strategy WHERE enabled = 1 AND framework_codes LIKE ? "
            "ORDER BY sort_order LIMIT 12", (f'%"{framework_code}"%',))]


def _score(s: dict, text: str) -> int:
    hay = s["name"] + s["plain"]
    return sum(1 for w in set(re.findall(r"[一-龥]{2}", text)) if w in hay)


def catalog_for(council: dict, text: str = "") -> list:
    """按智囊团配置取 40–100 条候选谋略：体系 + 领域筛选，再按和描述的相关度排序；不够就从全库补。"""
    schools_ = council.get("schools") or []
    domains = council.get("domains") or []
    with get_conn() as conn:
        rows = [_st(r) for r in conn.execute("SELECT * FROM strategy WHERE enabled = 1 ORDER BY sort_order, id")]
    primary = [s for s in rows if (not schools_ or s["school"] in schools_)]
    if domains:
        primary.sort(key=lambda s: (not any(d in s["domains"] for d in domains), -_score(s, text)))
    else:
        primary.sort(key=lambda s: -_score(s, text))
    picked = primary[:CATALOG_MAX]
    if len(picked) < CATALOG_MIN:
        extra = sorted((s for s in rows if s not in picked), key=lambda s: -_score(s, text))
        picked += extra[:CATALOG_MIN - len(picked)]
    return picked


def catalog_text(items: list) -> str:
    lines = []
    for s in items:
        mark = "【慎用：只用于识别和防范】" if s["caution"] else ""
        lines.append(f"{s['code']}｜{s['school_name']}·{s['name']}{mark}｜{s['plain'][:60]}")
    return "\n".join(lines)


def frameworks_for(strategy_items: list, extra_codes: list = (), limit: int = 14) -> list:
    """候选表达框架：谋略关联的框架优先，再补通用的几个。"""
    codes = []
    for s in strategy_items[:30]:
        for c in s["framework_codes"]:
            if c not in codes:
                codes.append(c)
    for c in list(extra_codes) + ["prep", "pyramid", "key_dialog", "nvc", "answer3", "trade", "emotion_down", "goal_guide"]:
        if c not in codes:
            codes.append(c)
    with get_conn() as conn:
        out = []
        for c in codes:
            f = conn.execute("SELECT code, name, steps FROM framework WHERE code = ?", (c,)).fetchone()
            if f:
                steps = "-".join(x.get("name", "") for x in loads(f["steps"], []))
                out.append({"code": f["code"], "name": f["name"], "steps": steps})
            if len(out) >= limit:
                break
    return out


def frameworks_text(items: list) -> str:
    return "\n".join(f"{f['code']}｜{f['name']}｜{f['steps']}" for f in items)
