"""标准 Web Push：提醒不依赖网页保持打开；订阅和发送去重均持久化。"""
import asyncio
import base64
import hashlib
import json
import logging
import os
from urllib.parse import urlsplit

from .. import config
from ..db import dumps, get_conn, loads, now_str
from .sessions import BadRequest

log = logging.getLogger("talktool.notifications")
# 仅连接浏览器厂商的推送端点，避免把订阅接口变成任意 URL 请求器。
PUSH_HOSTS = ("fcm.googleapis.com", "push.services.mozilla.com", "push.apple.com", "notify.windows.com")


def _b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _key():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    path = config.DATA_DIR / "webpush-private.pem"
    if not path.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        data = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except FileExistsError:
            pass
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return str(path), _b64(public)


def public_config():
    return {"public_key": _key()[1]}


def subscribe(user_id, subscription):
    endpoint = subscription.get("endpoint", "")
    try:
        u = urlsplit(endpoint)
        host = (u.hostname or "").lower()
        port = u.port
    except (ValueError, TypeError):
        raise BadRequest("通知订阅地址无效")
    if u.scheme != "https" or port not in (None, 443) or u.username or u.password or not any(host == h or host.endswith("." + h) for h in PUSH_HOSTS):
        raise BadRequest("不支持的浏览器推送地址")
    keys = subscription.get("keys") or {}
    try:
        if not all(isinstance(keys.get(k), str) for k in ("p256dh", "auth")):
            raise ValueError()
        public = base64.urlsafe_b64decode(keys["p256dh"] + "=" * (-len(keys["p256dh"]) % 4))
        auth = base64.urlsafe_b64decode(keys["auth"] + "=" * (-len(keys["auth"]) % 4))
        if len(public) != 65 or len(auth) != 16:
            raise ValueError()
        from cryptography.hazmat.primitives.asymmetric import ec
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
    except (ValueError, KeyError, TypeError):
        raise BadRequest("通知订阅密钥无效")
    if len(endpoint) > 2000:
        raise BadRequest("通知订阅地址过长")
    with get_conn() as c:
        # 同一设备切换账号时清理旧账号投递状态，绑定当前登录者。
        existing = c.execute("SELECT id,user_id FROM push_subscription WHERE endpoint=?", (endpoint,)).fetchone()
        if existing and existing["user_id"] != user_id:
            c.execute("DELETE FROM push_delivery WHERE subscription_id=?", (existing["id"],))
        if not existing and c.execute("SELECT COUNT(*) FROM push_subscription WHERE user_id=?", (user_id,)).fetchone()[0] >= 10:
            raise BadRequest("通知设备过多，请先关闭旧设备的提醒")
        c.execute("INSERT INTO push_subscription(user_id,endpoint,subscription,updated_at) VALUES (?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id,subscription=excluded.subscription,updated_at=excluded.updated_at",
                  (user_id, endpoint, dumps({"endpoint": endpoint, "keys": keys}), now_str()))
    return {"ok": True}


def unsubscribe(user_id, endpoint):
    with get_conn() as c:
        c.execute("DELETE FROM push_subscription WHERE user_id=? AND endpoint=?", (user_id, endpoint))
    return {"ok": True}


def reminders(user_id):
    """每件事只安排最新锦囊的一次最近提醒，包含未来事项，供原生本地通知使用。"""
    with get_conn() as c:
        rows = c.execute("""SELECT c.id,c.follow_up_at,p.id AS plan_id,
            (SELECT MIN(remind_at) FROM plan_action a WHERE a.plan_id=p.id AND a.done=0 AND a.remind_at IS NOT NULL) AS action_at
            FROM consult c JOIN plan p ON p.id=(SELECT MAX(id) FROM plan WHERE consult_id=c.id)
            WHERE c.user_id=? AND c.status='planned'""", (user_id,)).fetchall()
    result = []
    for r in rows:
        dates = [v for v in (r["follow_up_at"], r["action_at"] and r["action_at"] + " 09:00:00") if v]
        if not dates:
            continue
        due = min(dates)
        result.append({"consult_id": r["id"], "due_at": due, "key": f"{r['id']}:{r['plan_id']}:{due}"})
    return result


def _send(subscription, reminder):
    from pywebpush import webpush
    path, _ = _key()
    payload = {"title": "智囊跟进提醒", "body": "你有事项需要跟进，打开查看并记录进展。",
               "tag": "talktool-" + hashlib.sha256(reminder["key"].encode()).hexdigest()[:20],
               "url": f"/#/pages/consult/consult?id={reminder['consult_id']}&review=1"}
    webpush(subscription_info=subscription, data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=path, vapid_claims={"sub": config.WEBPUSH_SUBJECT}, ttl=86400, timeout=10)


def send_due():
    from pywebpush import WebPushException
    with get_conn() as c:
        subs = [dict(r) for r in c.execute("SELECT * FROM push_subscription")]
    sent = 0
    cache = {}
    for sub in subs:
        if sub["user_id"] not in cache:
            cache[sub["user_id"]] = reminders(sub["user_id"])
        due = cache[sub["user_id"]]
        for reminder in due:
            if reminder["due_at"] > now_str():
                continue
            with get_conn() as c:
                if c.execute("SELECT 1 FROM push_delivery WHERE subscription_id=? AND reminder_key=?", (sub["id"], reminder["key"])).fetchone():
                    continue
            try:
                _send(loads(sub["subscription"], {}), reminder)
            except WebPushException as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in (404, 410):
                    with get_conn() as c:
                        c.execute("DELETE FROM push_subscription WHERE id=?", (sub["id"],))
                    break
                log.warning("通知暂未送达 subscription=%s status=%s", sub["id"], status)
                break
            except Exception:
                log.exception("通知发送失败 subscription=%s", sub["id"])
                break
            with get_conn() as c:
                c.execute("INSERT OR IGNORE INTO push_delivery VALUES (?,?,?)", (sub["id"], reminder["key"], now_str()))
            sent += 1
    return sent


async def loop():
    while True:
        try:
            await asyncio.to_thread(send_due)
        except Exception:
            log.exception("提醒检查失败")
        await asyncio.sleep(60)
