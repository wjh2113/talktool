"""账号体系：管理员生成邀请码 → 用户凭邀请码注册 → 用户名密码登录。

- 密码：PBKDF2-SHA256（标准库，无需额外依赖）
- 令牌：随机串，库里只存 SHA-256 哈希，可吊销；默认 30 天有效
- 业务表里的 user_id 统一为 "acc_<账号 id>"
"""
import hashlib
import hmac
import logging
import re
import secrets
from datetime import timedelta

from .. import config
from ..db import get_conn, now, now_str, row_to_dict, TIME_FMT
from . import quota

log = logging.getLogger("talktool")

PBKDF2_ROUNDS = 200_000
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 去掉 0/O/1/I 等易混字符
USERNAME_RE = re.compile(r"^[A-Za-z0-9_一-鿿]{2,20}$")


class AuthError(Exception):
    """登录失效 / 未登录 → 401"""


class Forbidden(Exception):
    """无权限 → 403"""


class InvalidInput(Exception):
    """参数不合法 → 400"""


def account_uid(user_id: int) -> str:
    return f"acc_{user_id}"


# ---------------- 密码 ----------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(calc, digest)
    except (ValueError, AttributeError):
        return False


def _check_username(username: str) -> str:
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise InvalidInput("用户名为 2-20 位字母、数字、下划线或汉字")
    return username


def _check_password(password: str) -> str:
    if not password or len(password) < 6 or len(password) > 64:
        raise InvalidInput("密码长度为 6-64 位")
    return password


