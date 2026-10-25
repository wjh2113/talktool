"""长期记忆：我的档案 / 人物卡 / 事件线 / 训练画像。

- 读：问计时按提到的人名和关键词取相关的几张卡，拼成约 800 token 以内的文字块
- 写：每轮问计后台跑 memory_extract，只记用户亲口说的事实；训练画像从报告直接统计，不调大模型
- 管：用户可以查看、修改、删除、暂停、清空；管理员看不到内容
"""
import logging
import re
from difflib import SequenceMatcher

from ..db import dumps, get_conn, loads, now_str, row_to_dict
from .sessions import NotFound

log = logging.getLogger("talktool.memory")

MAX_ITEMS_PER_SUBJECT = 20
PROFILE_LIMIT = 12
SENSITIVE = re.compile(
    r"(身份证|银行卡|卡号|密码|账号|病|症|抑郁|焦虑症|吃药|住院|怀孕|流产|宗教|信仰|党员|政治|存款|负债|欠款|贷款|工资条|月薪|年薪|"
    r"收入\d|性生活|出轨|吸毒|犯罪|坐牢|自杀|自残)")


def _similar(a: str, b: str) -> bool:
    a, b = a.strip(), b.strip()
    return bool(a and b) and (a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.8)


def _clean(text) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()[:120]
    return "" if (not t or SENSITIVE.search(t)) else t


# ---------------- 开关 ----------------

def is_paused(user_id: str) -> bool:
    with get_conn() as conn:
        r = conn.execute("SELECT paused FROM memory_setting WHERE user_id = ?", (user_id,)).fetchone()
    return bool(r and r[0])


def set_paused(user_id: str, paused: bool) -> dict:
    with get_conn() as conn:
        conn.execute("""INSERT INTO memory_setting(user_id, paused, updated_at) VALUES (?,?,?)
                        ON CONFLICT(user_id) DO UPDATE SET paused = excluded.paused, updated_at = excluded.updated_at""",
                     (user_id, 1 if paused else 0, now_str()))
    return {"paused": bool(paused)}


# ---------------- 读 ----------------

def _subjects(conn, user_id: str, kind: str) -> list:
    rows = conn.execute("SELECT * FROM memory_subject WHERE user_id = ? AND kind = ? ORDER BY last_seen DESC",
                        (user_id, kind)).fetchall()
    out = []
    for r in rows:
        d = row_to_dict(r)
        d["aliases"] = loads(d["aliases"], [])
        out.append(d)
    return out


def _items(conn, user_id: str, subject_id: int = None, type_: str = None, limit: int = 6) -> list:
    if subject_id:
        rows = conn.execute("SELECT * FROM memory_item WHERE user_id = ? AND subject_id = ? ORDER BY pinned DESC, id DESC LIMIT ?",
                            (user_id, subject_id, limit))
    else:
        rows = conn.execute("SELECT * FROM memory_item WHERE user_id = ? AND type = ? ORDER BY pinned DESC, id DESC LIMIT ?",
                            (user_id, type_, limit))
    return [row_to_dict(r) for r in rows]


def find_person(conn, user_id: str, name: str):
    name = (name or "").strip()
    if not name:
        return None
    for p in _subjects(conn, user_id, "person"):
        if name == p["name"] or name in p["aliases"]:
            return p
    return None


