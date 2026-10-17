"""SQLite 访问层：建表、写入种子数据、时间工具。"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config
from .seed_data import CATEGORIES
from .seed_more import merge_into
from .seed_more2 import EXTRA as EXTRA_3
from .frameworks_data import CATEGORIES as FW_CATEGORIES, FRAMEWORKS
from .guides_data import GUIDES

ALL_CATEGORIES = merge_into(merge_into(CATEGORIES), EXTRA_3)

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
TZ = ZoneInfo(config.APP_TIMEZONE)
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def now() -> datetime:
    return datetime.now(TZ).replace(microsecond=0)


def now_str() -> str:
    return now().strftime(TIME_FMT)


def parse_time(s: str) -> datetime:
    return datetime.strptime(s, TIME_FMT).replace(tzinfo=TZ)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")   # 写锁冲突时等待而不是立刻报错
    conn.execute("PRAGMA synchronous = NORMAL")  # WAL 下安全且更快
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row) -> dict:
    return dict(row) if row is not None else None


SYSTEM_CATEGORY = "我的场景"
SYSTEM_SCENARIO = "自定义场景"

# 已部署的旧库升级用：(表, 列, 定义)
MIGRATIONS = [
    ("category", "is_system", "INTEGER NOT NULL DEFAULT 0"),
    ("drill", "owner_id", "TEXT"),
    ("drill", "sample_script", "TEXT NOT NULL DEFAULT ''"),
    ("session", "metrics", "TEXT NOT NULL DEFAULT '{}'"),
    ("report", "turn_reviews", "TEXT NOT NULL DEFAULT '[]'"),
    ("session", "ip", "TEXT"),
    ("session", "report_status", "TEXT NOT NULL DEFAULT 'none'"),
    ("drill", "pitfalls", "TEXT NOT NULL DEFAULT '[]'"),
    ("app_user", "tts_gender", "TEXT NOT NULL DEFAULT 'male'"),  # male | female
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, col, ddl in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_drill_owner ON drill(owner_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session_ip ON session(ip, started_at)")


def system_scenario_id(conn: sqlite3.Connection) -> int:
    """“我的场景 / 自定义场景”：用户自定义训练挂在这里，不在场景页展示。"""
    row = conn.execute("SELECT id FROM category WHERE name = ?", (SYSTEM_CATEGORY,)).fetchone()
    cid = row[0] if row else conn.execute(
        "INSERT INTO category(name, sort_order, is_system) VALUES (?, 999, 1)", (SYSTEM_CATEGORY,)).lastrowid
    row = conn.execute("SELECT id FROM scenario WHERE category_id = ? AND title = ?", (cid, SYSTEM_SCENARIO)).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO scenario(category_id, title, subtitle, sort_order) VALUES (?,?,?,0)",
        (cid, SYSTEM_SCENARIO, "描述你的真实情况，AI 帮你生成专属训练")).lastrowid


def init_db(reseed: bool = False) -> None:
    """建表 + 旧库升级 + 增量补充内置场景（reseed=True 时先清空公共场景）。"""
    with get_conn() as conn:
        # WAL：读写互不阻塞，多个请求同时访问更稳（设置一次会持久保存在库文件里）
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate(conn)
        empty = conn.execute("SELECT COUNT(*) FROM category WHERE is_system = 0").fetchone()[0] == 0
        if reseed and not empty:
            used = conn.execute(
                "SELECT COUNT(*) FROM session s JOIN drill d ON d.id = s.drill_id WHERE d.owner_id IS NULL"
            ).fetchone()[0]
            if used:
                raise SystemExit(f"已有 {used} 条训练记录引用公共场景，不能整体重置。请直接在数据库中修改场景内容。")
            conn.execute("DELETE FROM drill WHERE owner_id IS NULL")
            conn.execute("DELETE FROM scenario WHERE category_id IN (SELECT id FROM category WHERE is_system = 0)")
            conn.execute("DELETE FROM category WHERE is_system = 0")
            empty = True
        added = _sync_seed(conn)
        _sync_frameworks(conn)
        if added and not empty:
            import logging
            logging.getLogger("talktool").info("已补充 %s 个内置训练场景", added)
        system_scenario_id(conn)


def _sync_seed(conn: sqlite3.Connection) -> int:
    """按名称/标题增量写入内置内容：缺什么补什么，不改动、不删除已有数据。返回新增训练数。"""
    added = 0
    for ci, cat in enumerate(ALL_CATEGORIES):
        row = conn.execute("SELECT id FROM category WHERE name = ? AND is_system = 0", (cat["name"],)).fetchone()
        cid = row[0] if row else conn.execute(
            "INSERT INTO category(name, sort_order) VALUES (?, ?)", (cat["name"], ci)).lastrowid
        for si, sc in enumerate(cat["scenarios"]):
            row = conn.execute("SELECT id FROM scenario WHERE category_id = ? AND title = ?",
                               (cid, sc["title"])).fetchone()
            sid = row[0] if row else conn.execute(
                "INSERT INTO scenario(category_id, title, subtitle, sort_order) VALUES (?,?,?,?)",
                (cid, sc["title"], sc.get("subtitle", ""), si)).lastrowid
            for di, d in enumerate(sc["drills"]):
                if conn.execute("SELECT 1 FROM drill WHERE scenario_id = ? AND title = ? AND owner_id IS NULL",
                                (sid, d["title"])).fetchone():
                    continue
                conn.execute(
                    """INSERT INTO drill(scenario_id, title, description, cover_image, pressure_level,
                       duration_min, mode, ai_role, user_role, training_goal, opening_line,
                       system_prompt, status, sort_order)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sid, d["title"], d["description"], d.get("cover_image", ""), d["pressure"],
                     d["duration_min"], "纯语音", d["ai_role"], d["user_role"], d["training_goal"],
                     d.get("opening_line", ""), d.get("system_prompt", ""), "online", di),
                )
                added += 1
    return added


