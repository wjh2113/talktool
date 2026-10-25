"""生成持久化、并发去重、重启恢复和通知投递回归。"""
import asyncio
import base64
import os
import sys
import tempfile
import json
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

os.environ.update(DATA_DIR=tempfile.mkdtemp(), GATEWAY_API_KEY="", MOCK_MODE="true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db
from app.services import consult, jobs, notifications, sessions
from app.services.sessions import BadRequest, NotFound


def expect(exc, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc:
        return
    raise AssertionError(f"Expected {exc.__name__}")


async def main():
    db.init_db()
    args = ("u1", "initial-request-1", "create", None, {"text": "王总总在会上否定我的方案，我想争取下季度的项目负责人"})
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: jobs.submit(*args), range(8)))
    assert len({r["id"] for r in results}) == 1
    job = results[0]
    expect(BadRequest, jobs.submit, "u1", "initial-request-1", "create", None, {"text": "另一个问题"})
    await asyncio.gather(jobs.execute(job["id"]), jobs.execute(job["id"]))
    job = jobs.get("u1", job["id"])
    assert job["status"] == "done" and job["consult_id"]
    cid = job["consult_id"]
    expect(NotFound, jobs.get, "u2", job["id"])
    expect(NotFound, jobs.find, "u2", None, cid)
    plan = jobs.submit("u1", "plan-request-1", "plan", cid)
    expect(BadRequest, jobs.submit, "u1", "roundtable-1", "roundtable", cid)
    expect(BadRequest, consult.delete_consult, "u1", cid)
    await jobs.execute(plan["id"])
    assert jobs.get("u1", plan["id"])["status"] == "done"
    assert consult.get_detail("u1", cid)["plan"]["version"] == 1
    # 丢失提交响应后重放旧 key，已完成任务也只返回旧结果。
    again = jobs.submit("u1", "plan-request-1", "plan", cid)
    await jobs.execute(again["id"])
    assert consult.get_detail("u1", cid)["plan"]["version"] == 1
    message = jobs.submit("u1", "message-request-1", "message", cid, {"text": "如果他反驳我，帮我改一下", "kind": "ask"})
    await jobs.execute(message["id"])
    assert consult.get_detail("u1", cid)["plan"]["version"] == 2
    rt = jobs.submit("u1", "roundtable-request-1", "roundtable", cid)
    await jobs.execute(rt["id"])
    assert jobs.get("u1", rt["id"])["status"] == "done"
    await sessions.drain_tasks()

    # 服务在落库后退出：恢复状态而不重复生成版本。
    with db.get_conn() as c:
        c.execute("UPDATE generation_job SET status='running' WHERE id=?", (rt["id"],))
    jobs.recover()
    assert jobs.get("u1", rt["id"])["status"] == "done"
    interrupted = jobs.submit("u1", "interrupted-request", "plan", cid)
    with db.get_conn() as c:
        c.execute("UPDATE generation_job SET status='running' WHERE id=?", (interrupted["id"],))
    jobs.recover()
    assert jobs.get("u1", interrupted["id"])["status"] == "failed"
    assert consult.get_detail("u1", cid)["plan"]["version"] == 2

    # 通知签名 key 稳定，私钥只在测试临时数据目录。
    public = notifications.public_config()["public_key"]
    assert public == notifications.public_config()["public_key"] and len(public) == 87
    b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/test", "keys": {"p256dh": public, "auth": b64(b'b'*16)}}
    expect(BadRequest, notifications.subscribe, "u1", dict(sub, endpoint="http://127.0.0.1/internal"))
    expect(BadRequest, notifications.subscribe, "u1", dict(sub, endpoint="https://fcm.googleapis.com.attacker.test/send"))
    expect(BadRequest, notifications.subscribe, "u1", dict(sub, endpoint="https://fcm.googleapis.com:bad/send"))
    notifications.subscribe("u1", sub)
    with db.get_conn() as c:
        c.execute("UPDATE consult SET follow_up_at='2000-01-01 09:00:00' WHERE id=?", (cid,))
    sent = []
    with patch.object(notifications, "_send", lambda subscription, reminder: sent.append(reminder)):
        assert notifications.send_due() == 1
        assert notifications.send_due() == 0
    assert len(sent) == 1 and sent[0]["consult_id"] == cid
    # 其他账号不能取消订阅；设备切换账号后，不再收到旧账号的提醒。
    notifications.unsubscribe("u2", sub["endpoint"])
    with db.get_conn() as c:
        assert c.execute("SELECT COUNT(*) FROM push_subscription").fetchone()[0] == 1
    notifications.subscribe("u2", sub)
    with patch.object(notifications, "_send", lambda *_: (_ for _ in ()).throw(AssertionError("不应推送旧账号"))):
        assert notifications.send_due() == 0
    notifications.unsubscribe("u2", sub["endpoint"])
    # 真实 VAPID 签名 + Web Push 加密，再以浏览器私钥解密核对；仅替换网络发送。
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    import http_ece
    private = ec.generate_private_key(ec.SECP256R1())
    point = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    secret = os.urandom(16)
    encrypted_sub = dict(sub, keys={"p256dh": b64(point), "auth": b64(secret)})
    captured = {}
    def post(endpoint, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status_code=201, text="", headers={})
    with patch("requests.post", post):
        notifications._send(encrypted_sub, {"consult_id": cid, "key": "encrypted-test"})
    clear = json.loads(http_ece.decrypt(captured["data"], private_key=private, auth_secret=secret, version="aes128gcm"))
    assert clear["title"] == "智囊跟进提醒" and f"id={cid}" in clear["url"]
    assert any(k.lower() == "authorization" for k in captured["headers"])
    print("ALL JOBS AND NOTIFICATIONS TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
