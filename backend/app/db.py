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


def init_db(reseed: bool = False) -> None:
    """建表；分类表为空（或 reseed=True）时写入种子数据。"""
    with get_conn() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        empty = conn.execute("SELECT COUNT(*) FROM category").fetchone()[0] == 0
        if reseed and not empty:
            conn.execute("DELETE FROM drill")
            conn.execute("DELETE FROM scenario")
            conn.execute("DELETE FROM category")
            empty = True
        if empty:
            _seed(conn)


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