def _sync_frameworks(conn: sqlite3.Connection) -> None:
    """表达框架按 code 写入/更新；内置训练按标题关联推荐框架和常见误区（每次启动覆盖为代码里的版本）。"""
    order = {c: i for i, c in enumerate(FW_CATEGORIES)}
    for i, f in enumerate(FRAMEWORKS):
        vals = (f["name"], f["category"], f["summary"], json.dumps(f["steps"], ensure_ascii=False),
                f.get("when_to_use", ""), f.get("example", ""), json.dumps(f.get("pitfalls", []), ensure_ascii=False),
                json.dumps(f.get("tips", []), ensure_ascii=False), f.get("detail", ""), f.get("source", ""),
                order.get(f["category"], 99) * 1000 + i)
        if conn.execute("SELECT 1 FROM framework WHERE code = ?", (f["code"],)).fetchone():
            conn.execute("""UPDATE framework SET name=?, category=?, summary=?, steps=?, when_to_use=?, example=?,
                            pitfalls=?, tips=?, detail=?, source=?, sort_order=? WHERE code=?""", vals + (f["code"],))
        else:
            conn.execute("""INSERT INTO framework(name, category, summary, steps, when_to_use, example, pitfalls, tips,
                            detail, source, sort_order, code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", vals + (f["code"],))
    ids = {r[0]: r[1] for r in conn.execute("SELECT code, id FROM framework")}
    guides = dict(GUIDES)
    for cat in ALL_CATEGORIES:
        for sc in cat["scenarios"]:
            for d in sc["drills"]:
                if d.get("guide"):
                    guides[d["title"]] = d["guide"]
    for title, g in guides.items():
        for (drill_id,) in conn.execute("SELECT id FROM drill WHERE title = ? AND owner_id IS NULL", (title,)).fetchall():
            set_drill_guide(conn, drill_id, g.get("frameworks", []), g.get("pitfalls", []), ids)


def set_drill_guide(conn, drill_id: int, frameworks: list, pitfalls: list, ids: dict = None) -> None:
    """frameworks: [(code, 本场景示例)]；未知 code 会被忽略。"""
    if ids is None:
        ids = {r[0]: r[1] for r in conn.execute("SELECT code, id FROM framework")}
    conn.execute("DELETE FROM drill_framework WHERE drill_id = ?", (drill_id,))
    for i, item in enumerate(frameworks):
        code, example = (item[0], item[1]) if isinstance(item, (list, tuple)) else (item.get("code"), item.get("example", ""))
        if code in ids:
            conn.execute("INSERT OR IGNORE INTO drill_framework(drill_id, framework_id, example, sort_order) VALUES (?,?,?,?)",
                         (drill_id, ids[code], example or "", i))
    conn.execute("UPDATE drill SET pitfalls = ? WHERE id = ?", (json.dumps(pitfalls or [], ensure_ascii=False), drill_id))


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(s, default=None):
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    import sys
    init_db(reseed="--reseed" in sys.argv)
    print(f"数据库已就绪：{config.DB_PATH}")
