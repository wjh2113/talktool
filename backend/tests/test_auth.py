"""账号 / 邀请码 / 限额 / 异步报告 / 音频清理 / WAL 测试：python3 -m tests.test_auth（在 backend 目录）"""
import asyncio
import os
import sqlite3
import sys
import tempfile
import time
import types
from datetime import timedelta

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=tmp, GATEWAY_API_KEY="", MOCK_MODE="true", MIN_DURATION_SEC="60",
                  ADMIN_USERNAME="boss", ADMIN_PASSWORD="boss-pass-1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db  # noqa: E402
from app.services import auth, library, maintenance, practice, quota  # noqa: E402
from app.services import sessions as svc  # noqa: E402


def expect(exc, fn, *a, **kw):
    try:
        r = fn(*a, **kw)
        if asyncio.iscoroutine(r):
            asyncio.get_event_loop().run_until_complete(r)
    except exc as e:
        return str(e)
    raise AssertionError(f"应抛出 {exc.__name__}")


async def aexpect(exc, coro):
    try:
        await coro
    except exc as e:
        return str(e)
    raise AssertionError(f"应抛出 {exc.__name__}")


def speech_pcm(ms=1500, rate=16000):
    import array, math
    a = array.array("h", [0] * int(rate * 0.3))
    a.extend(int(0.3 * 32767 * math.sin(2 * math.pi * 220 * i / rate)) for i in range(int(rate * ms / 1000)))
    a.extend([0] * int(rate * 0.3))
    if sys.byteorder == "big":
        a.byteswap()
    return a.tobytes()


def test_auth():
    db.init_db()
    con = sqlite3.connect(config.DB_PATH)
    assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    con.close()

    # 管理员：.env 引导创建，不覆盖已有密码
    auth.bootstrap_admin()
    admin = auth.login("boss", "boss-pass-1")["user"]
    assert admin["role"] == "admin" and admin["uid"] == f"acc_{admin['id']}"
    config.ADMIN_PASSWORD = "changed"
    auth.bootstrap_admin()
    auth.login("boss", "boss-pass-1")  # 密码没被覆盖
    # CLI：提升 + 重置
    auth.ensure_admin("boss", "new-pass-9", reset_password=True)
    auth.login("boss", "new-pass-9")

    # 邀请码
    codes = auth.create_invites(admin["id"], count=3, max_uses=1, note="第一批")
    assert len(codes) == 3 and all(len(c["code"]) == 8 and c["state"] == "active" for c in codes)
    multi = auth.create_invites(admin["id"], count=1, max_uses=2)[0]["code"]

    # 匿名设备上已有的记录，注册时归到新账号
    async def anon_session():
        cats = svc.list_categories()
        drill_id = svc.get_scenario(cats[0]["scenarios"][0]["id"])["drills"][0]["id"]
        sid = (await svc.start_session("u_legacydevice01", drill_id))["session_id"]
        library.add_note("u_legacydevice01", "tip", "旧设备上的收藏")
        return drill_id, sid
    drill_id, legacy_sid = asyncio.run(anon_session())

    r = auth.register(codes[0]["code"].lower(), "小明", "pass-123", "明明", "u_legacydevice01", ip="9.9.9.9")
    assert r["token"] and r["user"]["nickname"] == "明明" and r["claimed_sessions"] == 1
    me = auth.user_from_token(r["token"])
    assert me["username"] == "小明" and me["role"] == "user"
    assert svc.get_session_detail(me["uid"], legacy_sid)["id"] == legacy_sid
    assert library.list_notes(me["uid"])[0]["text"] == "旧设备上的收藏"
    assert library.list_notes("u_legacydevice01") == []

    # 邀请码只能用一次 / 多次码 / 停用 / 过期
    assert "邀请码" in expect(auth.InvalidInput, auth.register, codes[0]["code"], "xiaohong", "pass-123")
    auth.register(multi, "user_a", "pass-123")
    auth.register(multi, "user_b", "pass-123")
    expect(auth.InvalidInput, auth.register, multi, "user_c", "pass-123")
    auth.disable_invite(codes[1]["code"])
    expect(auth.InvalidInput, auth.register, codes[1]["code"], "user_d", "pass-123")
    with db.get_conn() as c:
        c.execute("UPDATE invite_code SET expires_at = '2000-01-01 00:00:00' WHERE code = ?", (codes[2]["code"],))
    expect(auth.InvalidInput, auth.register, codes[2]["code"], "user_e", "pass-123")
    states = {i["code"]: i["state"] for i in auth.list_invites()}
    assert states[codes[0]["code"]] == "used_up" and states[codes[1]["code"]] == "disabled"
    assert states[codes[2]["code"]] == "expired"
    assert [i for i in auth.list_invites() if i["code"] == multi][0]["used_by"] in ("user_a、user_b", "user_b、user_a")
    # 校验
    ok = auth.create_invites(admin["id"])[0]["code"]
    expect(auth.InvalidInput, auth.register, ok, "a", "pass-123")           # 用户名太短
    expect(auth.InvalidInput, auth.register, ok, "user_f", "123")           # 密码太短
    expect(auth.InvalidInput, auth.register, ok, "小明", "pass-123")         # 重名
    assert [i for i in auth.list_invites() if i["code"] == ok][0]["used_count"] == 0  # 失败不消耗

    # 登录 / 改密码 / 退出
    expect(auth.InvalidInput, auth.login, "小明", "wrong")
    t2 = auth.login("小明", "pass-123", ip="1.1.1.1")["token"]
    auth.change_password(me["id"], "pass-123", "pass-456")
    expect(auth.InvalidInput, auth.change_password, me["id"], "pass-123", "x" * 8)
    auth.login("小明", "pass-456")
    auth.logout(t2)
    expect(auth.AuthError, auth.user_from_token, t2)
    expect(auth.AuthError, auth.user_from_token, "")
    expect(auth.AuthError, auth.user_from_token, "garbage")

    # 令牌过期
    t3 = auth.login("小明", "pass-456")["token"]
    with db.get_conn() as c:
        c.execute("UPDATE auth_token SET expires_at = '2000-01-01 00:00:00'")
    expect(auth.AuthError, auth.user_from_token, t3)

    # 管理员停用用户 → 立即失效、不能登录；重置密码
    t4 = auth.login("小明", "pass-456")["token"]
    expect(auth.InvalidInput, auth.set_user_status, admin["id"], admin["id"], "disabled")
    auth.set_user_status(admin["id"], me["id"], "disabled")
    expect(auth.AuthError, auth.user_from_token, t4)
    expect(auth.InvalidInput, auth.login, "小明", "pass-456")
    auth.set_user_status(admin["id"], me["id"], "active")
    temp = auth.reset_user_password(me["id"])["temp_password"]
    auth.login("小明", temp)
    users = {u["username"]: u for u in auth.list_users()}
    assert users["小明"]["sessions"] == 1 and users["boss"]["role"] == "admin"
    expect(auth.Forbidden, auth.require_admin, me)

    # 登录失败锁定（按 IP，15 分钟窗口）
    config.LOGIN_FAIL_LIMIT = 3
    for _ in range(3):
        expect(auth.InvalidInput, auth.login, "小明", "bad", ip="6.6.6.6")
    assert "15 分钟" in expect(quota.QuotaExceeded, auth.login, "小明", temp, ip="6.6.6.6")
    auth.login("小明", temp, ip="7.7.7.7")  # 其他 IP 不受影响
    print("✓ auth")
    return me, drill_id


