"""新功能测试：旧库升级、表达数据、逐句复盘、进步对比、练习本、跟读、自定义场景。
在 backend 目录执行：python3 -m tests.test_features
"""
import array
import asyncio
import json
import math
import os
import sqlite3
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=tmp, GATEWAY_API_KEY="", MOCK_MODE="true", MIN_DURATION_SEC="60")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db  # noqa: E402

OLD_SCHEMA = """
CREATE TABLE category (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, sort_order INTEGER NOT NULL DEFAULT 0);
CREATE TABLE scenario (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
  title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0);
CREATE TABLE drill (id INTEGER PRIMARY KEY AUTOINCREMENT, scenario_id INTEGER NOT NULL REFERENCES scenario(id) ON DELETE CASCADE,
  title TEXT NOT NULL, description TEXT NOT NULL, cover_image TEXT NOT NULL DEFAULT '', pressure_level TEXT NOT NULL DEFAULT '低压',
  duration_min INTEGER NOT NULL DEFAULT 3, mode TEXT NOT NULL DEFAULT '纯语音', ai_role TEXT NOT NULL DEFAULT '',
  user_role TEXT NOT NULL DEFAULT '', training_goal TEXT NOT NULL DEFAULT '', opening_line TEXT NOT NULL DEFAULT '',
  system_prompt TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'online', sort_order INTEGER NOT NULL DEFAULT 0);
CREATE TABLE session (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, drill_id INTEGER NOT NULL REFERENCES drill(id),
  started_at TEXT NOT NULL, ended_at TEXT, duration_sec INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'in_progress',
  transcript TEXT NOT NULL DEFAULT '[]');
CREATE TABLE report (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL UNIQUE REFERENCES session(id) ON DELETE CASCADE,
  scores TEXT NOT NULL DEFAULT '{}', total_score INTEGER NOT NULL DEFAULT 0, summary TEXT NOT NULL DEFAULT '',
  highlights TEXT NOT NULL DEFAULT '[]', improvements TEXT NOT NULL DEFAULT '[]', detail_comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
INSERT INTO category(name, sort_order) VALUES ('当众表达', 0);
INSERT INTO scenario(category_id, title, subtitle) VALUES (1, '临时点名发言', 'x');
INSERT INTO drill(scenario_id, title, description) VALUES (1, '老场景', '老描述');
INSERT INTO session(user_id, drill_id, started_at, status, duration_sec) VALUES ('old', 1, '2026-10-16 07:51:00', 'too_short', 32);
"""


def make_speech_pcm(segments, rate=16000):
    """segments: [(ms, amplitude)]，生成 16k int16 PCM（正弦波模拟人声）。"""
    a = array.array("h")
    t = 0
    for ms, amp in segments:
        for _ in range(int(rate * ms / 1000)):
            a.append(int(amp * 32767 * math.sin(2 * math.pi * 220 * t / rate)))
            t += 1
    if sys.byteorder == "big":
        a.byteswap()
    return a.tobytes()


def test_migration():
    con = sqlite3.connect(config.DB_PATH)
    con.executescript(OLD_SCHEMA)
    con.commit()
    con.close()
    db.init_db()  # 旧库升级：不能丢数据，补列 + 建新表 + 系统分类
    con = sqlite3.connect(config.DB_PATH)
    cols = {r[1] for r in con.execute("PRAGMA table_info(drill)")}
    assert {"owner_id", "sample_script"} <= cols
    assert "metrics" in {r[1] for r in con.execute("PRAGMA table_info(session)")}
    assert "turn_reviews" in {r[1] for r in con.execute("PRAGMA table_info(report)")}
    assert con.execute("SELECT COUNT(*) FROM session WHERE user_id='old'").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM category WHERE is_system=1").fetchone()[0] == 1
    con.close()
    db.init_db()  # 幂等
    # 旧库只有 1 个公共分类：不会重复播种
    from app.services import sessions as svc
    assert [c["name"] for c in svc.list_categories()] == ["当众表达"]
    print("✓ migration")


def reset_db():
    for f in Path(tmp).glob("talktool.db*"):
        f.unlink()
    db.init_db()


def backdate(sid, seconds):
    with db.get_conn() as c:
        st = (db.now() - timedelta(seconds=seconds)).strftime(db.TIME_FMT)
        c.execute("UPDATE session SET started_at=? WHERE id=?", (st, sid))


