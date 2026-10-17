"""管理员导入场景库 / 表达框架（Markdown 或 ZIP）。

格式约定见 docs/场景库导入格式.md。
匹配键：
  - 分类：name
  - 场景：category + title
  - 训练：scenario + title（仅公共 owner_id IS NULL）
  - 框架：code
mode=upsert：有则更新字段，无则插入；不删除库里多出来的内容。
mode=add_only：只插入缺失项，已存在则跳过。
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any

from ..db import get_conn, set_drill_guide
from .sessions import BadRequest

MAX_BYTES = 8 * 1024 * 1024
MAX_MD_FILES = 40
MAX_DRILLS = 500
MAX_FRAMEWORKS = 300

_PRESSURES = {"低压", "中压", "高压"}
_H1 = re.compile(r"^#\s+(.+?)\s*$")
_H2 = re.compile(r"^##\s+(.+?)\s*$")
_H3 = re.compile(r"^###\s+(.+?)\s*$")
_H4 = re.compile(r"^####\s+(.+?)\s*$")
_FIELD = re.compile(r"^[-*]\s*(.+?)\s*[:：]\s*(.*)$")
_BULLET = re.compile(r"^[-*]\s+(.+?)\s*$")
_STEP = re.compile(r"^(\d+)[.\s、]+(.+)$")
_SEP = re.compile(r"\s*[|｜]\s*")


def _strip_prefix(title: str, *prefixes: str) -> str | None:
    t = (title or "").strip()
    for p in prefixes:
        if t.startswith(p):
            return t[len(p):].strip()
    return None


def _norm_key(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip().lower())


def _split_blocks(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return lines


def extract_md_texts(data: bytes, filename: str) -> list[tuple[str, str]]:
    """从 .md / .zip 抽出 (文件名, 文本)。"""
    name = (filename or "upload.md").lower()
    if name.endswith(".md") or name.endswith(".markdown") or name.endswith(".txt"):
        return [(filename or "upload.md", data.decode("utf-8-sig"))]
    if name.endswith(".zip"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise BadRequest("不是有效的 ZIP 文件") from e
        out = []
        for info in zf.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX/"):
                continue
            base = info.filename.split("/")[-1]
            if base.startswith("."):
                continue
            low = base.lower()
            if not (low.endswith(".md") or low.endswith(".markdown") or low.endswith(".txt")):
                continue
            raw = zf.read(info)
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gb18030")
            out.append((info.filename, text))
            if len(out) >= MAX_MD_FILES:
                break
        if not out:
            raise BadRequest("ZIP 里没有 .md / .txt 文件")
        return out
    raise BadRequest("只支持 .md / .txt / .zip")


def _detect_kind(text: str) -> str:
    head = text[:800].lower()
    if "talktool-frameworks" in head or "talktool-framework" in head:
        return "frameworks"
    if "talktool-catalog" in head or "talktool-场景" in head:
        return "catalog"
    # 启发式：出现「框架：」且很少「训练：」→ frameworks
    fw = len(re.findall(r"^##\s*框架[:：]", text, re.M))
    dr = len(re.findall(r"^###\s*训练[:：]", text, re.M))
    if fw and fw >= dr:
        return "frameworks"
    return "catalog"


def parse_catalog_md(text: str) -> list[dict]:
    """解析场景库 Markdown → [{name, scenarios:[{title, subtitle, drills:[...]}]}]。"""
    lines = _split_blocks(text)
    categories: list[dict] = []
    cat = sc = drill = None
    section = None  # description | pitfalls | frameworks | None
    buf: list[str] = []

    def flush_buf():
        nonlocal buf, section, drill
        if not drill or not section:
            buf = []
            return
        body = "\n".join(buf).strip()
        buf = []
        if section == "description":
            drill["description"] = body
        elif section == "pitfalls":
            items = []
            for ln in body.split("\n"):
                m = _BULLET.match(ln.strip())
                if m:
                    items.append(m.group(1).strip())
                elif ln.strip():
                    items.append(ln.strip())
            drill["pitfalls"] = items
        elif section == "frameworks":
            items = []
            for ln in body.split("\n"):
                m = _BULLET.match(ln.strip())
                raw = m.group(1).strip() if m else ln.strip()
                if not raw:
                    continue
                parts = _SEP.split(raw, maxsplit=1)
                code = parts[0].strip().strip("`")
                example = parts[1].strip() if len(parts) > 1 else ""
                if code:
                    items.append({"code": code, "example": example})
            drill["guide_frameworks"] = items
        section = None

    def ensure_cat(name: str):
        nonlocal cat, sc, drill
        flush_buf()
        for c in categories:
            if c["name"] == name:
                cat = c
                sc = drill = None
                return
        cat = {"name": name, "scenarios": []}
        categories.append(cat)
        sc = drill = None

    def ensure_sc(title: str):
        nonlocal sc, drill
        flush_buf()
        if not cat:
            raise BadRequest(f"场景「{title}」前缺少「# 分类：…」")
        for s in cat["scenarios"]:
            if s["title"] == title:
                sc = s
                drill = None
                return
        sc = {"title": title, "subtitle": "", "drills": []}
        cat["scenarios"].append(sc)
        drill = None

    def ensure_drill(title: str):
        nonlocal drill, section
        flush_buf()
        if not sc:
            raise BadRequest(f"训练「{title}」前缺少「## 场景：…」")
        for d in sc["drills"]:
            if d["title"] == title:
                drill = d
                section = None
                return
        drill = {
            "title": title,
            "description": "",
            "pressure": "中压",
            "duration_min": 3,
            "ai_role": "",
            "user_role": "",
            "training_goal": "",
            "opening_line": "",
            "pitfalls": [],
            "guide_frameworks": [],
        }
        sc["drills"].append(drill)
        section = None

    field_map = {
        "压力": "pressure", "压力等级": "pressure", "pressure": "pressure",
        "时长": "duration_min", "时长分钟": "duration_min", "预计时长": "duration_min", "duration": "duration_min",
        "用户角色": "user_role", "user_role": "user_role",
        "ai角色": "ai_role", "ai 角色": "ai_role", "ai_role": "ai_role",
        "训练目标": "training_goal", "目标": "training_goal", "training_goal": "training_goal",
        "开场白": "opening_line", "opening": "opening_line", "opening_line": "opening_line",
        "副标题": "_subtitle", "subtitle": "_subtitle",
    }

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            if section:
                buf.append("")
            continue
        if line.strip().startswith(">"):
            tip = line.strip()[1:].strip()
            if tip.lower().startswith("mode"):
                continue
            if sc and not drill and tip and not tip.startswith("talktool"):
                sc["subtitle"] = tip
            continue

        m4 = _H4.match(line)
        if m4:
            flush_buf()
            h = m4.group(1).strip()
            if "描述" in h:
                section = "description"
            elif "误区" in h:
                section = "pitfalls"
            elif "框架" in h or "推荐" in h:
                section = "frameworks"
            else:
                section = None
            buf = []
            continue

        m3 = _H3.match(line)
        if m3:
            title = _strip_prefix(m3.group(1), "训练：", "训练:", "Drill：", "Drill:", "drill：", "drill:")
            if title is None:
                title = m3.group(1).strip()
            ensure_drill(title)
            continue

        m2 = _H2.match(line)
        if m2:
            title = _strip_prefix(m2.group(1), "场景：", "场景:", "Scenario：", "Scenario:")
            if title is not None:
                ensure_sc(title)
                continue
            # 忽略其它 ##

        m1 = _H1.match(line)
        if m1:
            title = m1.group(1).strip()
            if title.lower().startswith("talktool"):
                continue
            name = _strip_prefix(title, "分类：", "分类:", "Category：", "Category:")
            if name is not None:
                ensure_cat(name)
                continue
            # 裸一级标题也当分类名（兼容）
            if not title.startswith("框架"):
                ensure_cat(title)
            continue

        if section:
            buf.append(line)
            continue

        fm = _FIELD.match(line.strip())
        if fm and drill:
            key = _norm_key(fm.group(1))
            val = fm.group(2).strip()
            mapped = field_map.get(key) or field_map.get(fm.group(1).strip())
            if not mapped:
                # 模糊：去掉空格再找
                mapped = field_map.get(key.replace(" ", ""))
            if mapped == "_subtitle" and sc:
                sc["subtitle"] = val
            elif mapped == "pressure":
                p = val.replace(" ", "")
                if p not in _PRESSURES:
                    raise BadRequest(f"训练「{drill['title']}」压力等级只能是 低压/中压/高压，收到：{val}")
                drill["pressure"] = p
            elif mapped == "duration_min":
                num = re.search(r"\d+", val)
                if not num:
                    raise BadRequest(f"训练「{drill['title']}」时长无效：{val}")
                drill["duration_min"] = max(1, min(30, int(num.group())))
            elif mapped:
                drill[mapped] = val
            continue

        if sc and not drill:
            sub = _strip_prefix(line.strip(), "副标题：", "副标题:")
            if sub is not None:
                sc["subtitle"] = sub

    flush_buf()
    # 校验
    total = 0
    for c in categories:
        for s in c["scenarios"]:
            for d in s["drills"]:
                total += 1
                if not d.get("description"):
                    raise BadRequest(f"训练「{d['title']}」缺少「#### 场景描述」")
                if not d.get("ai_role") or not d.get("user_role"):
                    raise BadRequest(f"训练「{d['title']}」需要填写 AI角色 与 用户角色")
                if not d.get("training_goal"):
                    raise BadRequest(f"训练「{d['title']}」需要填写 训练目标")
                if not d.get("opening_line"):
                    raise BadRequest(f"训练「{d['title']}」需要填写 开场白")
    if total == 0 and not categories:
        raise BadRequest("未解析到任何分类/场景/训练，请检查 Markdown 标题格式")
    if total > MAX_DRILLS:
        raise BadRequest(f"单次最多导入 {MAX_DRILLS} 个训练，当前 {total}")
    return categories


def parse_frameworks_md(text: str) -> list[dict]:
    """解析框架库 Markdown → [{code, name, category, ...}]。"""
    lines = _split_blocks(text)
    items: list[dict] = []
    cur = None
    section = None
    buf: list[str] = []

    def flush_buf():
        nonlocal buf, section, cur
        if not cur or not section:
            buf = []
            return
        body = "\n".join(buf).strip()
        buf = []
        if section == "steps":
            steps = []
            for ln in body.split("\n"):
                ln = ln.strip()
                if not ln:
                    continue
                bm = _BULLET.match(ln)
                raw = bm.group(1).strip() if bm else ln
                sm = _STEP.match(raw)
                if sm:
                    raw = sm.group(2).strip()
                parts = _SEP.split(raw)
                if len(parts) >= 3:
                    steps.append({"key": parts[0].strip(), "name": parts[1].strip(), "desc": parts[2].strip()})
                elif len(parts) == 2:
                    steps.append({"key": str(len(steps) + 1), "name": parts[0].strip(), "desc": parts[1].strip()})
                else:
                    steps.append({"key": str(len(steps) + 1), "name": parts[0].strip(), "desc": ""})
            cur["steps"] = steps
        elif section == "example":
            cur["example"] = body
        elif section == "pitfalls":
            cur["pitfalls"] = [_BULLET.match(x.strip()).group(1) if _BULLET.match(x.strip()) else x.strip()
                               for x in body.split("\n") if x.strip()]
        elif section == "tips":
            cur["tips"] = [_BULLET.match(x.strip()).group(1) if _BULLET.match(x.strip()) else x.strip()
                           for x in body.split("\n") if x.strip()]
        elif section == "detail":
            cur["detail"] = body
        section = None

    field_map = {
        "code": "code", "编码": "code", "标识": "code",
        "分类": "category", "category": "category",
        "摘要": "summary", "summary": "summary",
        "适用": "when_to_use", "适用场合": "when_to_use", "when": "when_to_use",
        "来源": "source", "source": "source",
    }

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            if section:
                buf.append("")
            continue

        m3 = _H3.match(line) or _H4.match(line)
        if m3 and cur:
            flush_buf()
            h = m3.group(1).strip()
            if "步骤" in h:
                section = "steps"
            elif "示例" in h or "例子" in h:
                section = "example"
            elif "误区" in h:
                section = "pitfalls"
            elif "技巧" in h or "提示" in h:
                section = "tips"
            elif "说明" in h or "详情" in h or "写作" in h:
                section = "detail"
            else:
                section = None
            buf = []
            continue

        m2 = _H2.match(line)
        if m2:
            flush_buf()
            name = _strip_prefix(m2.group(1), "框架：", "框架:", "Framework：", "Framework:")
            if name is None:
                name = m2.group(1).strip()
            cur = {
                "code": "", "name": name, "category": "结构表达", "summary": "",
                "steps": [], "when_to_use": "", "example": "", "pitfalls": [], "tips": [],
                "detail": "", "source": "导入",
            }
            items.append(cur)
            section = None
            continue

        m1 = _H1.match(line)
        if m1 and m1.group(1).strip().lower().startswith("talktool"):
            continue

        if section and cur:
            buf.append(line)
            continue

        fm = _FIELD.match(line.strip())
        if fm and cur:
            key = _norm_key(fm.group(1))
            val = fm.group(2).strip()
            mapped = field_map.get(key) or field_map.get(fm.group(1).strip())
            if mapped:
                cur[mapped] = val
            continue

    flush_buf()
    out = []
    for it in items:
        if not it.get("code"):
            # 从 name 生成简易 code
            raise BadRequest(f"框架「{it['name']}」缺少 code 字段")
        if not it.get("summary"):
            raise BadRequest(f"框架「{it['name']}」缺少摘要")
        if not it.get("steps"):
            raise BadRequest(f"框架「{it['name']}」缺少步骤")
        out.append(it)
    if len(out) > MAX_FRAMEWORKS:
        raise BadRequest(f"单次最多导入 {MAX_FRAMEWORKS} 个框架")
    return out


def _upsert_frameworks(conn, frameworks: list[dict], mode: str) -> dict:
    added = updated = skipped = 0
    for i, f in enumerate(frameworks):
        vals = (f["name"], f["category"], f["summary"],
                json.dumps(f["steps"], ensure_ascii=False),
                f.get("when_to_use", ""), f.get("example", ""),
                json.dumps(f.get("pitfalls", []), ensure_ascii=False),
                json.dumps(f.get("tips", []), ensure_ascii=False),
                f.get("detail", ""), f.get("source", "导入"), 9000 + i)
        row = conn.execute("SELECT id FROM framework WHERE code = ?", (f["code"],)).fetchone()
        if row:
            if mode == "add_only":
                skipped += 1
                continue
            conn.execute("""UPDATE framework SET name=?, category=?, summary=?, steps=?, when_to_use=?, example=?,
                            pitfalls=?, tips=?, detail=?, source=?, sort_order=? WHERE code=?""",
                         vals + (f["code"],))
            updated += 1
        else:
            conn.execute("""INSERT INTO framework(name, category, summary, steps, when_to_use, example, pitfalls, tips,
                            detail, source, sort_order, code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                         vals + (f["code"],))
            added += 1
    return {"added": added, "updated": updated, "skipped": skipped}


