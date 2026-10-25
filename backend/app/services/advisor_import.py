"""管理员导入谋略 / 谋士 / 智囊团（Markdown），格式见 docs/谋略库导入格式.md。

文件第一行（或前几行）写 `# talktool-strategies` / `# talktool-advisors` / `# talktool-councils`，
也可以不写，按 `## 谋略：` / `## 谋士：` / `## 智囊团：` 自动识别。

- 匹配键都是 code；导入的行 customized=1，以后程序升级不会覆盖
- mode=upsert：有则更新，无则新增；mode=add_only：已存在就跳过
- 体系既可以填已有体系的 code / 名称，也可以填一个新名称（作为自定义体系出现在谋略库里）
"""
from __future__ import annotations

import json
import re

from ..strategies_data import DOMAINS, SCHOOLS
from .sessions import BadRequest

MAX_ITEMS = 500
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
COUNCIL_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,20}$")
_H2 = re.compile(r"^##\s+(.+?)\s*$")
_H3 = re.compile(r"^#{3,4}\s+(.+?)\s*$")
_FIELD = re.compile(r"^[-*]\s*([^:：]{1,12}?)\s*[:：]\s*(.*)$")
_BULLET = re.compile(r"^(?:[-*]|\d+[.、)）])\s*(.+?)\s*$")
_SPLIT = re.compile(r"\s*[,，、;；/|｜]\s*")

KINDS = {
    "strategies": ("谋略", "talktool-strategies"),
    "advisors": ("谋士", "talktool-advisors"),
    "councils": ("智囊团", "talktool-councils"),
}

STRATEGY_FIELDS = {"code": "code", "体系": "school", "流派": "school", "school": "school", "出处": "sub", "篇章": "sub",
                   "副标题": "sub", "sub": "sub", "领域": "domains", "适用": "domains", "domains": "domains",
                   "慎用": "caution", "caution": "caution", "框架": "frameworks", "表达框架": "frameworks",
                   "frameworks": "frameworks", "启用": "enabled"}
STRATEGY_SECTIONS = {"原文": "origin", "白话": "plain", "要点": "plain", "怎么做": "how_to_do", "识别": "how_to_do",
                     "防范": "how_to_do", "怎么说": "how_to_say", "话术": "how_to_say", "误用": "misuses", "注意": "misuses"}
ADVISOR_FIELDS = {"code": "code", "头像": "avatar", "头像字": "avatar", "风格": "style", "体系": "schools", "擅长": "schools"}
ADVISOR_SECTIONS = {"人设": "persona", "简介": "persona"}
COUNCIL_FIELDS = {"code": "code", "图标": "icon", "图标字": "icon", "谋士": "advisors", "体系": "schools",
                  "领域": "domains", "启用": "enabled"}
COUNCIL_SECTIONS = {"处理": "description", "描述": "description", "要求": "requirement", "示例": "examples"}


def detect(text: str) -> str | None:
    head = text[:800].lower()
    for kind, (_, marker) in KINDS.items():
        if marker in head:
            return kind
    counts = {k: len(re.findall(rf"^##\s*{label}[:：]", text, re.M)) for k, (label, _) in KINDS.items()}
    best = max(counts, key=counts.get)
    return best if counts[best] else None


def _yes(v: str) -> bool:
    return (v or "").strip().lower() in ("是", "yes", "y", "true", "1", "慎用", "对")


def _bullets(body: str) -> list:
    out = []
    for ln in body.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        m = _BULLET.match(ln)
        out.append((m.group(1) if m else ln).strip())
    return out


def _parse(text: str, label: str, fields: dict, sections: dict) -> list:
    items, cur, sec, buf = [], None, None, []

    def flush():
        nonlocal buf
        if cur is not None and sec:
            cur["_sec"][sec] = "\n".join(buf).strip()
        buf = []

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        m2 = _H2.match(line)
        if m2:
            flush()
            sec = None
            title = re.sub(rf"^{label}\s*[:：]\s*", "", m2.group(1).strip())
            cur = {"name": title, "_sec": {}}
            items.append(cur)
            continue
        if cur is None:
            continue
        m3 = _H3.match(line)
        if m3:
            flush()
            h = m3.group(1).strip()
            sec = next((v for k, v in sections.items() if k in h), None)
            continue
        if sec:
            buf.append(line)
            continue
        fm = _FIELD.match(line.strip())
        if fm:
            key = fields.get(fm.group(1).strip().lower()) or fields.get(fm.group(1).strip())
            if key:
                cur[key] = fm.group(2).strip()
    flush()
    if len(items) > MAX_ITEMS:
        raise BadRequest(f"单次最多导入 {MAX_ITEMS} 条")
    return items


