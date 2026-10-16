"""用量计数：每日限额、登录失败锁定。"""
from ..db import get_conn, now


class QuotaExceeded(Exception):
    pass


def today() -> str:
    return now().strftime("%Y-%m-%d")


def window(minutes: int = 15) -> str:
    t = now()
    return t.strftime("%Y-%m-%d %H:") + f"{t.minute // minutes * minutes:02d}"


def count(subject: str, kind: str, bucket: str = None) -> int:
    with get_conn() as conn:
        r = conn.execute("SELECT count FROM usage_counter WHERE subject = ? AND bucket = ? AND kind = ?",
                         (subject, bucket or today(), kind)).fetchone()
    return r[0] if r else 0


def add(subject: str, kind: str, bucket: str = None, n: int = 1) -> int:
    bucket = bucket or today()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO usage_counter(subject, bucket, kind, count) VALUES (?,?,?,?)
               ON CONFLICT(subject, bucket, kind) DO UPDATE SET count = count + excluded.count""",
            (subject, bucket, kind, n))
        return conn.execute("SELECT count FROM usage_counter WHERE subject = ? AND bucket = ? AND kind = ?",
                            (subject, bucket, kind)).fetchone()[0]


def check(subject: str, kind: str, limit: int, message: str, bucket: str = None) -> None:
    """超过上限抛 QuotaExceeded；limit <= 0 表示不限。"""
    if limit and limit > 0 and count(subject, kind, bucket) >= limit:
        raise QuotaExceeded(message)


def hit(subject: str, kind: str, limit: int, message: str) -> None:
    """检查并计一次（按天）。"""
    check(subject, kind, limit, message)
    add(subject, kind)


def purge(days: int = 7) -> int:
    """删掉旧的计数记录。"""
    from datetime import timedelta
    cutoff = (now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        return conn.execute("DELETE FROM usage_counter WHERE bucket < ?", (cutoff,)).rowcount
