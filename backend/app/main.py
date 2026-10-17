"""FastAPI 入口。启动：uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"""
import asyncio
import logging
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .db import init_db
from .services import auth, frameworks, library, maintenance, practice
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
    n = svc.recover_pending_reports()
    if n:
        log.info("有 %s 份报告在上次重启时中断，已标记为失败，可在报告页重新生成", n)
    t = asyncio.get_running_loop().create_task(maintenance.loop())
    _bg.add(t)
    mode = "MOCK（未配置 GATEWAY_API_KEY）" if config.MOCK else f"网关 {config.GATEWAY_BASE_URL}"
    log.info("TalkTool 启动，语音模式：%s", mode)


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