def training_profile(conn, user_id: str, before_id: int = None) -> dict:
    """训练画像：直接从报告统计（最近 20 场）。before_id：只统计这场之前的（报告里做长期对比用）。"""
    rows = conn.execute(
        """SELECT r.scores, s.metrics FROM report r JOIN session s ON s.id = r.session_id
           WHERE s.user_id = ? AND s.status = 'completed' AND (? IS NULL OR s.id < ?)
           ORDER BY s.id DESC LIMIT 20""", (user_id, before_id, before_id)).fetchall()
    if not rows:
        return {}
    dims, fillers, n = {}, {}, len(rows)
    for r in rows:
        for k, v in loads(r["scores"], {}).items():
            dims.setdefault(k, []).append(v)
        for f in (loads(r["metrics"], {}) or {}).get("filler_top") or []:
            if isinstance(f, dict):
                fillers[f.get("word")] = fillers.get(f.get("word"), 0) + (f.get("count") or 0)
    avg = {k: round(sum(v) / len(v), 1) for k, v in dims.items() if v}
    weakest = min(avg, key=avg.get) if avg else ""
    top = sorted(((k, v) for k, v in fillers.items() if k), key=lambda kv: -kv[1])[:3]
    return {"sessions": n, "avg": avg, "weakest": weakest,
            "fillers": [{"word": k, "per_session": round(v / n, 1)} for k, v in top]}


def training_line(tp: dict) -> str:
    if not tp:
        return ""
    parts = [f"最近 {tp['sessions']} 场训练"]
    if tp.get("avg"):
        parts.append("平均分 " + "、".join(f"{k}{v}" for k, v in tp["avg"].items()))
    if tp.get("weakest"):
        parts.append(f"最弱的是{tp['weakest']}")
    if tp.get("fillers"):
        parts.append("口头禅 " + "、".join(f"「{f['word']}」每场约 {f['per_session']} 次" for f in tp["fillers"]))
    return "；".join(parts)


def context(user_id: str, text: str = "", people: list = None, case_id: int = None) -> tuple:
    """返回 (给提示词的记忆文字块, 引用列表)。暂停时返回空。"""
    if is_paused(user_id):
        return "（用户暂停了记忆）", []
    text = text or ""
    names = [p for p in (people or []) if p]
    lines, refs = [], []
    with get_conn() as conn:
        prof = _items(conn, user_id, type_="profile", limit=PROFILE_LIMIT)
        if prof:
            lines.append("我的档案：" + "；".join(i["text"] for i in prof))
            refs.append({"kind": "profile", "label": "我的档案"})
        hit = []
        for p in _subjects(conn, user_id, "person"):
            keys = [p["name"]] + p["aliases"]
            if any(k and (k in text or k in names) for k in keys):
                hit.append(p)
        for p in hit[:3]:
            facts = _items(conn, user_id, subject_id=p["id"])
            desc = f"（{p['summary']}）" if p["summary"] else ""
            lines.append(f"人物卡·{p['name']}{desc}：" + ("；".join(f["text"] for f in facts) or "暂无细节"))
            refs.append({"kind": "person", "id": p["id"], "label": f"{p['name']}的人物卡"})
        cases = [c for c in _subjects(conn, user_id, "case") if c["status"] == "open"]
        picked = [c for c in cases if c["id"] == case_id]
        picked += [c for c in cases if c not in picked and any(ch in text for ch in re.findall(r"[一-龥]{2}", c["name"]))][:2]
        for c in picked[:2]:
            ev = _items(conn, user_id, subject_id=c["id"], limit=5)
            lines.append(f"事件线·{c['name']}（{c['summary'] or '进行中'}）：" + ("；".join(e["text"] for e in reversed(ev)) or "刚开始"))
            refs.append({"kind": "case", "id": c["id"], "label": f"事件线「{c['name']}」"})
        tl = training_line(training_profile(conn, user_id))
        if tl:
            lines.append("训练画像：" + tl)
            refs.append({"kind": "training", "label": "训练画像"})
    block = "\n".join(lines)
    return (block[:1600] if block else "（暂无）"), refs


