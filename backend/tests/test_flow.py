"""不依赖 FastAPI/httpx 的流程测试：python3 -m tests.test_flow（在 backend 目录下执行）"""
import asyncio, json, os, sys, tempfile
from datetime import timedelta

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=tmp, GATEWAY_API_KEY="", MOCK_MODE="true", MIN_DURATION_SEC="60")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db                      # noqa: E402
from app.services import sessions as svc, gateway, report, voice   # noqa: E402

U = "tester"


def backdate(sid, seconds):
    with db.get_conn() as c:
        st = (db.now() - timedelta(seconds=seconds)).strftime(db.TIME_FMT)
        c.execute("UPDATE session SET started_at=? WHERE id=?", (st, sid))


async def main():
    db.init_db()
    cats = svc.list_categories()
    assert len(cats) == 8, len(cats)
    assert sum(len(c["scenarios"]) for c in cats) == 21
    assert all(s["drill_count"] == 1 for c in cats for s in c["scenarios"])
    sc = svc.get_scenario(cats[-1]["scenarios"][0]["id"])
    assert sc["category_name"] == "当众表达" and sc["title"] == "临时点名发言"
    d = svc.get_drill(sc["drills"][0]["id"])
    assert "system_prompt" not in d

    # 1) 完整训练 → completed + 报告
    st = await svc.start_session(U, d["id"])
    sid = st["session_id"]
    assert st["mock"] and st["ai"]["text"].startswith("小李")
    for _ in range(2):
        r = await svc.run_turn(U, sid, b"\0" * 32000, "pcm", 16000)
        assert not r["empty"] and r["ai"]["text"]
    backdate(sid, 95)
    det = await svc.end_session(U, sid, "finish")
    assert det["status"] == "completed", det["status"]
    assert det["report"]["total_score"] > 0 and len(det["report"]["scores"]) == 4
    assert len(det["transcript"]) == 5

    # 2) 时长过短
    sid2 = (await svc.start_session(U, d["id"]))["session_id"]
    await svc.run_turn(U, sid2, b"\0" * 32000, "pcm", 16000)
    backdate(sid2, 32)
    det2 = await svc.end_session(U, sid2, "finish")
    assert det2["status"] == "too_short" and det2["report"] is None
    assert det2["summary_line"] == report.TOO_SHORT_TEXT

    # 3) 主动放弃
    sid3 = (await svc.start_session(U, d["id"]))["session_id"]
    det3 = await svc.end_session(U, sid3, "exit")
    assert det3["status"] == "abandoned"

    # 4) 空音频不计入
    sid4 = (await svc.start_session(U, d["id"]))["session_id"]
    assert (await svc.run_turn(U, sid4, b"", "pcm", 16000))["empty"]
    # 5) 过期会话自动放弃
    backdate(sid4, 3 * 3600)
    lst = svc.list_sessions(U, "all")
    assert lst["total"] == 4
    assert {i["id"]: i["status"] for i in lst["items"]}[sid4] == "abandoned"
    assert svc.list_sessions(U, "week")["total"] == 4
    assert svc.list_sessions("someone-else")["total"] == 0
    print("stats", svc.get_stats(U))

    # 6) 边界规则
    assert report.decide_status("exit", 200, 3) == "completed"
    assert report.decide_status("finish", 200, 0) == "too_short"
    assert report.decide_status("exit", 10, 0) == "abandoned"
    # 7) JSON 解析与归一化
    raw = gateway.extract_json('好的：\n```json\n{"scores":{"逻辑表达":"9","语言组织":12},"summary":"s","highlights":"a"}\n```')
    n = report.normalize_report(raw)
    assert n["scores"] == {"逻辑表达": 9, "语言组织": 10, "应变能力": 5, "情绪管理": 5} and n["highlights"] == ["a"]
    # 8) PCM → WAV
    wav, name, mime = voice.normalize_audio(b"\0" * 3200, "pcm", 16000)
    assert wav[:4] == b"RIFF" and mime == "audio/wav"

    await gateway_payload_test(d)
    print("ALL TESTS PASSED")


class FakeResp:
    def __init__(self, status=200, js=None, content=b"", headers=None):
        self.status_code, self._js, self.content = status, js, content
        self.headers = headers or {"Content-Type": "application/json"}
        self.text = json.dumps(js, ensure_ascii=False) if js is not None else ""

    def json(self):
        return self._js


class FakeClient:
    calls = []

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def post(self, url, json=None, data=None, files=None, headers=None):
        FakeClient.calls.append((url, json, data, files, headers))
        if url.endswith("/api/ai/chat"):
            cap = json["capability"]
            content = ('{"scores":{"逻辑表达":8,"语言组织":7,"应变能力":6,"情绪管理":8},"summary":"ok",'
                       '"highlights":["h"],"improvements":["i"],"detail_comment":"d"}') if cap == "quality-chat" else "那你具体说说？"
            return FakeResp(js={"choices": [{"message": {"content": content}}]})
        if url.endswith("/api/ai/transcribe"):
            return FakeResp(js={"text": "我觉得要加强跟进"})
        if url.endswith("/api/ai/tts"):
            return FakeResp(content=b"ID3fake", headers={"Content-Type": "audio/mpeg"})
        return FakeResp(404, {"detail": "nf"})


async def gateway_payload_test(d):
    """模拟网关，检查请求格式与真实（非 Mock）链路。"""
    config.MOCK = False
    config.GATEWAY_API_KEY = "aam_test"
    config.GATEWAY_BASE_URL = "http://gw"
    gateway._client = lambda: FakeClient()
    st = await svc.start_session("gw", d["id"])
    assert st["ai"]["audio_url"].startswith("/media/audio/") and st["provider"] == "pipeline"
    r = await svc.run_turn("gw", st["session_id"], b"\0" * 32000, "pcm", 16000)
    assert r["user_text"] == "我觉得要加强跟进" and r["ai"]["text"] == "那你具体说说？"
    backdate(st["session_id"], 120)
    det = await svc.end_session("gw", st["session_id"], "finish")
    assert det["status"] == "completed" and det["report"]["summary"] == "ok", det
    urls = [c[0] for c in FakeClient.calls]
    assert urls == ["http://gw/api/ai/tts", "http://gw/api/ai/transcribe", "http://gw/api/ai/chat",
                    "http://gw/api/ai/tts", "http://gw/api/ai/chat"], urls
    tr = FakeClient.calls[1]
    assert tr[2]["capability"] == "speech" and tr[2]["language"] == "zh" and tr[3]["file"][0] == "audio.wav"
    assert tr[4]["Authorization"] == "Bearer aam_test"
    assert FakeClient.calls[2][1]["capability"] == "fast-chat" and FakeClient.calls[4][1]["capability"] == "quality-chat"
    assert FakeClient.calls[0][1]["responseFormat"] == "mp3"
    # 错误码提示
    gateway._client = lambda: type("C", (FakeClient,), {"post": lambda self, *a, **k: _err()})()
    try:
        await gateway.chat([{"role": "user", "content": "hi"}])
        raise AssertionError("should fail")
    except gateway.GatewayError as e:
        assert "积分不足" in str(e)


async def _err():
    return FakeResp(402, {"detail": "insufficient"})


asyncio.run(main())
