"""提示词存取：默认版（代码）+ 后台版本（prompt_template 表）。

- 生效顺序：试运行时的草稿覆盖 > active 版本 > 代码默认版
- 每个 key 最多一个 draft、一个 active；发布时 active → archived，draft → active
"""
import contextvars
import re

from ..db import get_conn, loads, now_str, row_to_dict
from ..prompts_default import DEFAULTS, council_default_for
from .sessions import BadRequest, NotFound

CAPABILITIES = ("fast-chat", "quality-chat")
VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_override = contextvars.ContextVar("prompt_override", default=None)


def _default(key: str) -> dict:
    if key in DEFAULTS:
        return DEFAULTS[key]
    if key.startswith("council."):
        code = key.split(".", 1)[1]
        with get_conn() as conn:
            row = conn.execute("SELECT name, requirement FROM council WHERE code = ?", (code,)).fetchone()
        if row:
            return council_default_for(code, row["name"], row["requirement"])
    raise NotFound(f"提示词 {key} 不存在")


def _row_to_prompt(row, base: dict) -> dict:
    r = row_to_dict(row)
    return {**base, "system": r["system"], "user": r["user_template"],
            "capability": r["capability"] or base["capability"],
            "max_tokens": r["max_tokens"] or base["max_tokens"],
            "temperature": base["temperature"] if r["temperature"] is None else r["temperature"],
            "version": r["version"], "source": r["status"]}


def get(key: str) -> dict:
    """当前生效的提示词（试运行时返回草稿）。"""
    base = {**_default(key), "version": 0, "source": "default"}
    ov = _override.get()
    if ov and key in ov:
        return {**base, **ov[key]}
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM prompt_template WHERE key = ? AND status = 'active' ORDER BY version DESC LIMIT 1",
                           (key,)).fetchone()
    return _row_to_prompt(row, base) if row else base


def render(key: str, variables: dict) -> tuple:
    """返回 (messages, meta)；未提供的变量替换为“（无）”。"""
    p = get(key)

    def fill(text: str) -> str:
        return VAR_RE.sub(lambda m: str(variables.get(m.group(1)) or "（无）"), text or "")

    messages = []
    if p.get("system"):
        messages.append({"role": "system", "content": fill(p["system"])})
    messages.append({"role": "user", "content": fill(p["user"])})
    meta = {k: p[k] for k in ("capability", "max_tokens", "temperature", "output", "version", "source")}
    return messages, meta


class use_override:
    """试运行：with use_override({"intent": {...草稿字段}}): ..."""

    def __init__(self, mapping: dict):
        self.mapping = mapping

    def __enter__(self):
        self.token = _override.set(self.mapping)

    def __exit__(self, *a):
        _override.reset(self.token)


# ---------------- 后台管理 ----------------

def all_keys() -> list:
    keys = [k for k in DEFAULTS if not k.startswith("council.")]
    with get_conn() as conn:
        councils = [r[0] for r in conn.execute("SELECT code FROM council ORDER BY sort_order, id")]
    return keys[:1] + [f"council.{c}" for c in councils] + keys[1:]


def _status_of(conn, key: str) -> dict:
    rows = conn.execute("SELECT version, status, created_at FROM prompt_template WHERE key = ? AND status != 'archived'",
                        (key,)).fetchall()
    active = next((r for r in rows if r["status"] == "active"), None)
    draft = next((r for r in rows if r["status"] == "draft"), None)
    return {"active_version": active["version"] if active else 0,
            "updated_at": active["created_at"] if active else "",
            "has_draft": bool(draft)}


def list_prompts() -> list:
    out = []
    with get_conn() as conn:
        for key in all_keys():
            d = _default(key)
            out.append({"key": key, "name": d["name"], "node": d["node"], "capability": d["capability"],
                        "required": d["required"], **_status_of(conn, key)})
    return out


def detail(key: str) -> dict:
    d = _default(key)
    with get_conn() as conn:
        rows = [row_to_dict(r) for r in conn.execute(
            "SELECT id, version, status, note, updated_by, created_at, system, user_template, capability, max_tokens, temperature "
            "FROM prompt_template WHERE key = ? ORDER BY version DESC", (key,))]
    pick = lambda st: next((r for r in rows if r["status"] == st), None)  # noqa: E731
    fmt = lambda r: r and {"version": r["version"], "system": r["system"], "user": r["user_template"],  # noqa: E731
                           "capability": r["capability"], "max_tokens": r["max_tokens"],
                           "temperature": r["temperature"], "note": r["note"], "created_at": r["created_at"]}
    return {
        "key": key, "name": d["name"], "node": d["node"], "output": d["output"], "required": d["required"],
        "variables": sorted(set(VAR_RE.findall(d["system"] + d["user"]))),
        "default": {"system": d["system"], "user": d["user"], "capability": d["capability"],
                    "max_tokens": d["max_tokens"], "temperature": d["temperature"]},
        "active": fmt(pick("active")), "draft": fmt(pick("draft")),
        "history": [{"version": r["version"], "status": r["status"], "note": r["note"], "created_at": r["created_at"]}
                    for r in rows if r["status"] != "draft"],
        "ratings": _ratings(key),
    }


def _ratings(key: str) -> dict:
    """各版本出的锦囊被用户评为“有用”的比例（version 0 = 默认版）。"""
    from .advisor_stats import prompt_version_stats
    return prompt_version_stats(key)