def _upsert_catalog(conn, categories: list[dict], mode: str) -> dict:
    added = updated = skipped = 0
    cat_added = sc_added = 0
    fw_ids = {r[0]: r[1] for r in conn.execute("SELECT code, id FROM framework")}
    max_cat_order = conn.execute("SELECT COALESCE(MAX(sort_order), -1) FROM category WHERE is_system = 0").fetchone()[0]

    for ci, cat in enumerate(categories):
        row = conn.execute("SELECT id FROM category WHERE name = ? AND is_system = 0", (cat["name"],)).fetchone()
        if row:
            cid = row[0]
        else:
            max_cat_order += 1
            cid = conn.execute(
                "INSERT INTO category(name, sort_order) VALUES (?, ?)", (cat["name"], max_cat_order)).lastrowid
            cat_added += 1

        for si, sc in enumerate(cat["scenarios"]):
            row = conn.execute("SELECT id FROM scenario WHERE category_id = ? AND title = ?",
                               (cid, sc["title"])).fetchone()
            if row:
                sid = row[0]
                if mode != "add_only" and sc.get("subtitle"):
                    conn.execute("UPDATE scenario SET subtitle = ? WHERE id = ?", (sc["subtitle"], sid))
            else:
                sid = conn.execute(
                    "INSERT INTO scenario(category_id, title, subtitle, sort_order) VALUES (?,?,?,?)",
                    (cid, sc["title"], sc.get("subtitle", ""), si)).lastrowid
                sc_added += 1

            for di, d in enumerate(sc["drills"]):
                row = conn.execute(
                    "SELECT id FROM drill WHERE scenario_id = ? AND title = ? AND owner_id IS NULL",
                    (sid, d["title"])).fetchone()
                pitfalls = d.get("pitfalls") or []
                guide_fw = d.get("guide_frameworks") or []
                if row:
                    if mode == "add_only":
                        skipped += 1
                        continue
                    drill_id = row[0]
                    conn.execute(
                        """UPDATE drill SET description=?, pressure_level=?, duration_min=?, ai_role=?, user_role=?,
                           training_goal=?, opening_line=?, pitfalls=?, status='online', sort_order=?
                           WHERE id=?""",
                        (d["description"], d["pressure"], d["duration_min"], d["ai_role"], d["user_role"],
                         d["training_goal"], d["opening_line"], json.dumps(pitfalls, ensure_ascii=False), di, drill_id))
                    set_drill_guide(conn, drill_id,
                                    [(x["code"], x.get("example", "")) for x in guide_fw],
                                    pitfalls, fw_ids)
                    updated += 1
                else:
                    drill_id = conn.execute(
                        """INSERT INTO drill(scenario_id, title, description, cover_image, pressure_level,
                           duration_min, mode, ai_role, user_role, training_goal, opening_line,
                           system_prompt, status, sort_order, pitfalls)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sid, d["title"], d["description"], "", d["pressure"], d["duration_min"], "纯语音",
                         d["ai_role"], d["user_role"], d["training_goal"], d["opening_line"], "",
                         "online", di, json.dumps(pitfalls, ensure_ascii=False))).lastrowid
                    set_drill_guide(conn, drill_id,
                                    [(x["code"], x.get("example", "")) for x in guide_fw],
                                    pitfalls, fw_ids)
                    added += 1

    return {
        "categories_added": cat_added,
        "scenarios_added": sc_added,
        "drills_added": added,
        "drills_updated": updated,
        "drills_skipped": skipped,
    }


def import_bytes(data: bytes, filename: str, mode: str = "upsert") -> dict[str, Any]:
    if not data:
        raise BadRequest("文件为空")
    if len(data) > MAX_BYTES:
        raise BadRequest(f"文件过大（上限 {MAX_BYTES // (1024 * 1024)}MB）")
    mode = (mode or "upsert").strip().lower()
    if mode not in ("upsert", "add_only"):
        raise BadRequest("mode 只能是 upsert 或 add_only")

    texts = extract_md_texts(data, filename)
    all_fw: list[dict] = []
    all_cats: list[dict] = []
    files = []

    for fname, text in texts:
        kind = _detect_kind(text)
        files.append({"name": fname, "kind": kind})
        if kind == "frameworks":
            all_fw.extend(parse_frameworks_md(text))
        else:
            # 合并同名分类
            for cat in parse_catalog_md(text):
                existing = next((c for c in all_cats if c["name"] == cat["name"]), None)
                if not existing:
                    all_cats.append(cat)
                    continue
                for sc in cat["scenarios"]:
                    esc = next((s for s in existing["scenarios"] if s["title"] == sc["title"]), None)
                    if not esc:
                        existing["scenarios"].append(sc)
                    else:
                        if sc.get("subtitle"):
                            esc["subtitle"] = sc["subtitle"]
                        titles = {d["title"] for d in esc["drills"]}
                        for d in sc["drills"]:
                            if d["title"] in titles:
                                esc["drills"] = [d if x["title"] == d["title"] else x for x in esc["drills"]]
                            else:
                                esc["drills"].append(d)

    if not all_fw and not all_cats:
        raise BadRequest("没有可导入的内容")

    with get_conn() as conn:
        fw_stat = _upsert_frameworks(conn, all_fw, mode) if all_fw else {"added": 0, "updated": 0, "skipped": 0}
        cat_stat = _upsert_catalog(conn, all_cats, mode) if all_cats else {
            "categories_added": 0, "scenarios_added": 0, "drills_added": 0, "drills_updated": 0, "drills_skipped": 0}

    return {
        "ok": True,
        "mode": mode,
        "files": files,
        "frameworks": fw_stat,
        "catalog": cat_stat,
        "summary": (
            f"框架 +{fw_stat['added']}/改{fw_stat['updated']}；"
            f"训练 +{cat_stat['drills_added']}/改{cat_stat['drills_updated']}"
            + (f"/跳过{cat_stat['drills_skipped']}" if cat_stat['drills_skipped'] else "")
        ),
    }