async def test_limits_and_reports(me, drill_id):
    U = me["uid"]
    pcm = speech_pcm()
    # 单场最多发言轮数
    config.MAX_USER_TURNS = 2
    sid = (await svc.start_session(U, drill_id))["session_id"]
    await svc.run_turn(U, sid, pcm, "pcm", 16000)
    await svc.run_turn(U, sid, pcm, "pcm", 16000)
    assert "上限" in await aexpect(svc.BadRequest, svc.run_turn(U, sid, pcm, "pcm", 16000))

    # 异步报告：结束立即返回 pending，后台完成后 ready
    with db.get_conn() as c:
        c.execute("UPDATE session SET started_at = ? WHERE id = ?",
                  ((db.now() - timedelta(seconds=90)).strftime(db.TIME_FMT), sid))
    first = await svc.end_session(U, sid, "finish")
    assert first["status"] == "completed" and first["report_status"] == "pending" and first["report"] is None
    assert [i for i in svc.list_sessions(U)["items"] if i["id"] == sid][0]["summary_line"] == "报告生成中…"
    await svc.drain_tasks()
    det = svc.get_session_detail(U, sid)
    assert det["report_status"] == "ready" and det["report"]["total_score"] > 0

    # 生成失败 → failed，可以重新生成
    from app.services import report as report_svc
    orig = report_svc.generate_report

    async def boom(*a, **k):
        raise RuntimeError("gateway down")
    report_svc.generate_report = boom
    sid2 = (await svc.start_session(U, drill_id))["session_id"]
    await svc.run_turn(U, sid2, pcm, "pcm", 16000)
    with db.get_conn() as c:
        c.execute("UPDATE session SET started_at = ? WHERE id = ?",
                  ((db.now() - timedelta(seconds=90)).strftime(db.TIME_FMT), sid2))
    await svc.end_session(U, sid2, "finish")
    await svc.drain_tasks()
    d2 = svc.get_session_detail(U, sid2)
    assert d2["report_status"] == "failed" and d2["summary_line"] == report_svc.FAILED_TEXT
    report_svc.generate_report = orig
    await svc.retry_report(U, sid2)
    await svc.drain_tasks()
    assert svc.get_session_detail(U, sid2)["report_status"] == "ready"

    # 服务重启时中断的报告 → failed
    with db.get_conn() as c:
        c.execute("UPDATE session SET report_status = 'pending' WHERE id = ?", (sid2,))
    assert svc.recover_pending_reports() == 1
    assert svc.get_session_detail(U, sid2)["report_status"] == "ready"  # 已有报告的显示 ready

    # TTS 白名单：只能读示范内容
    assert "示范" in await aexpect(svc.BadRequest, svc.tts("帮我读一段广告词", U))
    library.add_note(U, "phrase", "我的看法有两点")
    assert (await svc.tts("我的看法有两点", U))["mock"]
    tr = await svc.get_turn_reviews(U, sid)
    await svc.tts(tr[0]["better"], U)  # 报告里的逐句示范可以读
    script = (await practice.drill_script(U, drill_id))["script"]
    await svc.tts(script, U)
    await svc.tts("随便什么")  # user_id=None（内部调用）不受限

    # 非 Mock 下的每日限额（不真正调网关：额度检查在调用之前）
    config.MOCK = False
    config.DAILY_PRONOUNCE_LIMIT = 1
    quota.add(U, "pronounce")
    assert "跟读" in await aexpect(quota.QuotaExceeded, practice.pronounce(U, pcm, "pcm", 16000, "你好"))
    config.DAILY_REVIEW_LIMIT = 1
    quota.add(U, "review")
    assert "次数" in await aexpect(quota.QuotaExceeded, svc.retry_report(U, sid))
    config.DAILY_TTS_LIMIT = 1
    quota.add(U, "tts")
    library.add_note(U, "phrase", "还没合成过的一句")
    assert "朗读" in await aexpect(quota.QuotaExceeded, svc.tts("还没合成过的一句", U))
    # 命中缓存的不计数：造一个缓存文件
    import hashlib
    from app.services.voice import voice_for_gender
    voice = voice_for_gender("male")
    name = "t_" + hashlib.sha1(f"{voice}|{config.TTS_SPEED}|我的看法有两点".encode()).hexdigest()[:20] + ".mp3"
    (config.AUDIO_DIR / name).write_bytes(b"ID3")
    assert (await svc.tts("我的看法有两点", U))["audio_url"].endswith(name)
    config.MOCK = True
    config.DAILY_CUSTOM_LIMIT = 1
    await library.create_custom_drill(U, "明天和房东谈退押金的事情", "中压")
    assert "自定义" in await aexpect(quota.QuotaExceeded, library.create_custom_drill(U, "第二个自定义场景描述", "中压"))
    print("✓ limits & async report")