def _validate(key: str, body: dict) -> dict:
    d = _default(key)
    system, user = (body.get("system") or "").strip(), (body.get("user") or "").strip()
    if not user:
        raise BadRequest("用户消息模板不能为空")
    if len(system) + len(user) > 12000:
        raise BadRequest("提示词太长了（系统设定 + 消息模板最多 12000 字）")
    present = set(VAR_RE.findall(system + user))
    missing = [v for v in d["required"] if v not in present]
    if missing:
        raise BadRequest("缺少必填变量：" + "、".join("{{%s}}" % v for v in missing))
    if d["output"] == "json" and "JSON" not in (system + user).upper():
        raise BadRequest("这个节点要求输出 JSON，提示词里请保留输出 JSON 的要求")
    cap = body.get("capability") or d["capability"]
    if cap not in CAPABILITIES:
        raise BadRequest("能力只能是 fast-chat 或 quality-chat")
    try:
        max_tokens = int(body.get("max_tokens") or d["max_tokens"])
        temperature = float(d["temperature"] if body.get("temperature") in (None, "") else body["temperature"])
    except (TypeError, ValueError):
        raise BadRequest("最大长度和温度必须是数字")
    if not 100 <= max_tokens <= 4000:
        raise BadRequest("最大输出长度需在 100–4000 之间")
    if not 0 <= temperature <= 1.5:
        raise BadRequest("温度需在 0–1.5 之间")
    return {"system": system, "user": user, "capability": cap, "max_tokens": max_tokens, "temperature": temperature,
            "note": (body.get("note") or "").strip()[:200]}


def save_draft(key: str, body: dict, admin_id: int) -> dict:
    v = _validate(key, body)
    with get_conn() as conn:
        draft = conn.execute("SELECT id FROM prompt_template WHERE key = ? AND status = 'draft'", (key,)).fetchone()
        if draft:
            conn.execute("""UPDATE prompt_template SET system=?, user_template=?, capability=?, max_tokens=?,
                            temperature=?, note=?, updated_by=?, created_at=? WHERE id=?""",
                         (v["system"], v["user"], v["capability"], v["max_tokens"], v["temperature"], v["note"],
                          admin_id, now_str(), draft["id"]))
        else:
            ver = (conn.execute("SELECT MAX(version) FROM prompt_template WHERE key = ?", (key,)).fetchone()[0] or 0) + 1
            conn.execute("""INSERT INTO prompt_template(key, version, system, user_template, capability, max_tokens,
                            temperature, status, note, updated_by, created_at) VALUES (?,?,?,?,?,?,?,'draft',?,?,?)""",
                         (key, ver, v["system"], v["user"], v["capability"], v["max_tokens"], v["temperature"],
                          v["note"], admin_id, now_str()))
    return detail(key)


def draft_override(key: str, body: dict = None) -> dict:
    """试运行用：传了 body 就用 body（先校验），否则用已保存的草稿。"""
    if body:
        v = _validate(key, body)
    else:
        with get_conn() as conn:
            r = conn.execute("SELECT * FROM prompt_template WHERE key = ? AND status = 'draft'", (key,)).fetchone()
        if not r:
            raise BadRequest("还没有草稿，请先保存")
        v = {"system": r["system"], "user": r["user_template"], "capability": r["capability"],
             "max_tokens": r["max_tokens"], "temperature": r["temperature"]}
    return {key: {"system": v["system"], "user": v["user"], "capability": v["capability"],
                  "max_tokens": v["max_tokens"], "temperature": v["temperature"], "source": "draft"}}


def publish(key: str, admin_id: int) -> dict:
    with get_conn() as conn:
        draft = conn.execute("SELECT id FROM prompt_template WHERE key = ? AND status = 'draft'", (key,)).fetchone()
        if not draft:
            raise BadRequest("没有可发布的草稿")
        conn.execute("UPDATE prompt_template SET status = 'archived' WHERE key = ? AND status = 'active'", (key,))
        conn.execute("UPDATE prompt_template SET status = 'active', updated_by = ?, created_at = ? WHERE id = ?",
                     (admin_id, now_str(), draft["id"]))
    return detail(key)


def rollback(key: str, version: int, admin_id: int) -> dict:
    """把某个历史版本复制成新的 active 版本。"""
    with get_conn() as conn:
        src = conn.execute("SELECT * FROM prompt_template WHERE key = ? AND version = ?", (key, version)).fetchone()
        if not src:
            raise NotFound("版本不存在")
        conn.execute("DELETE FROM prompt_template WHERE key = ? AND status = 'draft'", (key,))
        conn.execute("UPDATE prompt_template SET status = 'archived' WHERE key = ? AND status = 'active'", (key,))
        ver = conn.execute("SELECT MAX(version) FROM prompt_template WHERE key = ?", (key,)).fetchone()[0] + 1
        conn.execute("""INSERT INTO prompt_template(key, version, system, user_template, capability, max_tokens,
                        temperature, status, note, updated_by, created_at) VALUES (?,?,?,?,?,?,?,'active',?,?,?)""",
                     (key, ver, src["system"], src["user_template"], src["capability"], src["max_tokens"],
                      src["temperature"], f"回滚自 v{version}", admin_id, now_str()))
    return detail(key)


def reset(key: str) -> dict:
    """恢复默认：当前 active 归档、草稿删除，之后用代码默认版。"""
    _default(key)
    with get_conn() as conn:
        conn.execute("DELETE FROM prompt_template WHERE key = ? AND status = 'draft'", (key,))
        conn.execute("UPDATE prompt_template SET status = 'archived' WHERE key = ? AND status = 'active'", (key,))
    return detail(key)


def versions_in_use(keys: list) -> dict:
    return {k: get(k)["version"] for k in keys}


def load_json(s, default):
    return loads(s, default)