def _school(v: str) -> str:
    v = (v or "").strip()
    if v in SCHOOLS:
        return v
    for code, meta in SCHOOLS.items():
        if v == meta[0] or v in meta[0].split(" / "):
            return code
    return v[:20]   # 新体系：直接用名称


def parse_strategies(text: str, fw_codes: set, warnings: list) -> list:
    out = []
    for it in _parse(text, "谋略", STRATEGY_FIELDS, STRATEGY_SECTIONS):
        sec, name = it["_sec"], it["name"][:30]
        code = (it.get("code") or "").strip().strip("`")
        if not CODE_RE.match(code):
            raise BadRequest(f"谋略「{name}」的 code 只能用小写字母、数字和下划线（字母开头，2-40 位）")
        if not it.get("school"):
            raise BadRequest(f"谋略「{name}」缺少「体系」")
        if not sec.get("plain") or not sec.get("how_to_do") or not sec.get("how_to_say"):
            raise BadRequest(f"谋略「{name}」需要 白话 / 怎么做 / 怎么说 三段")
        domains = [d for d in _SPLIT.split(it.get("domains") or "") if d]
        bad = [d for d in domains if d not in DOMAINS]
        if bad:
            warnings.append(f"谋略「{name}」的领域 {'、'.join(bad)} 不在列表里，已忽略")
        fws = [f.strip("` ") for f in _SPLIT.split(it.get("frameworks") or "") if f.strip("` ")]
        unknown = [f for f in fws if f not in fw_codes]
        if unknown:
            warnings.append(f"谋略「{name}」的框架 {'、'.join(unknown)} 不存在，已忽略")
        out.append({
            "code": code, "name": name, "school": _school(it["school"]), "sub": (it.get("sub") or "")[:40],
            "origin": sec.get("origin", "")[:500], "plain": sec["plain"][:500],
            "domains": [d for d in domains if d in DOMAINS] or ["为人处世"],
            "how_to_do": [x[:200] for x in _bullets(sec["how_to_do"])][:8],
            "how_to_say": sec["how_to_say"].strip().strip("“”\"")[:300],
            "framework_codes": [f for f in fws if f in fw_codes][:4],
            "misuses": sec.get("misuses", "")[:300], "caution": _yes(it.get("caution", "")),
            "enabled": 0 if (it.get("enabled") and not _yes(it["enabled"])) else 1,
        })
    return out


def parse_advisors(text: str) -> list:
    out = []
    for it in _parse(text, "谋士", ADVISOR_FIELDS, ADVISOR_SECTIONS):
        name = it["name"][:10]
        code = (it.get("code") or "").strip().strip("`")
        if not CODE_RE.match(code) or code.startswith("my_"):
            raise BadRequest(f"谋士「{name}」的 code 不合法（小写字母开头，不能以 my_ 开头）")
        persona = re.sub(r"\s+", " ", it["_sec"].get("persona", "")).strip()
        if len(persona) < 6:
            raise BadRequest(f"谋士「{name}」缺少「人设」")
        out.append({"code": code, "name": name, "avatar": (it.get("avatar") or name[:1])[:2],
                    "style": (it.get("style") or "")[:8], "persona": persona[:400],
                    "schools": [_school(s) for s in _SPLIT.split(it.get("schools") or "") if s][:4]})
    return out


