"""FastAPI 入口。启动：uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"""
import asyncio
import logging
import json
import time
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .db import init_db
from .services import auth, catalog_import, frameworks, library, maintenance, practice
from .services import jobs, notifications
from .services import advisor_admin, advisor_stats, consult, memory, my_advisors, prompt_store, strategies, workflow
from .services import sessions as svc
from .services.gateway import GatewayError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("talktool")

app = FastAPI(title="TalkTool · AI 沟通训练", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
# 开发环境由后端提供音频；生产环境 nginx 直接读 data/audio（见 deploy/nginx-talktool.conf）
app.mount("/media/audio", StaticFiles(directory=str(config.AUDIO_DIR)), name="audio")

_bg = set()


@app.on_event("startup")
async def _startup():
    init_db()
    auth.bootstrap_admin()
    jobs.recover()
    for work in (jobs.loop(), notifications.loop()):
        _bg.add(asyncio.create_task(work))
    n = svc.recover_pending_reports()
    if n:
        log.info("有 %s 份报告在上次重启时中断，已标记为失败，可在报告页重新生成", n)
    t = asyncio.get_running_loop().create_task(maintenance.loop())
    _bg.add(t)
    mode = "MOCK（未配置 GATEWAY_API_KEY）" if config.MOCK else f"网关 {config.GATEWAY_BASE_URL}"
    log.info("TalkTool 启动，语音模式：%s", mode)


@app.on_event("shutdown")
async def _shutdown():
    for task in _bg:
        task.cancel()
    await asyncio.gather(*_bg, return_exceptions=True)
    _bg.clear()
    await jobs.shutdown()


class JobIn(BaseModel):
    request_key: str
    kind: str
    consult_id: Optional[int] = None
    payload: dict = {}



def _err(status):
    async def handler(_, e):
        return JSONResponse({"detail": str(e)}, status_code=status)
    return handler


for exc, code in ((svc.NotFound, 404), (svc.BadRequest, 400), (svc.TooMany, 429), (GatewayError, 502),
                  (auth.AuthError, 401), (auth.Forbidden, 403), (auth.InvalidInput, 400)):
    app.add_exception_handler(exc, _err(code))


# ---------------- 鉴权 ----------------

def _token(authorization: Optional[str]) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    return auth.user_from_token(_token(authorization))


def admin_user(user: dict = Depends(current_user)) -> dict:
    auth.require_admin(user)
    return user


def client_ip(request: Request) -> Optional[str]:
    # nginx 反代 + uvicorn --proxy-headers 时，client.host 就是真实 IP
    return request.client.host if request.client else None


@app.post("/api/advisor/jobs", status_code=202)
def advisor_submit_job(body: JobIn, user: dict = Depends(current_user)):
    return jobs.submit(user["uid"], body.request_key, body.kind, body.consult_id, body.payload)


@app.get("/api/advisor/jobs/find")
def advisor_find_job(request_key: Optional[str] = None, consult_id: Optional[int] = None, user: dict = Depends(current_user)):
    return jobs.find(user["uid"], request_key, consult_id)


@app.get("/api/advisor/jobs/{job_id}")
def advisor_job(job_id: str, user: dict = Depends(current_user)):
    return jobs.get(user["uid"], job_id)


@app.get("/api/advisor/jobs/{job_id}/events")
async def advisor_job_events(job_id: str, after: int = Query(0, ge=0), wait: int = Query(0, ge=0, le=15000),
                             user: dict = Depends(current_user)):
    deadline = time.monotonic() + wait / 1000
    while True:
        batch = jobs.events(user["uid"], job_id, after)
        if batch["events"] or batch["terminal"] or time.monotonic() >= deadline:
            return batch
        await asyncio.sleep(0.1)


@app.get("/api/advisor/jobs/{job_id}/stream")
async def advisor_job_stream(job_id: str, request: Request, after: int = Query(0, ge=0),
                              user: dict = Depends(current_user)):
    jobs.get(user["uid"], job_id)  # 发响应头前校验归属，不把令牌放进 URL。

    async def output():
        cursor = after
        heartbeat = time.monotonic()
        while not await request.is_disconnected():
            batch = jobs.events(user["uid"], job_id, cursor)
            for event in batch["events"]:
                cursor = event["id"]
                yield f"id: {cursor}\nevent: update\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            if batch["terminal"]:
                yield f"event: terminal\ndata: {json.dumps({'cursor': cursor, 'status': batch['status']})}\n\n"
                return
            if time.monotonic() - heartbeat >= 10:
                yield ": keepalive\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(0.1)

    return StreamingResponse(output(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


class SubscriptionIn(BaseModel):
    endpoint: str
    keys: dict = {}


@app.get("/api/notifications/config")
def notification_config(user: dict = Depends(current_user)):
    return notifications.public_config()


@app.post("/api/notifications/subscribe")
def notification_subscribe(body: SubscriptionIn, user: dict = Depends(current_user)):
    return notifications.subscribe(user["uid"], body.dict())


@app.post("/api/notifications/unsubscribe")
def notification_unsubscribe(body: SubscriptionIn, user: dict = Depends(current_user)):
    return notifications.unsubscribe(user["uid"], body.endpoint)


@app.get("/api/notifications/reminders")
def notification_reminders(user: dict = Depends(current_user)):
    return notifications.reminders(user["uid"])


# ---------------- 基础 ----------------

@app.get("/api/health")
def health():
    return {"ok": True, "mock": config.MOCK, "provider": config.VOICE_PROVIDER,
            "min_duration_sec": config.MIN_DURATION_SEC}


@app.get("/api/ping")
def ping():
    return {"pong": True}


# ---------------- 账号 ----------------

class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    invite_code: str
    username: str
    password: str
    nickname: str = ""
    device_id: Optional[str] = None  # 注册前在这台设备上的匿名记录会归到新账号


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


class ProfileIn(BaseModel):
    nickname: str


class TtsGenderIn(BaseModel):
    tts_gender: str  # male | female


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    return auth.login(body.username, body.password, client_ip(request))


@app.post("/api/auth/register")
def register(body: RegisterIn, request: Request):
    return auth.register(body.invite_code, body.username, body.password, body.nickname, body.device_id,
                         client_ip(request))


@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(None)):
    auth.logout(_token(authorization))
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return user


@app.post("/api/auth/password")
def change_password(body: PasswordIn, user: dict = Depends(current_user)):
    return auth.change_password(user["id"], body.old_password, body.new_password)


@app.put("/api/auth/profile")
def update_profile(body: ProfileIn, user: dict = Depends(current_user)):
    return auth.update_profile(user["id"], body.nickname)


@app.put("/api/auth/tts-gender")
def update_tts_gender(body: TtsGenderIn, user: dict = Depends(current_user)):
    return auth.update_tts_gender(user["id"], body.tts_gender)


# ---------------- 管理员 ----------------

class InviteIn(BaseModel):
    count: int = 1
    max_uses: int = 1
    expires_days: int = 0
    note: str = ""


class StatusIn(BaseModel):
    status: str  # active | disabled


@app.get("/api/admin/invites")
def admin_invites(admin: dict = Depends(admin_user)):
    return auth.list_invites()


@app.post("/api/admin/invites")
def admin_create_invites(body: InviteIn, admin: dict = Depends(admin_user)):
    return auth.create_invites(admin["id"], body.count, body.max_uses, body.expires_days, body.note)


@app.post("/api/admin/invites/{code}/disable")
def admin_disable_invite(code: str, admin: dict = Depends(admin_user)):
    return auth.disable_invite(code)


@app.get("/api/admin/users")
def admin_users(admin: dict = Depends(admin_user)):
    return auth.list_users()


@app.post("/api/admin/users/{user_id}/status")
def admin_user_status(user_id: int, body: StatusIn, admin: dict = Depends(admin_user)):
    return auth.set_user_status(admin["id"], user_id, body.status)


@app.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_password(user_id: int, admin: dict = Depends(admin_user)):
    return auth.reset_user_password(user_id)


@app.post("/api/admin/catalog/import")
async def admin_catalog_import(
    file: UploadFile = File(...),
    mode: str = Form("upsert"),
    admin: dict = Depends(admin_user),
):
    """导入场景库 / 表达框架：.md 或 .zip（内含多个 md）。mode=upsert|add_only。"""
    data = await file.read()
    return catalog_import.import_bytes(data, file.filename or "upload.md", mode=mode)


# ---------------- 内容 ----------------

@app.get("/api/categories")
def categories(user: dict = Depends(current_user)):
    return svc.list_categories()


@app.get("/api/scenarios/{scenario_id}")
def scenario(scenario_id: int, user: dict = Depends(current_user)):
    return svc.get_scenario(scenario_id)


@app.get("/api/drills/{drill_id}")
def drill(drill_id: int, user: dict = Depends(current_user)):
    return svc.get_drill(drill_id, user["uid"])


@app.get("/api/drills/{drill_id}/script")
async def drill_script(drill_id: int, user: dict = Depends(current_user)):
    """跟读模式：场景示范稿"""
    return await practice.drill_script(user["uid"], drill_id)


# ---------------- 表达框架库 ----------------

@app.get("/api/frameworks")
def framework_list(category: Optional[str] = None, q: Optional[str] = None, user: dict = Depends(current_user)):
    return frameworks.list_frameworks(category, q)


@app.get("/api/frameworks/{key}")
def framework_detail(key: str, user: dict = Depends(current_user)):
    return frameworks.get_framework(key, user["uid"])


# ---------------- 训练会话 ----------------

class StartIn(BaseModel):
    drill_id: int


class EndIn(BaseModel):
    reason: str = "finish"  # finish | exit


@app.post("/api/sessions")
async def start(body: StartIn, request: Request, user: dict = Depends(current_user)):
    return await svc.start_session(user["uid"], body.drill_id, client_ip(request))


@app.post("/api/sessions/{session_id}/turn")
async def turn(session_id: int,
               audio: UploadFile = File(...),
               format: str = Form("wav"),
               sample_rate: int = Form(16000),
               user: dict = Depends(current_user)):
    data = await audio.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "音频过大")
    return await svc.run_turn(user["uid"], session_id, data, format, sample_rate)


@app.post("/api/sessions/{session_id}/end")
async def end(session_id: int, body: EndIn = None, user: dict = Depends(current_user)):
    reason = (body.reason if body else "finish")
    if reason not in ("finish", "exit"):
        raise HTTPException(400, "reason 只能是 finish 或 exit")
    return await svc.end_session(user["uid"], session_id, reason)


@app.post("/api/sessions/{session_id}/turn-reviews")
async def turn_reviews(session_id: int, user: dict = Depends(current_user)):
    """逐句复盘：报告里展开时才生成（已生成则直接返回）"""
    return await svc.get_turn_reviews(user["uid"], session_id)


@app.post("/api/sessions/{session_id}/report/retry")
async def retry(session_id: int, user: dict = Depends(current_user)):
    return await svc.retry_report(user["uid"], session_id)


@app.get("/api/sessions")
def records(range: str = Query("all", pattern="^(all|week|month)$"),
            page: int = 1, page_size: int = 20, user: dict = Depends(current_user)):
    return svc.list_sessions(user["uid"], range, page, page_size)


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: int, user: dict = Depends(current_user)):
    return svc.get_session_detail(user["uid"], session_id)