def brief_for_extract(user_id: str) -> str:
    """提取记忆时给模型看的“已有记忆”（只列名字和少量事实，避免重复）。"""
    with get_conn() as conn:
        prof = _items(conn, user_id, type_="profile", limit=PROFILE_LIMIT)
        persons = _subjects(conn, user_id, "person")[:15]
        cases = _subjects(conn, user_id, "case")[:5]
        lines = []
        if prof:
            lines.append("我的档案：" + "；".join(i["text"] for i in prof))
        for p in persons:
            facts = _items(conn, user_id, subject_id=p["id"], limit=4)
            lines.append(f"人物·{p['name']}（别名：{'、'.join(p['aliases']) or '无'}）：" + "；".join(f["text"] for f in facts))
        for c in cases:
            lines.append(f"事件·{c['name']}（{c['status']}）")
    return "\n".join(lines) or "（暂无）"


# ---------------- 写 ----------------

def _add_item(conn, user_id, type_, text, subject_id=None, source="", consult_id=None) -> bool:
    text = _clean(text)
    if not text:
        return False
    if subject_id:
        existing = conn.execute("SELECT text FROM memory_item WHERE user_id = ? AND subject_id = ?", (user_id, subject_id))
    else:
        existing = conn.execute("SELECT text FROM memory_item WHERE user_id = ? AND type = ? AND subject_id IS NULL",
                                (user_id, type_))
    if any(_similar(text, r[0]) for r in existing):
        return False
    conn.execute("""INSERT INTO memory_item(user_id, type, subject_id, text, source, consult_id, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?)""", (user_id, type_, subject_id, text, source, consult_id, now_str(), now_str()))
    if subject_id:  # 超过上限时删掉最旧的非置顶条目
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM memory_item WHERE subject_id = ? AND pinned = 0 ORDER BY id DESC", (subject_id,))]
        for old in ids[MAX_ITEMS_PER_SUBJECT:]:
            conn.execute("DELETE FROM memory_item WHERE id = ?", (old,))
        conn.execute("UPDATE memory_subject SET last_seen = ? WHERE id = ?", (now_str(), subject_id))
    return True


def upsert_person(conn, user_id: str, name: str, aliases=(), relation: str = "") -> int:
    name = _clean(name)[:20]
    if not name:
        return 0
    p = find_person(conn, user_id, name)
    if not p:
        for a in aliases or []:
            p = find_person(conn, user_id, a)
            if p:
                break
    if p:
        al = list(dict.fromkeys(p["aliases"] + [a for a in (aliases or []) if a and a != p["name"]] +
                                ([name] if name != p["name"] else [])))[:8]
        conn.execute("UPDATE memory_subject SET aliases = ?, summary = CASE WHEN summary = '' THEN ? ELSE summary END, "
                     "last_seen = ? WHERE id = ?", (dumps(al), _clean(relation)[:40], now_str(), p["id"]))
        return p["id"]
    return conn.execute("""INSERT INTO memory_subject(user_id, kind, name, aliases, summary, last_seen, created_at)
                           VALUES (?,?,?,?,?,?,?)""",
                        (user_id, "person", name, dumps([a for a in (aliases or []) if a and a != name][:8]),
                         _clean(relation)[:40], now_str(), now_str())).lastrowid


def upsert_case(conn, user_id: str, title: str, goal: str = "", case_id: int = None) -> int:
    if case_id:
        row = conn.execute("SELECT id FROM memory_subject WHERE id = ? AND user_id = ?", (case_id, user_id)).fetchone()
        if row:  # 搁置的事有了新进展，自动恢复为进行中
            conn.execute("UPDATE memory_subject SET last_seen = ?, status = CASE WHEN status = 'dormant' THEN 'open' "
                         "ELSE status END WHERE id = ?", (now_str(), case_id))
            return case_id
    title = _clean(title)[:20]
    if not title:
        return 0
    return conn.execute("""INSERT INTO memory_subject(user_id, kind, name, summary, last_seen, created_at)
                           VALUES (?,?,?,?,?,?)""",
                        (user_id, "case", title, _clean(goal)[:60], now_str(), now_str())).lastrowid