async def test_features():
    from app.services import library, metrics, practice
    from app.services import sessions as svc

    reset_db()
    cats = svc.list_categories()
    assert len(cats) == 8 and "我的场景" not in [c["name"] for c in cats]

    # ---- 表达数据：反应 0.9s → 说 2s → 停 1s → 说 1.5s → 尾静音 1.4s
    pcm = make_speech_pcm([(900, 0.002), (2000, 0.3), (1000, 0.002), (1500, 0.3), (1400, 0.002)])
    info = metrics.analyze_audio(pcm, "pcm", 16000)
    assert abs(info["reaction_ms"] - 900) <= 60, info
    assert abs(info["speech_ms"] - 4500) <= 90, info
    assert info["pauses"] == 1, info
    m = metrics.turn_metrics(info, "嗯我觉得然后就是我们可以先做调研然后再定方案")
    assert m["fillers"] == {"嗯": 1, "然后": 2, "就是": 1} and m["chars"] == 22 and 250 < m["rate"] < 320, m
    wav, _, _ = __import__("app.services.voice", fromlist=["x"]).normalize_audio(pcm, "pcm", 16000)
    assert metrics.analyze_audio(wav, "wav")["pauses"] == 1
    assert metrics.analyze_audio(b"\0" * 32000, "pcm")["speech_ms"] == 0
    assert metrics.analyze_audio(b"xx", "mp3") == {}

    drill_id = [c for c in cats if c["name"] == "当众表达"][0]["scenarios"][0]["id"]
    drill_id = svc.get_scenario(drill_id)["drills"][0]["id"]
    U = "u1"

    async def full_session():
        sid = (await svc.start_session(U, drill_id))["session_id"]
        r1 = await svc.run_turn(U, sid, pcm, "pcm", 16000)
        assert r1["metrics"]["pauses"] == 1
        await svc.run_turn(U, sid, pcm, "pcm", 16000)
        backdate(sid, 100)
        return await svc.end_session(U, sid, "finish")

    d1 = await full_session()
    assert d1["status"] == "completed"
    assert d1["metrics"]["turns"] == 2 and d1["metrics"]["pauses"] == 2 and d1["metrics"]["rate"]
    tr = d1["report"]["turn_reviews"]
    assert len(tr) == 2 and tr[0]["turn"] == 1 and tr[0]["user_text"] and tr[0]["better"], tr
    assert d1["previous"] is None

    # ---- 进步对比
    d2 = await full_session()
    assert d2["previous"]["session_id"] == d1["id"] and d2["previous"]["total_score"] == d1["report"]["total_score"]
    assert set(d2["previous"]["scores"]) == set(d1["report"]["scores"])
    assert svc.get_drill(drill_id, U)["my_times"] == 2

    # ---- 练习本
    n1 = library.add_note(U, "phrase", tr[0]["better"], tr[0]["user_text"], session_id=d1["id"])
    assert n1["drill_id"] == drill_id
    assert library.add_note(U, "phrase", tr[0]["better"])["id"] == n1["id"]  # 去重
    library.add_note(U, "tip", "先给结论再展开", session_id=d1["id"])
    assert len(library.list_notes(U)) == 2 and len(library.list_notes(U, "tip")) == 1
    assert len(svc.get_session_detail(U, d1["id"])["saved_notes"]) == 2
    assert library.list_notes("other") == []
    try:
        library.add_note("other", "phrase", "x", session_id=d1["id"])
        raise AssertionError("越权收藏")
    except svc.NotFound:
        pass

    # ---- 跟读
    p = await practice.pronounce(U, pcm, "pcm", 16000, tr[0]["better"], note_id=n1["id"])
    assert 0 <= p["score"] <= 100
    best = library.list_notes(U, "phrase")[0]["best_score"]
    assert best == p["score"]
    s1 = await practice.drill_script(U, drill_id)
    s2 = await practice.drill_script(U, drill_id)
    assert s1["script"] and s1 == s2
    assert (await svc.tts("你好"))["mock"] is True
    library.delete_note(U, n1["id"])
    assert len(library.list_notes(U)) == 1

    # ---- 自定义场景
    cd = await library.create_custom_drill(U, "明天要跟房东谈退押金，他说墙面有划痕要扣一千", "高压")
    assert cd["is_custom"] and cd["pressure_level"] == "高压" and "owner_id" not in cd
    assert svc.get_drill(cd["id"], U)["title"]
    try:
        svc.get_drill(cd["id"], "intruder")
        raise AssertionError("别人能看到自定义场景")
    except svc.NotFound:
        pass
    try:
        await svc.start_session("intruder", cd["id"])
        raise AssertionError("别人能练自定义场景")
    except svc.NotFound:
        pass
    cs = (await svc.start_session(U, cd["id"]))["session_id"]
    await svc.run_turn(U, cs, pcm, "pcm", 16000)
    backdate(cs, 90)
    assert (await svc.end_session(U, cs, "finish"))["status"] == "completed"
    lst = library.list_custom_drills(U)
    assert len(lst) == 1 and lst[0]["times"] == 1 and lst[0]["best"]
    assert all(s["drill_count"] == 1 for c in svc.list_categories() for s in c["scenarios"])  # 不混进公共场景
    rec = svc.list_sessions(U)["items"][0]
    assert rec["is_custom"] is True
    library.delete_custom_drill(U, cd["id"])
    assert library.list_custom_drills(U) == []
    assert svc.get_session_detail(U, cs)["drill"]["title"]  # 删除后记录仍可查看
    try:
        await svc.start_session(U, cd["id"])
        raise AssertionError("已删除场景还能练")
    except svc.BadRequest:
        pass
    for bad in ("太短", "x" * 601):
        try:
            await library.create_custom_drill(U, bad)
            raise AssertionError("应校验长度")
        except svc.BadRequest:
            pass
    print("✓ features (mock)")
    await gateway_test(drill_id, pcm)


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
        FakeClient.calls.append((url, json, data, files))
        if url.endswith("/api/ai/chat"):
            prompt = json["messages"][-1]["content"]
            if "turn_reviews" in prompt:
                assert "平均语速" in prompt and "用户[第1句]" in prompt
                content = ('好的```json\n{"scores":{"逻辑表达":8,"语言组织":7,"应变能力":6,"情绪管理":8},"summary":"ok",'
                           '"highlights":["h"],"improvements":["i"],"detail_comment":"d",'
                           '"turn_reviews":[{"turn":1,"better":"更好的说法","tip":"先结论"},{"turn":9,"better":"越界"}]}\n```')
            elif "用户描述" in prompt:
                content = json_dumps({"title": "和房东谈退押金", "description": "你是租客……", "ai_role": "强势房东",
                                      "user_role": "租客", "training_goal": "据理力争", "opening_line": "墙都划花了还想全退？",
                                      "duration_min": 99})
            elif "示范发言" in prompt:
                content = "“谢谢王总，我的看法是……”"
            else:
                content = "嗯，你继续说。"
            return FakeResp(js={"choices": [{"message": {"content": content}}]})
        if url.endswith("/api/ai/transcribe"):
            return FakeResp(js={"text": "我觉得然后要加强跟进"})
        if url.endswith("/api/ai/tts"):
            return FakeResp(content=b"ID3fake", headers={"Content-Type": "audio/mpeg"})
        if url.endswith("/api/ai/pronounce"):
            assert data["capability"] == "pronunciation" and data["text"] == "更好的说法" and files["file"][0] == "audio.wav"
            return FakeResp(js={"score": 82, "accuracy": 0.82, "transcript": "更好的说法", "issues": [{"quote": "说法", "note": "n"}], "note": "ok"})
        return FakeResp(404, {"detail": "nf"})