# ---------------- 跟读 / 示范朗读 ----------------

class TtsIn(BaseModel):
    text: str
    preview: bool = False  # 设置页试听固定文案


@app.post("/api/tts")
async def tts(body: TtsIn, user: dict = Depends(current_user)):
    text = body.text
    preview = bool(body.preview)
    if preview:
        text = config.TTS_PREVIEW_TEXT
    return await svc.tts(text, user["uid"], preview=preview)


@app.post("/api/pronounce")
async def pronounce(audio: UploadFile = File(...),
                    text: str = Form(...),
                    format: str = Form("wav"),
                    sample_rate: int = Form(16000),
                    note_id: Optional[int] = Form(None),
                    user: dict = Depends(current_user)):
    data = await audio.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "音频过大")
    return await practice.pronounce(user["uid"], data, format, sample_rate, text, note_id)


# ---------------- 练习本 ----------------

class NoteIn(BaseModel):
    kind: str = "phrase"   # phrase 话术 | tip 建议 | script 示范稿
    text: str
    source_text: str = ""
    drill_id: Optional[int] = None
    session_id: Optional[int] = None


@app.get("/api/notes")
def notes(kind: str = None, user: dict = Depends(current_user)):
    return library.list_notes(user["uid"], kind)


@app.post("/api/notes")
def add_note(body: NoteIn, user: dict = Depends(current_user)):
    return library.add_note(user["uid"], body.kind, body.text, body.source_text, body.drill_id, body.session_id)


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int, user: dict = Depends(current_user)):
    return library.delete_note(user["uid"], note_id)