def apply_extraction(user_id: str, data: dict, consult_id: int = None, case_id: int = None, source: str = "") -> dict:
    """把 memory_extract 的结果写进库；返回 {added, case_id, subjects（这次写到的卡片 id）}。"""
    if is_paused(user_id) or not isinstance(data, dict):
        return {"added": 0, "case_id": case_id, "subjects": []}
    added = 0
    touched = []
    with get_conn() as conn:
        for f in data.get("forget") or []:
            forget(conn, user_id, str(f))
        for t in (data.get("profile") or [])[:5]:
            added += _add_item(conn, user_id, "profile", t, source=source, consult_id=consult_id)
        for p in (data.get("people") or [])[:5]:
            if not isinstance(p, dict):
                continue
            pid = upsert_person(conn, user_id, p.get("name"), p.get("aliases") or [], p.get("relation") or "")
            if pid:
                touched.append(pid)
                for t in (p.get("facts") or [])[:5]:
                    added += _add_item(conn, user_id, "fact", t, pid, source, consult_id)
        c = data.get("case")
        if isinstance(c, dict) and (c.get("title") or case_id):
            case_id = upsert_case(conn, user_id, c.get("title"), c.get("goal") or "", case_id) or case_id
            if case_id:
                touched.append(case_id)
                if c.get("update"):
                    added += _add_item(conn, user_id, "event", c["update"], case_id, source, consult_id)
                if c.get("status") == "done":
                    conn.execute("UPDATE memory_subject SET status = 'done' WHERE id = ?", (case_id,))
    return {"added": added, "case_id": case_id, "subjects": list(dict.fromkeys(touched))}


def record_event(user_id: str, case_id: int, text: str, source: str = "", consult_id: int = None) -> None:
    if not case_id or is_paused(user_id):
        return
    with get_conn() as conn:
        _add_item(conn, user_id, "event", text, case_id, source, consult_id)


def forget(conn, user_id: str, text: str) -> int:
    """用户说“忘掉……”：删除内容相近的记忆条目和同名人物卡。"""
    text = (text or "").strip()
    if not text:
        return 0
    n = 0
    for r in conn.execute("SELECT id, text FROM memory_item WHERE user_id = ?", (user_id,)).fetchall():
        if _similar(text, r["text"]) or text in r["text"]:
            conn.execute("DELETE FROM memory_item WHERE id = ?", (r["id"],))
            n += 1
    p = find_person(conn, user_id, text)
    if p:
        conn.execute("DELETE FROM memory_subject WHERE id = ?", (p["id"],))
        n += 1
    return n


# ---------------- 管理（“智囊记得的”页面） ----------------

def overview(user_id: str) -> dict:
    with get_conn() as conn:
        profile = _items(conn, user_id, type_="profile", limit=100)
        people, cases = [], []
        for kind, out in (("person", people), ("case", cases)):
            for s in _subjects(conn, user_id, kind):
                s["items"] = _items(conn, user_id, subject_id=s["id"], limit=100)
                out.append(s)
        tp = training_profile(conn, user_id)
    return {"paused": is_paused(user_id), "profile": profile, "people": people, "cases": cases, "training": tp}


def update_item(user_id: str, item_id: int, text: str = None, pinned: bool = None) -> dict:
    with get_conn() as conn:
        r = conn.execute("SELECT id FROM memory_item WHERE id = ? AND user_id = ?", (item_id, user_id)).fetchone()
        if not r:
            raise NotFound("记忆不存在")
        if text is not None:
            t = re.sub(r"\s+", " ", text).strip()[:200]
            if not t:
                raise NotFound("内容不能为空")
            conn.execute("UPDATE memory_item SET text = ?, updated_at = ? WHERE id = ?", (t, now_str(), item_id))
        if pinned is not None:
            conn.execute("UPDATE memory_item SET pinned = ? WHERE id = ?", (1 if pinned else 0, item_id))
    return {"ok": True}