def test_cleanup():
    d = config.AUDIO_DIR
    now_ts = time.time()
    files = {"s1_old.mp3": 10, "s2_new.mp3": 1, "t_old.mp3": 400, "t_new.mp3": 30, "other.txt": 999}
    for name, days in files.items():
        p = d / name
        p.write_bytes(b"x" * 100)
        os.utime(p, (now_ts - days * 86400, now_ts - days * 86400))
    r = maintenance.cleanup_audio(now_ts)
    left = {p.name for p in d.iterdir()}
    assert r["session"] == 1 and r["cache"] == 1, r
    assert {"s2_new.mp3", "t_new.mp3", "other.txt"} <= left and "s1_old.mp3" not in left and "t_old.mp3" not in left
    out = maintenance.run_once()
    assert "tokens" in out and "counters" in out
    print("✓ audio cleanup")


def test_routes(me):
    """FastAPI 未安装时用一个极简替身导入 main.py，直接调用每个路由函数，确保接线没有低级错误。"""
    try:
        import fastapi  # noqa: F401
        print("（已安装 FastAPI，路由测试请用 TestClient）")
        return
    except ImportError:
        pass
    try:
        import pydantic  # noqa: F401
    except ImportError:
        print("（未安装 pydantic，跳过路由测试；pip install -r requirements.txt 后再跑）")
        return

    def passthrough(*a, **k):
        return k.get("default", a[0] if a else None)

    class FastAPI:
        def __init__(self, **k): pass
        def add_middleware(self, *a, **k): pass
        def mount(self, *a, **k): pass
        def add_exception_handler(self, *a, **k): pass
        def on_event(self, *a):
            return lambda f: f
        def _route(self, *a, **k):
            return lambda f: f
        get = post = put = delete = _route

    class HTTPException(Exception):
        def __init__(self, status, detail=""):
            super().__init__(detail)

    fa = types.ModuleType("fastapi")
    fa.FastAPI, fa.HTTPException = FastAPI, HTTPException
    fa.Depends = fa.File = fa.Form = fa.Header = fa.Query = passthrough
    fa.Request = fa.UploadFile = object
    for sub, names in (("middleware.cors", ["CORSMiddleware"]), ("responses", ["JSONResponse"]),
                       ("staticfiles", ["StaticFiles"])):
        m = types.ModuleType("fastapi." + sub)
        for n in names:
            setattr(m, n, type(n, (), {"__init__": lambda self, *a, **k: None}))
        sys.modules["fastapi." + sub] = m
    sys.modules["fastapi.middleware"] = types.ModuleType("fastapi.middleware")
    sys.modules["fastapi"] = fa
    from app import main

    class Req:
        client = types.SimpleNamespace(host="8.8.8.8")

    class Upload:
        def __init__(self, data): self.data = data
        async def read(self): return self.data

    admin = auth.login("boss", "new-pass-9")
    bearer = "Bearer " + admin["token"]
    a = main.admin_user(main.current_user(bearer))
    assert main.me(a)["role"] == "admin"
    new = main.admin_create_invites(main.InviteIn(count=2, max_uses=1, expires_days=7, note="路由"), a)
    assert len(new) == 2 and new[0]["expires_at"]
    reg = main.register(main.RegisterIn(invite_code=new[0]["code"], username="route_user", password="pass-123"), Req())
    u = main.current_user("Bearer " + reg["token"])
    expect(auth.Forbidden, main.admin_user, u)
    expect(auth.AuthError, main.current_user, None)
    assert main.login(main.LoginIn(username="route_user", password="pass-123"), Req())["token"]
    main.admin_disable_invite(new[1]["code"], a)
    assert any(x["username"] == "route_user" for x in main.admin_users(a))
    main.admin_user_status(u["id"], main.StatusIn(status="active"), a)
    assert main.admin_reset_password(u["id"], a)["temp_password"]
    u = main.current_user("Bearer " + main.login(main.LoginIn(username="route_user", password="pass-123"), Req())["token"]) \
        if False else u
    tok = auth.login("route_user", main.admin_reset_password(u["id"], a)["temp_password"])["token"]
    u = main.current_user("Bearer " + tok)
    main.update_profile(main.ProfileIn(nickname="路由"), u)

    async def flow():
        cats = main.categories(u)
        sc = main.scenario(cats[0]["scenarios"][0]["id"], u)
        d = main.drill(sc["drills"][0]["id"], u)
        await main.drill_script(d["id"], u)
        st = await main.start(main.StartIn(drill_id=d["id"]), Req(), u)
        sid = st["session_id"]
        await main.turn(sid, Upload(speech_pcm()), "pcm", 16000, u)
        with db.get_conn() as c:
            c.execute("UPDATE session SET started_at = ? WHERE id = ?",
                      ((db.now() - timedelta(seconds=90)).strftime(db.TIME_FMT), sid))
        await main.end(sid, main.EndIn(reason="finish"), u)
        await svc.drain_tasks()
        await main.turn_reviews(sid, u)
        await main.retry(sid, u)
        await svc.drain_tasks()
        assert main.records("all", 1, 20, u)["total"] == 1
        assert main.session_detail(sid, u)["report_status"] == "ready"
        n = main.add_note(main.NoteIn(kind="phrase", text="路由收藏", session_id=sid), u)
        await main.tts(main.TtsIn(text="路由收藏"), u)
        await main.pronounce(Upload(speech_pcm()), "路由收藏", "pcm", 16000, n["id"], u)
        assert main.notes(None, u)
        main.delete_note(n["id"], u)
        cd = await main.create_custom(main.CustomIn(description="想和领导谈谈涨薪的事情"), u)
        assert main.custom_drills(u)
        main.delete_custom(cd["id"], u)
        assert main.stats(u)["total"] == 1
        main.change_password(main.PasswordIn(old_password="x" * 6, new_password="y" * 6), u) if False else None
        main.logout("Bearer " + tok)
        expect(auth.AuthError, main.current_user, "Bearer " + tok)
    config.DAILY_REVIEW_LIMIT = config.DAILY_CUSTOM_LIMIT = 50
    asyncio.run(flow())
    assert main.health()["ok"] and main.ping()["pong"]
    print("✓ routes (FastAPI 替身)")


me, drill_id = test_auth()
asyncio.run(test_limits_and_reports(me, drill_id))
test_cleanup()
test_routes(me)
print("ALL AUTH TESTS PASSED")
