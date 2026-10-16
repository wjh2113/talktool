"""SQLite 访问层：建表、写入种子数据、时间工具。"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config
from .seed_data import CATEGORIES

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
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, col, ddl in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_drill_owner ON drill(owner_id)")


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
    """建表 + 旧库升级；公共分类为空（或 reseed=True）时写入种子数据。"""
    with get_conn() as conn:
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
        if empty:
            _seed(conn)
        system_scenario_id(conn)


def _seed(conn: sqlite3.Connection) -> None:
    for ci, cat in enumerate(CATEGORIES):
        cid = conn.execute(
            "INSERT INTO category(name, sort_order) VALUES (?, ?)", (cat["name"], ci)
        ).lastrowid
        for si, sc in enumerate(cat["scenarios"]):
            sid = conn.execute(
                "INSERT INTO scenario(category_id, title, subtitle, sort_order) VALUES (?,?,?,?)",
                (cid, sc["title"], sc["subtitle"], si),
            ).lastrowid
            for di, d in enumerate(sc["drills"]):
                conn.execute(
                    """INSERT INTO drill(scenario_id, title, description, cover_image, pressure_level,
                       duration_min, mode, ai_role, user_role, training_goal, opening_line,
                       system_prompt, status, sort_order)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sid, d["title"], d["description"], d.get("cover_image", ""), d["pressure"],
                     d["duration_min"], "纯语音", d["ai_role"], d["user_role"], d["training_goal"],
                     d.get("opening_line", ""), d.get("system_prompt", ""), "online", di),
                )


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