def parse_councils(text: str) -> list:
    out = []
    for it in _parse(text, "智囊团", COUNCIL_FIELDS, COUNCIL_SECTIONS):
        name, sec = it["name"][:20], it["_sec"]
        code = (it.get("code") or "").strip().strip("`")
        if not COUNCIL_CODE_RE.match(code):
            raise BadRequest(f"智囊团「{name}」的 code 只能用小写字母、数字和下划线（字母开头，2-21 位）")
        advisors = [a for a in _SPLIT.split(it.get("advisors") or "") if a]
        if not advisors:
            raise BadRequest(f"智囊团「{name}」至少要有一位谋士")
        if not sec.get("description"):
            raise BadRequest(f"智囊团「{name}」缺少「处理什么问题」")
        out.append({"code": code, "name": name, "icon": (it.get("icon") or name[:1])[:2],
                     "advisors": advisors[:4], "schools": [_school(s) for s in _SPLIT.split(it.get("schools") or "") if s],
                     "domains": [d for d in _SPLIT.split(it.get("domains") or "") if d in DOMAINS],
                     "description": re.sub(r"\s+", " ", sec["description"])[:120],
                     "requirement": sec.get("requirement", "")[:300],
                     "examples": [e[:40] for e in _bullets(sec.get("examples", ""))][:5],
                     "enabled": 0 if (it.get("enabled") and not _yes(it["enabled"])) else 1})
    return out


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def upsert_strategies(conn, items: list, mode: str) -> dict:
    stat = {"added": 0, "updated": 0, "skipped": 0}
    base = (conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM strategy").fetchone()[0] or 0) + 1
    for i, s in enumerate(items):
        vals = (s["school"], s["name"], s["sub"], s["origin"], s["plain"], _j(s["domains"]), _j(s["how_to_do"]),
                s["how_to_say"], _j(s["framework_codes"]), s["misuses"], 1 if s["caution"] else 0, s["enabled"])
        if conn.execute("SELECT 1 FROM strategy WHERE code = ?", (s["code"],)).fetchone():
            if mode == "add_only":
                stat["skipped"] += 1
                continue
            conn.execute("""UPDATE strategy SET school=?, name=?, sub=?, origin=?, plain=?, domains=?, how_to_do=?,
                            how_to_say=?, framework_codes=?, misuses=?, caution=?, enabled=?, customized=1 WHERE code=?""",
                         vals + (s["code"],))
            stat["updated"] += 1
        else:
            conn.execute("""INSERT INTO strategy(school, name, sub, origin, plain, domains, how_to_do, how_to_say,
                            framework_codes, misuses, caution, enabled, customized, sort_order, code)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""", vals + (base + i, s["code"]))
            stat["added"] += 1
    return stat


def upsert_advisors(conn, items: list, mode: str) -> dict:
    stat = {"added": 0, "updated": 0, "skipped": 0}
    for i, a in enumerate(items):
        row = conn.execute("SELECT owner_id FROM advisor WHERE code = ?", (a["code"],)).fetchone()
        vals = (a["name"], a["avatar"], _j(a["schools"]), a["persona"], a["style"])
        if row:
            if row[0]:
                raise BadRequest(f"谋士 code「{a['code']}」已被用户的私人谋士占用，换一个")
            if mode == "add_only":
                stat["skipped"] += 1
                continue
            conn.execute("UPDATE advisor SET name=?, avatar=?, schools=?, persona=?, style=?, customized=1 WHERE code=?",
                         vals + (a["code"],))
            stat["updated"] += 1
        else:
            conn.execute("""INSERT INTO advisor(name, avatar, schools, persona, style, customized, sort_order, code)
                            VALUES (?,?,?,?,?,1,?,?)""", vals + (500 + i, a["code"]))
            stat["added"] += 1
    return stat


def upsert_councils(conn, items: list, mode: str) -> dict:
    stat = {"added": 0, "updated": 0, "skipped": 0}
    known = {r[0] for r in conn.execute("SELECT code FROM advisor WHERE owner_id IS NULL")}
    for c in items:
        missing = [a for a in c["advisors"] if a not in known]
        if missing:
            raise BadRequest(f"智囊团「{c['name']}」的谋士 {'、'.join(missing)} 不存在（可以先导入谋士）")
        if c["code"] == "general" and not c["enabled"]:
            raise BadRequest("综合团是兜底团，不能停用")
        vals = (c["name"], c["icon"], c["description"], _j(c["advisors"]), _j(c["schools"]), _j(c["domains"]),
                c["requirement"], _j(c["examples"]), c["enabled"])
        if conn.execute("SELECT 1 FROM council WHERE code = ?", (c["code"],)).fetchone():
            if mode == "add_only":
                stat["skipped"] += 1
                continue
            conn.execute("""UPDATE council SET name=?, icon=?, description=?, advisors=?, schools=?, domains=?,
                            requirement=?, examples=?, enabled=?, customized=1 WHERE code=?""", vals + (c["code"],))
            stat["updated"] += 1
        else:
            order = (conn.execute("SELECT MAX(sort_order) FROM council WHERE code != 'general'").fetchone()[0] or 0) + 1
            conn.execute("UPDATE council SET sort_order = sort_order + 1 WHERE code = 'general'")
            conn.execute("""INSERT INTO council(name, icon, description, advisors, schools, domains, requirement, examples,
                            enabled, customized, sort_order, code) VALUES (?,?,?,?,?,?,?,?,?,1,?,?)""",
                         vals + (order, c["code"]))
            stat["added"] += 1
    return stat
