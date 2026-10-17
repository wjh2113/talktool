"""表达框架库：列表 / 详情 / 场景关联。"""
from ..db import get_conn, loads, row_to_dict
from ..frameworks_data import CATEGORIES
from .sessions import NotFound

JSON_FIELDS = (("steps", []), ("pitfalls", []), ("tips", []))


def _fw(row) -> dict:
    f = row_to_dict(row)
    for k, default in JSON_FIELDS:
        if k in f:
            f[k] = loads(f[k], default)
    return f


def list_frameworks(category: str = None, q: str = None) -> dict:
    where, params = [], []
    if category:
        where.append("category = ?")
        params.append(category)
    if q:
        like = f"%{q.strip()}%"
        where.append("(name LIKE ? OR summary LIKE ? OR when_to_use LIKE ? OR code LIKE ?)")
        params += [like, like, like, like]
    sql = f"""SELECT f.id, f.code, f.name, f.category, f.summary, f.steps, f.when_to_use, f.source,
                     (SELECT COUNT(*) FROM drill_framework df JOIN drill d ON d.id = df.drill_id
                       WHERE df.framework_id = f.id AND d.owner_id IS NULL AND d.status = 'online') AS drill_count
              FROM framework f {'WHERE ' + ' AND '.join(where) if where else ''}
              ORDER BY f.sort_order, f.id"""
    with get_conn() as conn:
        items = [_fw(r) for r in conn.execute(sql, params)]
        counts = {r[0]: r[1] for r in conn.execute("SELECT category, COUNT(*) FROM framework GROUP BY category")}
    cats = [{"name": c, "count": counts.get(c, 0)} for c in CATEGORIES if counts.get(c)]
    return {"categories": cats, "items": items, "total": len(items)}


def get_framework(key: str, user_id: str = None) -> dict:
    """key 可以是 code 或数字 id。附带：用到这个框架的训练（含该场景的示例说法）。"""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM framework WHERE code = ? OR CAST(id AS TEXT) = ?", (key, str(key))).fetchone()
        if not row:
            raise NotFound("框架不存在")
        f = _fw(row)
        drills = conn.execute(
            """SELECT d.id, d.title, d.pressure_level, d.duration_min, s.title AS scenario_title,
                      c.name AS category_name, df.example
               FROM drill_framework df JOIN drill d ON d.id = df.drill_id
               JOIN scenario s ON s.id = d.scenario_id JOIN category c ON c.id = s.category_id
               WHERE df.framework_id = ? AND d.status = 'online'
                 AND (d.owner_id IS NULL OR d.owner_id = ?)
               ORDER BY d.owner_id IS NOT NULL, c.sort_order, s.sort_order, d.sort_order""",
            (f["id"], user_id or "")).fetchall()
    f["drills"] = [row_to_dict(d) for d in drills]
    return f


def drill_guide(conn, drill_id: int) -> list:
    """某个训练推荐的表达框架（按推荐顺序），每个带本场景示例。"""
    rows = conn.execute(
        """SELECT f.id, f.code, f.name, f.category, f.summary, f.steps, df.example AS scene_example
           FROM drill_framework df JOIN framework f ON f.id = df.framework_id
           WHERE df.drill_id = ? ORDER BY df.sort_order""", (drill_id,)).fetchall()
    return [_fw(r) for r in rows]


def guide_text(conn, drill_id: int) -> str:
    """给报告/复盘 Prompt 用：推荐框架的简短文字描述。"""
    parts = []
    for f in drill_guide(conn, drill_id):
        steps = "-".join(s["name"] for s in f["steps"])
        parts.append(f"{f['name']}（{steps}）")
    return "；".join(parts)