# ---------------- 自定义场景 ----------------

class CustomIn(BaseModel):
    description: str
    pressure_level: str = "中压"


@app.get("/api/custom-drills")
def custom_drills(user: dict = Depends(current_user)):
    return library.list_custom_drills(user["uid"])


@app.post("/api/custom-drills")
async def create_custom(body: CustomIn, user: dict = Depends(current_user)):
    return await library.create_custom_drill(user["uid"], body.description, body.pressure_level)


@app.delete("/api/custom-drills/{drill_id}")
def delete_custom(drill_id: int, user: dict = Depends(current_user)):
    return library.delete_custom_drill(user["uid"], drill_id)


@app.get("/api/stats")
def stats(user: dict = Depends(current_user)):
    return svc.get_stats(user["uid"])



# ---------------- AI 智囊团 ----------------

@app.post("/api/transcribe")
async def transcribe_audio(audio: UploadFile = File(...), format: str = Form("wav"), sample_rate: int = Form(16000),
                           user: dict = Depends(current_user)):
    """语音输入：转成文字，前端放进输入框让用户确认后再发。"""
    data = await audio.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "音频过大")
    return {"text": await consult.resolve_text("", data, format, sample_rate)}


@app.get("/api/advisor/home")
def advisor_home(user: dict = Depends(current_user)):
    return {"councils": workflow.councils(), "ongoing": consult.ongoing_cases(user["uid"]),
            "consults": consult.list_consults(user["uid"], 20), "memory_paused": memory.is_paused(user["uid"]),
            "due": consult.due_followups(user["uid"]), "my_advisors": my_advisors.list_mine(user["uid"])}