def add_profile(user_id: str, text: str) -> dict:
    with get_conn() as conn:
        t = re.sub(r"\s+", " ", text or "").strip()[:200]
        if t:
            conn.execute("""INSERT INTO memory_item(user_id, type, text, source, created_at, updated_at)
                            VALUES (?,?,?,?,?,?)""", (user_id, "profile", t, "我自己填写", now_str(), now_str()))
    return {"ok": True}


def delete_item(user_id: str, item_id: int) -> dict:
    with get_conn() as conn:
        n = conn.execute("DELETE FROM memory_item WHERE id = ? AND user_id = ?", (item_id, user_id)).rowcount
    if not n:
        raise NotFound("记忆不存在")
    return {"ok": True}


def update_subject(user_id: str, subject_id: int, body: dict) -> dict:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM memory_subject WHERE id = ? AND user_id = ?", (subject_id, user_id)).fetchone()
        if not r:
            raise NotFound("卡片不存在")
        name = (body.get("name") or r["name"]).strip()[:20]
        aliases = body.get("aliases")
        aliases = dumps([a.strip()[:20] for a in aliases if a and a.strip()][:8]) if isinstance(aliases, list) else r["aliases"]
        summary = (body.get("summary") if body.get("summary") is not None else r["summary"]).strip()[:60]
        status = body.get("status") if body.get("status") in ("open", "done", "dormant") else r["status"]
        conn.execute("UPDATE memory_subject SET name = ?, aliases = ?, summary = ?, status = ? WHERE id = ?",
                     (name, aliases, summary, status, subject_id))
    return {"ok": True}


def merge_subjects(user_id: str, keep_id: int, merge_id: int) -> dict:
    """把一张人物卡合并进另一张（名字变成别名，条目搬过去）。"""
    with get_conn() as conn:
        keep = conn.execute("SELECT * FROM memory_subject WHERE id = ? AND user_id = ?", (keep_id, user_id)).fetchone()
        other = conn.execute("SELECT * FROM memory_subject WHERE id = ? AND user_id = ?", (merge_id, user_id)).fetchone()
        if not keep or not other or keep_id == merge_id or keep["kind"] != other["kind"]:
            raise NotFound("卡片不存在或类型不同")
        al = list(dict.fromkeys(loads(keep["aliases"], []) + [other["name"]] + loads(other["aliases"], [])))[:8]
        conn.execute("UPDATE memory_subject SET aliases = ? WHERE id = ?", (dumps(al), keep_id))
        conn.execute("UPDATE memory_item SET subject_id = ? WHERE subject_id = ?", (keep_id, merge_id))
        conn.execute("DELETE FROM memory_subject WHERE id = ?", (merge_id,))
    return {"ok": True}


def delete_subject(user_id: str, subject_id: int) -> dict:
    with get_conn() as conn:
        n = conn.execute("DELETE FROM memory_subject WHERE id = ? AND user_id = ?", (subject_id, user_id)).rowcount
    if not n:
        raise NotFound("卡片不存在")
    return {"ok": True}


def clear_all(user_id: str) -> dict:
    with get_conn() as conn:
        conn.execute("DELETE FROM memory_item WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM memory_subject WHERE user_id = ?", (user_id,))
    return {"ok": True}


def delete_by_consult(conn, user_id: str, consult_id: int) -> None:
    conn.execute("DELETE FROM memory_item WHERE user_id = ? AND consult_id = ?", (user_id, consult_id))


# ---------------- 定期整理：压缩长卡片、搁置久未更新的事 ----------------

COMPACT_THRESHOLD = 12   # 一张卡上（不含置顶）超过这么多条就整理
COMPACT_LIMIT = 6        # 整理后最多保留
DORMANT_DAYS = 30


def mark_dormant(days: int = DORMANT_DAYS) -> int:
    """进行中的事件线超过 days 天没有动静 → 搁置（不再自动带进问计；有新进展时自动恢复）。"""
    from datetime import timedelta
    from ..db import TIME_FMT, now
    cutoff = (now() - timedelta(days=days)).strftime(TIME_FMT)
    with get_conn() as conn:
        return conn.execute("UPDATE memory_subject SET status = 'dormant' WHERE kind = 'case' AND status = 'open' "
                            "AND last_seen < ?", (cutoff,)).rowcount