def json_dumps(o):
    return json.dumps(o, ensure_ascii=False)


async def gateway_test(drill_id, pcm):
    from app.services import gateway, library, practice
    from app.services import sessions as svc
    config.MOCK = False
    config.GATEWAY_API_KEY = "aam_test"
    config.GATEWAY_BASE_URL = "http://gw"
    gateway._client = lambda: FakeClient()
    U = "gw"
    sid = (await svc.start_session(U, drill_id))["session_id"]
    await svc.run_turn(U, sid, pcm, "pcm", 16000)
    backdate(sid, 80)
    det = await svc.end_session(U, sid, "finish")
    assert det["report"]["turn_reviews"] == [
        {"turn": 1, "user_text": "我觉得然后要加强跟进", "better": "更好的说法", "tip": "先结论"}], det["report"]
    assert det["metrics"]["filler_top"] == [{"word": "然后", "count": 1}]
    p = await practice.pronounce(U, pcm, "pcm", 16000, "更好的说法")
    assert p["score"] == 82 and p["issues"][0]["quote"] == "说法"
    cd = await library.create_custom_drill(U, "明天要跟房东谈退押金", "中压")
    assert cd["title"] == "和房东谈退押金" and cd["duration_min"] == 8 and cd["opening_line"]
    sc = await practice.drill_script(U, cd["id"])
    assert sc["script"] == "谢谢王总，我的看法是……", sc
    t1 = await svc.tts("示范一句")
    t2 = await svc.tts("示范一句")
    assert t1["audio_url"] == t2["audio_url"] and t1["audio_url"].startswith("/media/audio/t_")
    tts_calls = [c for c in FakeClient.calls if c[0].endswith("/api/ai/tts") and c[1]["input"] == "示范一句"]
    assert len(tts_calls) == 1  # 缓存命中
    print("✓ features (gateway)")


test_migration()
asyncio.run(test_features())
print("ALL FEATURE TESTS PASSED")