@app.get("/api/advisor/due")
def advisor_due(user: dict = Depends(current_user)):
    """首页 / 底栏角标用：有几件事该跟进了。"""
    items = consult.due_followups(user["uid"])
    return {"count": len(items), "items": items}


@app.get("/api/councils")
def council_list(user: dict = Depends(current_user)):
    return workflow.councils()


@app.get("/api/strategies")
def strategy_list(school: Optional[str] = None, domain: Optional[str] = None, q: Optional[str] = None,
                  user: dict = Depends(current_user)):
    return strategies.list_strategies(school, domain, q)


@app.get("/api/strategies/{code}")
def strategy_detail(code: str, user: dict = Depends(current_user)):
    return strategies.get_strategy(code)


class ConsultIn(BaseModel):
    text: str
    council: Optional[str] = None
    advisors: Optional[list] = None   # 列席的私人谋士 code


class ConsultMsgIn(BaseModel):
    text: str = ""
    kind: str = "ask"   # answer | ask | review | skip


class PlanIn(BaseModel):
    council: Optional[str] = None


class ActionIn(BaseModel):
    done: Optional[bool] = None
    result: Optional[str] = None
    remind_at: Optional[str] = None   # YYYY-MM-DD；空字符串 = 取消提醒


class RoundtableIn(BaseModel):
    topic: str = ""


class ExtraAdvisorsIn(BaseModel):
    codes: list = []


class SnoozeIn(BaseModel):
    days: int = 2


class RatingIn(BaseModel):
    rating: int          # 1 有用 / -1 没用 / 0 撤销
    reason: str = ""


class MyAdvisorIn(BaseModel):
    name: str
    avatar: str = ""
    persona: str = ""
    style: str = ""
    schools: list = []


@app.post("/api/consults")
async def consult_create(body: ConsultIn, user: dict = Depends(current_user)):
    text = await consult.resolve_text(body.text)
    return await consult.create(user["uid"], text, body.council, body.advisors)


@app.get("/api/consults")
def consult_list(user: dict = Depends(current_user)):
    return consult.list_consults(user["uid"])


@app.get("/api/consults/{consult_id}")
def consult_detail(consult_id: int, version: Optional[int] = None, user: dict = Depends(current_user)):
    return consult.get_detail(user["uid"], consult_id, version)