def _loose_count(conn, subject_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM memory_item WHERE subject_id = ? AND pinned = 0", (subject_id,)).fetchone()[0]


def needs_compact(subject_id: int) -> bool:
    with get_conn() as conn:
        return _loose_count(conn, subject_id) > COMPACT_THRESHOLD


async def compact_subject(user_id: str, subject_id: int, force: bool = False) -> dict:
    """把一张卡上的条目交给 memory_compact 合并去重；置顶的不动。失败或结果为空时保持原样。"""
    from . import workflow
    with get_conn() as conn:
        subj = conn.execute("SELECT * FROM memory_subject WHERE id = ? AND user_id = ?", (subject_id, user_id)).fetchone()
        if not subj:
            raise NotFound("卡片不存在")
        rows = conn.execute("SELECT id, text, type FROM memory_item WHERE subject_id = ? AND pinned = 0 ORDER BY id",
                            (subject_id,)).fetchall()
    if is_paused(user_id) or len(rows) < (3 if force else COMPACT_THRESHOLD + 1):
        return {"ok": True, "before": len(rows), "after": len(rows), "changed": False}
    data = await workflow.run_memory_compact(user_id, subj["kind"], subj["name"], [r["text"] for r in rows],
                                             COMPACT_LIMIT, subject_id)
    items = []
    for t in (data.get("items") if isinstance(data, dict) else None) or []:
        t = _clean(t)
        if t and not any(_similar(t, x) for x in items):
            items.append(t)
    items = items[:COMPACT_LIMIT]
    if not items:
        return {"ok": True, "before": len(rows), "after": len(rows), "changed": False}
    type_ = "event" if subj["kind"] == "case" else "fact"
    summary = _clean(data.get("summary"))[:60]
    with get_conn() as conn:
        ids = [r["id"] for r in rows]
        # 只删参与整理的那几条：整理期间新写入的条目保留
        conn.execute(f"DELETE FROM memory_item WHERE id IN ({','.join('?' * len(ids))})", ids)
        src = f"整理于 {now_str()[:10]}"
        for t in items:
            conn.execute("""INSERT INTO memory_item(user_id, type, subject_id, text, source, created_at, updated_at)
                            VALUES (?,?,?,?,?,?,?)""", (user_id, type_, subject_id, t, src, now_str(), now_str()))
        if summary and (subj["kind"] == "case" or not subj["summary"]):
            conn.execute("UPDATE memory_subject SET summary = ? WHERE id = ?", (summary, subject_id))
        conn.execute("UPDATE memory_subject SET compacted_at = ? WHERE id = ?", (now_str(), subject_id))
    return {"ok": True, "before": len(rows), "after": len(items), "changed": True}


async def maintain(max_subjects: int = 20) -> dict:
    """定时任务：搁置久未更新的事；整理条目过多的卡片（每次最多 max_subjects 张，避免一次花太多）。"""
    out = {"dormant": mark_dormant(), "compacted": 0}
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT s.id, s.user_id FROM memory_subject s
               LEFT JOIN memory_setting m ON m.user_id = s.user_id
               WHERE COALESCE(m.paused, 0) = 0
                 AND (SELECT COUNT(*) FROM memory_item i WHERE i.subject_id = s.id AND i.pinned = 0) > ?
               ORDER BY s.last_seen DESC LIMIT ?""", (COMPACT_THRESHOLD, max_subjects)).fetchall()
    for r in rows:
        try:
            if (await compact_subject(r["user_id"], r["id"]))["changed"]:
                out["compacted"] += 1
        except Exception as e:  # noqa: BLE001  一张失败不影响其他
            log.warning("整理记忆失败 subject=%s：%s", r["id"], e)
    return out
