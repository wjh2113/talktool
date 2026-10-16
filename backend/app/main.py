"""FastAPI 入口。启动：uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"""
import logging

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .db import init_db
from .services import sessions as svc
from .services.gateway import GatewayError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="TalkTool · AI 沟通训练", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/media/audio", StaticFiles(directory=str(config.AUDIO_DIR)), name="audio")


@app.on_event("startup")
def _startup():
    init_db()
    mode = "MOCK（未配置 GATEWAY_API_KEY）" if config.MOCK else f"网关 {config.GATEWAY_BASE_URL}"
    logging.getLogger("talktool").info("TalkTool 启动，语音模式：%s", mode)


@app.exception_handler(svc.NotFound)
async def _nf(_, e):
    return JSONResponse({"detail": str(e)}, status_code=404)


@app.exception_handler(svc.BadRequest)
async def _br(_, e):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(GatewayError)
async def _gw(_, e: GatewayError):
    return JSONResponse({"detail": str(e)}, status_code=502)


def uid(x_user_id: str = None) -> str:
    """MVP 不做登录：前端生成一个设备 ID 放在 X-User-Id 头里。"""
    return (x_user_id or "anonymous")[:64]


# ---------------- 基础 ----------------

@app.get("/api/health")
def health():
    return {"ok": True, "mock": config.MOCK, "provider": config.VOICE_PROVIDER,
            "min_duration_sec": config.MIN_DURATION_SEC}


@app.get("/api/ping")
def ping():
    return {"pong": True}


# ---------------- 内容 ----------------

@app.get("/api/categories")
def categories():
    return svc.list_categories()


@app.get("/api/scenarios/{scenario_id}")
def scenario(scenario_id: int):
    return svc.get_scenario(scenario_id)


@app.get("/api/drills/{drill_id}")
def drill(drill_id: int):
    return svc.get_drill(drill_id)


# ---------------- 训练会话 ----------------

class StartIn(BaseModel):
    drill_id: int


class EndIn(BaseModel):
    reason: str = "finish"  # finish | exit


@app.post("/api/sessions")
async def start(body: StartIn, x_user_id: str = Header(None)):
    return await svc.start_session(uid(x_user_id), body.drill_id)


@app.post("/api/sessions/{session_id}/turn")
async def turn(session_id: int,
               audio: UploadFile = File(...),
               format: str = Form("wav"),
               sample_rate: int = Form(16000),
               x_user_id: str = Header(None)):
    data = await audio.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "音频过大")
    return await svc.run_turn(uid(x_user_id), session_id, data, format, sample_rate)


@app.post("/api/sessions/{session_id}/end")
async def end(session_id: int, body: EndIn = None, x_user_id: str = Header(None)):
    reason = (body.reason if body else "finish")
    if reason not in ("finish", "exit"):
        raise HTTPException(400, "reason 只能是 finish 或 exit")
    return await svc.end_session(uid(x_user_id), session_id, reason)


@app.post("/api/sessions/{session_id}/report/retry")
async def retry(session_id: int, x_user_id: str = Header(None)):
    return await svc.retry_report(uid(x_user_id), session_id)


@app.get("/api/sessions")
def records(range: str = Query("all", pattern="^(all|week|month)$"),
            page: int = 1, page_size: int = 20, x_user_id: str = Header(None)):
    return svc.list_sessions(uid(x_user_id), range, page, page_size)


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: int, x_user_id: str = Header(None)):
    return svc.get_session_detail(uid(x_user_id), session_id)


@app.get("/api/stats")
def stats(x_user_id: str = Header(None)):
    return svc.get_stats(uid(x_user_id))