@app.post("/api/consults/{consult_id}/messages")
async def consult_message(consult_id: int, body: ConsultMsgIn, user: dict = Depends(current_user)):
    text = "" if body.kind == "skip" else await consult.resolve_text(body.text)
    return await consult.add_message(user["uid"], consult_id, text, body.kind)


@app.post("/api/consults/{consult_id}/plan")
async def consult_plan(consult_id: int, body: PlanIn = None, user: dict = Depends(current_user)):
    return await consult.make_plan(user["uid"], consult_id, body.council if body else None)


@app.post("/api/consults/{consult_id}/rehearse")
def consult_rehearse(consult_id: int, user: dict = Depends(current_user)):
    return consult.rehearse(user["uid"], consult_id)


@app.delete("/api/consults/{consult_id}")
def consult_delete(consult_id: int, user: dict = Depends(current_user)):
    return consult.delete_consult(user["uid"], consult_id)


@app.post("/api/consults/{consult_id}/roundtable")
async def consult_roundtable(consult_id: int, body: RoundtableIn = None, user: dict = Depends(current_user)):
    return await consult.roundtable(user["uid"], consult_id, body.topic if body else "")


@app.put("/api/consults/{consult_id}/advisors")
def consult_extra_advisors(consult_id: int, body: ExtraAdvisorsIn, user: dict = Depends(current_user)):
    return consult.set_extra_advisors(user["uid"], consult_id, body.codes)


@app.post("/api/consults/{consult_id}/snooze")
def consult_snooze(consult_id: int, body: SnoozeIn = None, user: dict = Depends(current_user)):
    return consult.snooze(user["uid"], consult_id, body.days if body else 2)


@app.post("/api/consults/{consult_id}/stop-follow")
def consult_stop_follow(consult_id: int, user: dict = Depends(current_user)):
    return consult.stop_follow(user["uid"], consult_id)


@app.put("/api/plans/{plan_id}/rating")
def plan_rating(plan_id: int, body: RatingIn, user: dict = Depends(current_user)):
    return consult.rate_plan(user["uid"], plan_id, body.rating, body.reason)


@app.put("/api/plan-actions/{action_id}")
def plan_action(action_id: int, body: ActionIn, user: dict = Depends(current_user)):
    return consult.update_action(user["uid"], action_id, body.done, body.result, body.remind_at)


# ---- 私人谋士 ----

@app.get("/api/my-advisors")
def my_advisor_list(user: dict = Depends(current_user)):
    return {"items": my_advisors.list_mine(user["uid"]), "templates": my_advisors.TEMPLATES,
            "styles": my_advisors.STYLES, "max": my_advisors.MAX_PER_USER,
            "schools": [{"code": x["code"], "name": x["name"]} for x in strategies.schools()]}


@app.post("/api/my-advisors")
def my_advisor_create(body: MyAdvisorIn, user: dict = Depends(current_user)):
    return my_advisors.create(user["uid"], body.dict())


@app.put("/api/my-advisors/{code}")
def my_advisor_update(code: str, body: MyAdvisorIn, user: dict = Depends(current_user)):
    return my_advisors.update(user["uid"], code, body.dict())


@app.delete("/api/my-advisors/{code}")
def my_advisor_delete(code: str, user: dict = Depends(current_user)):
    return my_advisors.delete(user["uid"], code)


# ---- 长期记忆 ----

class MemTextIn(BaseModel):
    text: Optional[str] = None
    pinned: Optional[bool] = None


class SubjectIn(BaseModel):
    name: Optional[str] = None
    aliases: Optional[list] = None
    summary: Optional[str] = None
    status: Optional[str] = None


class MergeIn(BaseModel):
    into: int


class PauseIn(BaseModel):
    paused: bool


@app.get("/api/memory")
def memory_overview(user: dict = Depends(current_user)):
    return memory.overview(user["uid"])


@app.post("/api/memory/profile")
def memory_add_profile(body: MemTextIn, user: dict = Depends(current_user)):
    return memory.add_profile(user["uid"], body.text or "")


@app.put("/api/memory/items/{item_id}")
def memory_update_item(item_id: int, body: MemTextIn, user: dict = Depends(current_user)):
    return memory.update_item(user["uid"], item_id, body.text, body.pinned)