# ---------------- 令牌 ----------------

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    exp = (now() + timedelta(days=config.TOKEN_DAYS)).strftime(TIME_FMT)
    conn.execute("INSERT INTO auth_token(token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                 (_hash_token(token), user_id, now_str(), exp))
    return token


def public_user(u: dict) -> dict:
    gender = (u.get("tts_gender") or "male").lower()
    if gender not in ("male", "female"):
        gender = "male"
    return {"id": u["id"], "uid": account_uid(u["id"]), "username": u["username"],
            "nickname": u["nickname"] or u["username"], "role": u["role"], "status": u["status"],
            "tts_gender": gender, "created_at": u["created_at"]}


def user_from_token(token: str) -> dict:
    if not token:
        raise AuthError("请先登录")
    with get_conn() as conn:
        r = conn.execute(
            """SELECT u.* FROM auth_token t JOIN app_user u ON u.id = t.user_id
               WHERE t.token_hash = ? AND t.expires_at > ?""", (_hash_token(token), now_str())).fetchone()
    if not r:
        raise AuthError("登录已过期，请重新登录")
    if r["status"] != "active":
        raise AuthError("账号已被停用，请联系管理员")
    return public_user(row_to_dict(r))


def logout(token: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM auth_token WHERE token_hash = ?", (_hash_token(token or ""),))


# ---------------- 登录 / 注册 ----------------

def _fail_guard(ip: str) -> None:
    if ip:
        quota.check(f"ip:{ip}", "auth_fail", config.LOGIN_FAIL_LIMIT,
                    "尝试次数太多，请 15 分钟后再试", bucket=quota.window(15))


def _record_fail(ip: str) -> None:
    if ip:
        quota.add(f"ip:{ip}", "auth_fail", bucket=quota.window(15))


def login(username: str, password: str, ip: str = None) -> dict:
    _fail_guard(ip)
    with get_conn() as conn:
        u = conn.execute("SELECT * FROM app_user WHERE username = ?", ((username or "").strip(),)).fetchone()
        if not u or not verify_password(password or "", u["password_hash"]):
            _record_fail(ip)
            raise InvalidInput("用户名或密码错误")
        if u["status"] != "active":
            raise InvalidInput("账号已被停用，请联系管理员")
        conn.execute("UPDATE app_user SET last_login_at = ? WHERE id = ?", (now_str(), u["id"]))
        token = issue_token(conn, u["id"])
    return {"token": token, "user": public_user(row_to_dict(u))}


def _claim_legacy_data(conn, legacy_uid: str, new_uid: str) -> int:
    """把注册前这台设备上的匿名训练记录 / 收藏 / 自定义场景归到新账号。"""
    if not legacy_uid or legacy_uid.startswith("acc_") or not re.match(r"^[A-Za-z0-9_\-]{6,64}$", legacy_uid):
        return 0
    n = conn.execute("UPDATE session SET user_id = ? WHERE user_id = ?", (new_uid, legacy_uid)).rowcount
    conn.execute("UPDATE note SET user_id = ? WHERE user_id = ?", (new_uid, legacy_uid))
    conn.execute("UPDATE drill SET owner_id = ? WHERE owner_id = ?", (new_uid, legacy_uid))
    return n


def register(code: str, username: str, password: str, nickname: str = "", legacy_uid: str = None,
             ip: str = None) -> dict:
    _fail_guard(ip)
    username = _check_username(username)
    _check_password(password)
    nickname = (nickname or "").strip()[:20]
    code = (code or "").strip().upper().replace(" ", "")
    try:
        return _do_register(code, username, password, nickname, legacy_uid)
    except _BadCode:
        _record_fail(ip)  # 放在事务外记录，避免和注册事务抢写锁
        raise InvalidInput("邀请码无效、已用完或已过期")


class _BadCode(Exception):
    pass


def _do_register(code, username, password, nickname, legacy_uid) -> dict:
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM app_user WHERE username = ?", (username,)).fetchone():
            raise InvalidInput("用户名已被占用")
        ok = conn.execute(
            """UPDATE invite_code SET used_count = used_count + 1
               WHERE code = ? AND disabled = 0 AND used_count < max_uses
                 AND (expires_at IS NULL OR expires_at > ?)""", (code, now_str())).rowcount
        if not ok:
            raise _BadCode()
        uid = conn.execute(
            """INSERT INTO app_user(username, password_hash, nickname, role, invite_code, created_at, last_login_at)
               VALUES (?,?,?,'user',?,?,?)""",
            (username, hash_password(password), nickname, code, now_str(), now_str())).lastrowid
        claimed = _claim_legacy_data(conn, legacy_uid, account_uid(uid))
        token = issue_token(conn, uid)
        u = row_to_dict(conn.execute("SELECT * FROM app_user WHERE id = ?", (uid,)).fetchone())
    if claimed:
        log.info("新用户 %s 认领了设备 %s 上的 %s 条训练记录", username, legacy_uid, claimed)
    return {"token": token, "user": public_user(u), "claimed_sessions": claimed}


def change_password(user_id: int, old: str, new: str) -> dict:
    _check_password(new)
    with get_conn() as conn:
        u = conn.execute("SELECT password_hash FROM app_user WHERE id = ?", (user_id,)).fetchone()
        if not u or not verify_password(old or "", u["password_hash"]):
            raise InvalidInput("原密码不正确")
        conn.execute("UPDATE app_user SET password_hash = ? WHERE id = ?", (hash_password(new), user_id))
    return {"ok": True}


def update_profile(user_id: int, nickname: str) -> dict:
    with get_conn() as conn:
        conn.execute("UPDATE app_user SET nickname = ? WHERE id = ?", ((nickname or "").strip()[:20], user_id))
        return public_user(row_to_dict(conn.execute("SELECT * FROM app_user WHERE id = ?", (user_id,)).fetchone()))


def update_tts_gender(user_id: int, gender: str) -> dict:
    """示范朗读 / 对练 AI 音色：male 男声 | female 女声。"""
    gender = (gender or "").strip().lower()
    if gender not in ("male", "female"):
        raise InvalidInput("请选择男声或女声")
    with get_conn() as conn:
        conn.execute("UPDATE app_user SET tts_gender = ? WHERE id = ?", (gender, user_id))
        return public_user(row_to_dict(conn.execute("SELECT * FROM app_user WHERE id = ?", (user_id,)).fetchone()))


def tts_gender_of(uid: str) -> str:
    """业务 user_id（acc_N）→ male/female。"""
    if not uid or not str(uid).startswith("acc_"):
        return "male"
    try:
        aid = int(str(uid).split("_", 1)[1])
    except (ValueError, IndexError):
        return "male"
    with get_conn() as conn:
        row = conn.execute("SELECT tts_gender FROM app_user WHERE id = ?", (aid,)).fetchone()
    g = (row["tts_gender"] if row else None) or "male"
    return g if g in ("male", "female") else "male"


# ---------------- 管理员 ----------------

def ensure_admin(username: str, password: str, reset_password: bool = False) -> dict:
    """创建管理员；已存在则提升为管理员（reset_password=True 时同时重置密码）。"""
    username = _check_username(username)
    _check_password(password)
    with get_conn() as conn:
        u = conn.execute("SELECT * FROM app_user WHERE username = ?", (username,)).fetchone()
        if u:
            conn.execute("UPDATE app_user SET role = 'admin', status = 'active' WHERE id = ?", (u["id"],))
            if reset_password:
                conn.execute("UPDATE app_user SET password_hash = ? WHERE id = ?", (hash_password(password), u["id"]))
            uid = u["id"]
        else:
            uid = conn.execute(
                """INSERT INTO app_user(username, password_hash, nickname, role, created_at)
                   VALUES (?,?,?,'admin',?)""", (username, hash_password(password), "管理员", now_str())).lastrowid
        return public_user(row_to_dict(conn.execute("SELECT * FROM app_user WHERE id = ?", (uid,)).fetchone()))


def bootstrap_admin() -> None:
    """启动时：.env 配了 ADMIN_USERNAME/ADMIN_PASSWORD 且该用户不存在 → 创建管理员（不会覆盖已有密码）。"""
    if not (config.ADMIN_USERNAME and config.ADMIN_PASSWORD):
        with get_conn() as conn:
            if not conn.execute("SELECT 1 FROM app_user WHERE role = 'admin'").fetchone():
                log.warning("还没有管理员账号：在 .env 配置 ADMIN_USERNAME / ADMIN_PASSWORD，"
                            "或执行 python3 -m app.admin create-admin <用户名> <密码>")
        return
    with get_conn() as conn:
        exists = conn.execute("SELECT 1 FROM app_user WHERE username = ?", (config.ADMIN_USERNAME,)).fetchone()
    if not exists:
        ensure_admin(config.ADMIN_USERNAME, config.ADMIN_PASSWORD)
        log.info("已创建管理员账号 %s", config.ADMIN_USERNAME)


def require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise Forbidden("需要管理员权限")


def _new_code(conn) -> str:
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not conn.execute("SELECT 1 FROM invite_code WHERE code = ?", (code,)).fetchone():
            return code


def create_invites(admin_id: int, count: int = 1, max_uses: int = 1, expires_days: int = 0,
                   note: str = "") -> list:
    count = max(1, min(50, int(count or 1)))
    max_uses = max(1, min(1000, int(max_uses or 1)))
    expires_days = max(0, min(365, int(expires_days or 0)))
    exp = (now() + timedelta(days=expires_days)).strftime(TIME_FMT) if expires_days else None
    codes = []
    with get_conn() as conn:
        for _ in range(count):
            code = _new_code(conn)
            conn.execute(
                """INSERT INTO invite_code(code, created_by, max_uses, expires_at, note, created_at)
                   VALUES (?,?,?,?,?,?)""", (code, admin_id, max_uses, exp, (note or "").strip()[:50], now_str()))
            codes.append(code)
    return [i for i in list_invites() if i["code"] in codes]


def list_invites(limit: int = 200) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT i.*, (SELECT GROUP_CONCAT(username, '、') FROM app_user u WHERE u.invite_code = i.code) AS used_by
               FROM invite_code i ORDER BY i.created_at DESC, i.rowid DESC LIMIT ?""", (limit,)).fetchall()
    out, ts = [], now_str()
    for r in rows:
        r = row_to_dict(r)
        r["state"] = ("disabled" if r["disabled"] else "used_up" if r["used_count"] >= r["max_uses"]
                      else "expired" if r["expires_at"] and r["expires_at"] <= ts else "active")
        out.append(r)
    return out


def disable_invite(code: str) -> dict:
    with get_conn() as conn:
        n = conn.execute("UPDATE invite_code SET disabled = 1 WHERE code = ?", (code,)).rowcount
    if not n:
        raise InvalidInput("邀请码不存在")
    return {"ok": True}


def list_users(limit: int = 500) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT u.*, (SELECT COUNT(*) FROM session s WHERE s.user_id = 'acc_' || u.id) AS sessions,
                      (SELECT MAX(started_at) FROM session s WHERE s.user_id = 'acc_' || u.id) AS last_session_at
               FROM app_user u ORDER BY u.id DESC LIMIT ?""", (limit,)).fetchall()
    out = []
    for r in rows:
        r = row_to_dict(r)
        item = public_user(r)
        item.update(invite_code=r["invite_code"], last_login_at=r["last_login_at"], sessions=r["sessions"],
                    last_session_at=r["last_session_at"])
        out.append(item)
    return out


def set_user_status(admin_id: int, user_id: int, status: str) -> dict:
    if status not in ("active", "disabled"):
        raise InvalidInput("状态不正确")
    if user_id == admin_id:
        raise InvalidInput("不能停用自己")
    with get_conn() as conn:
        n = conn.execute("UPDATE app_user SET status = ? WHERE id = ?", (status, user_id)).rowcount
        if status == "disabled":
            conn.execute("DELETE FROM auth_token WHERE user_id = ?", (user_id,))  # 立刻踢下线
    if not n:
        raise InvalidInput("用户不存在")
    return {"ok": True}


def reset_user_password(user_id: int) -> dict:
    """管理员重置密码：生成一个临时密码，只显示这一次。"""
    temp = "".join(secrets.choice(CODE_ALPHABET.lower() + "23456789") for _ in range(10))
    with get_conn() as conn:
        n = conn.execute("UPDATE app_user SET password_hash = ? WHERE id = ?", (hash_password(temp), user_id)).rowcount
        conn.execute("DELETE FROM auth_token WHERE user_id = ?", (user_id,))
    if not n:
        raise InvalidInput("用户不存在")
    return {"temp_password": temp}


def purge_tokens() -> int:
    with get_conn() as conn:
        return conn.execute("DELETE FROM auth_token WHERE expires_at <= ?", (now_str(),)).rowcount
