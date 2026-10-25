"""客户端断开不取消生成；请求键、任务状态和结果均保存在 SQLite。"""
import asyncio
import logging
import secrets

from ..db import dumps, get_conn, loads, now_str
from . import consult
from .sessions import BadRequest, NotFound

log = logging.getLogger("talktool.jobs")
_tasks = {}
STAGES = {"create": "正在理解与分派", "plan": "智囊团正在生成锦囊", "message": "正在处理追问与复盘", "roundtable": "谋士正在圆桌讨论"}


def _out(row):
    return {"payload": loads(row["payload"], {}), **{k: row[k] for k in ("id", "kind", "consult_id", "status", "stage", "error", "created_at", "updated_at")}}


def get(user_id, job_id):
    with get_conn() as c:
        row = c.execute("SELECT * FROM generation_job WHERE id=? AND user_id=?", (job_id, user_id)).fetchone()
        if not row:
            raise NotFound("生成任务不存在")
        return _out(row)


def find(user_id, request_key=None, consult_id=None):
    with get_conn() as c:
        if request_key:
            row = c.execute("SELECT * FROM generation_job WHERE user_id=? AND request_key=?", (user_id, request_key)).fetchone()
        elif consult_id:
            consult._get(c, user_id, consult_id)
            row = c.execute("SELECT * FROM generation_job WHERE user_id=? AND consult_id=? ORDER BY rowid DESC LIMIT 1", (user_id, consult_id)).fetchone()
        else:
            return None
        return _out(row) if row else None


def _completed(c, row):
    """进程在结果落库后退出时，恢复结果，不重复提交用户消息或生成版本。"""
    if not row["consult_id"]:
        return False
    last = c.execute("SELECT * FROM consult_message WHERE consult_id=? AND role='advisor' AND id>? ORDER BY id DESC LIMIT 1",
                     (row["consult_id"], row["baseline"])).fetchone()
    if not last or last["kind"] == "error":
        return False
    if row["kind"] == "create":
        return last["kind"] in ("route", "clarify", "safety")
    if row["kind"] == "plan":
        return last["kind"] == "plan"
    if row["kind"] == "roundtable":
        return last["kind"] == "roundtable"
    return last["kind"] in ("reply", "plan", "route", "clarify", "safety")


def recover():
    with get_conn() as c:
        for row in c.execute("SELECT * FROM generation_job WHERE status='running'").fetchall():
            done = _completed(c, row)
            c.execute("UPDATE generation_job SET status=?, stage=?, error=?, updated_at=? WHERE id=?",
                      ("done" if done else "failed", "已完成" if done else "生成已中断",
                       "" if done else "服务重启中断了生成，请查看已有对话后重试。", now_str(), row["id"]))


def submit(user_id, request_key, kind, consult_id=None, payload=None):
    if kind not in STAGES or not isinstance(request_key, str) or not 8 <= len(request_key) <= 100:
        raise BadRequest("任务类型或请求标识不正确")
    payload = dict(payload or {})
    if kind == "create":
        text = str(payload.get("text") or "").strip()
        if not 2 <= len(text) <= 2000:
            raise BadRequest("请用 2–2000 字描述情况")
        payload["text"] = text
        consult_id = None
    elif not consult_id:
        raise BadRequest("缺少问计编号")
    if kind == "message":
        if payload.get("kind", "ask") not in ("ask", "answer", "review", "skip"):
            raise BadRequest("消息类型不正确")
        text = str(payload.get("text") or "").strip()
        if payload.get("kind") != "skip" and not 2 <= len(text) <= 2000:
            raise BadRequest("请输入 2–2000 字的内容")
        payload["text"] = text
    stamp = now_str()
    with get_conn() as c:
        c.execute("BEGIN IMMEDIATE")
        old = c.execute("SELECT * FROM generation_job WHERE user_id=? AND request_key=?", (user_id, request_key)).fetchone()
        if old:
            if old["kind"] != kind or loads(old["payload"], {}) != payload or (kind != "create" and old["consult_id"] != consult_id):
                raise BadRequest("同一个请求标识不能用于不同内容")
            return _out(old)
        baseline = 0
        if consult_id:
            consult._get(c, user_id, consult_id)
            active = c.execute("SELECT * FROM generation_job WHERE consult_id=? AND status IN ('queued','running')", (consult_id,)).fetchone()
            if active:
                raise BadRequest("这次问计已有生成任务，请等待当前任务完成")
            baseline = c.execute("SELECT COALESCE(MAX(id),0) FROM consult_message WHERE consult_id=?", (consult_id,)).fetchone()[0]
        count = c.execute("SELECT COUNT(*) FROM generation_job WHERE user_id=? AND status IN ('queued','running')", (user_id,)).fetchone()[0]
        if count >= 3:
            raise BadRequest("正在处理的问计较多，请稍后再试")
        jid = secrets.token_hex(16)
        c.execute("INSERT INTO generation_job(id,user_id,request_key,kind,consult_id,payload,baseline,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (jid, user_id, request_key, kind, consult_id, dumps(payload), baseline, stamp, stamp))
    return get(user_id, jid)


async def execute(job_id):
    with get_conn() as c:
        row = c.execute("SELECT * FROM generation_job WHERE id=?", (job_id,)).fetchone()
        if not row or row["status"] != "queued":
            return
        c.execute("UPDATE generation_job SET status='running', stage=?, updated_at=? WHERE id=? AND status='queued'",
                  (STAGES[row["kind"]], now_str(), job_id))
    p, uid, cid = loads(row["payload"], {}), row["user_id"], row["consult_id"]
    try:
        if row["kind"] == "create":
            result = await consult.create(uid, p["text"], p.get("council"), p.get("advisors"), job_id=job_id)
        elif row["kind"] == "plan":
            result = await consult.make_plan(uid, cid, p.get("council"))
        elif row["kind"] == "message":
            result = await consult.add_message(uid, cid, p.get("text", ""), p.get("kind", "ask"))
        else:
            result = await consult.roundtable(uid, cid, p.get("topic", ""))
        last = result["messages"][-1] if result["messages"] else {}
        if last.get("kind") == "error" or result["status"] == "failed":
            raise BadRequest(last.get("text") or "生成失败，请重试")
        with get_conn() as c:
            c.execute("UPDATE generation_job SET status='done',stage='已完成',consult_id=?,error='',updated_at=? WHERE id=?",
                      (result["id"], now_str(), job_id))
    except asyncio.CancelledError:
        # 保留 running，启动时识别已写入的结果或明确标记中断。
        raise
    except Exception as exc:
        log.exception("生成任务失败 %s", job_id)
        message = str(exc) if isinstance(exc, (BadRequest, NotFound)) else "生成暂时失败，请查看已有对话后重试。"
        with get_conn() as c:
            c.execute("UPDATE generation_job SET status='failed',stage='生成失败',error=?,updated_at=? WHERE id=?",
                      (message[:300], now_str(), job_id))


async def loop():
    while True:
        capacity = max(0, 4 - len(_tasks))
        with get_conn() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM generation_job WHERE status='queued' ORDER BY rowid LIMIT ?", (capacity,))]
        for jid in ids:
            if jid not in _tasks:
                task = asyncio.create_task(execute(jid))
                _tasks[jid] = task
                task.add_done_callback(lambda _, key=jid: _tasks.pop(key, None))
        await asyncio.sleep(0.5)


async def shutdown():
    for task in list(_tasks.values()):
        task.cancel()
    if _tasks:
        await asyncio.gather(*list(_tasks.values()), return_exceptions=True)
    _tasks.clear()