@app.delete("/api/memory/items/{item_id}")
def memory_delete_item(item_id: int, user: dict = Depends(current_user)):
    return memory.delete_item(user["uid"], item_id)


@app.put("/api/memory/subjects/{subject_id}")
def memory_update_subject(subject_id: int, body: SubjectIn, user: dict = Depends(current_user)):
    return memory.update_subject(user["uid"], subject_id, body.dict())


@app.post("/api/memory/subjects/{subject_id}/merge")
def memory_merge_subject(subject_id: int, body: MergeIn, user: dict = Depends(current_user)):
    return memory.merge_subjects(user["uid"], body.into, subject_id)


@app.post("/api/memory/subjects/{subject_id}/compact")
async def memory_compact_subject(subject_id: int, user: dict = Depends(current_user)):
    """手动整理一张卡：合并重复、去掉过时的条目（置顶的不动）。"""
    return await memory.compact_subject(user["uid"], subject_id, force=True)


@app.delete("/api/memory/subjects/{subject_id}")
def memory_delete_subject(subject_id: int, user: dict = Depends(current_user)):
    return memory.delete_subject(user["uid"], subject_id)


@app.post("/api/memory/pause")
def memory_pause(body: PauseIn, user: dict = Depends(current_user)):
    return memory.set_paused(user["uid"], body.paused)


@app.post("/api/memory/clear")
def memory_clear(user: dict = Depends(current_user)):
    return memory.clear_all(user["uid"])


# ---- 管理员：提示词 / 智囊团 ----

class PromptIn(BaseModel):
    system: str = ""
    user: str = ""
    capability: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    note: str = ""


class PromptTestIn(BaseModel):
    message: str
    draft: Optional[PromptIn] = None   # 传了就用编辑框里的内容试跑，不传就用已保存的草稿


class RollbackIn(BaseModel):
    version: int


class CouncilIn(BaseModel):
    code: Optional[str] = None
    name: str
    icon: str = ""
    description: str = ""
    advisors: list = []
    schools: list = []
    domains: list = []
    requirement: str = ""
    examples: list = []
    enabled: bool = True


@app.get("/api/admin/prompts")
def admin_prompts(admin: dict = Depends(admin_user)):
    return prompt_store.list_prompts()


@app.get("/api/admin/prompts/{key}")
def admin_prompt_detail(key: str, admin: dict = Depends(admin_user)):
    return prompt_store.detail(key)


@app.put("/api/admin/prompts/{key}")
def admin_prompt_save(key: str, body: PromptIn, admin: dict = Depends(admin_user)):
    return prompt_store.save_draft(key, body.dict(), admin["id"])


@app.post("/api/admin/prompts/{key}/test")
async def admin_prompt_test(key: str, body: PromptTestIn, admin: dict = Depends(admin_user)):
    return await advisor_admin.test_prompt(key, body.message, body.draft.dict() if body.draft else None, admin["uid"])


@app.post("/api/admin/prompts/{key}/publish")
def admin_prompt_publish(key: str, admin: dict = Depends(admin_user)):
    return prompt_store.publish(key, admin["id"])


@app.post("/api/admin/prompts/{key}/rollback")
def admin_prompt_rollback(key: str, body: RollbackIn, admin: dict = Depends(admin_user)):
    return prompt_store.rollback(key, body.version, admin["id"])


@app.post("/api/admin/prompts/{key}/reset")
def admin_prompt_reset(key: str, admin: dict = Depends(admin_user)):
    return prompt_store.reset(key)


@app.get("/api/admin/councils")
def admin_councils(admin: dict = Depends(admin_user)):
    return {"items": advisor_admin.list_councils(), "options": advisor_admin.options()}


@app.put("/api/admin/councils/{code}")
def admin_council_update(code: str, body: CouncilIn, admin: dict = Depends(admin_user)):
    return advisor_admin.update_council(code, body.dict())


@app.post("/api/admin/councils")
def admin_council_create(body: CouncilIn, admin: dict = Depends(admin_user)):
    return advisor_admin.create_council(body.dict())


@app.get("/api/admin/advisor-stats")
def admin_advisor_stats(days: int = 30, admin: dict = Depends(admin_user)):
    return advisor_stats.overview(days)
