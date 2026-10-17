"""表达框架库测试：python3 -m tests.test_frameworks（在 backend 目录）"""
import asyncio
import json
import os
import sys
import tempfile

os.environ.update(DATA_DIR=tempfile.mkdtemp(), GATEWAY_API_KEY="", MOCK_MODE="true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db  # noqa: E402
from app.frameworks_data import CATEGORIES, FRAMEWORKS  # noqa: E402
from app.guides_data import GUIDES  # noqa: E402
from app.services import frameworks as fw, library, sessions as svc  # noqa: E402


def test_data():
    codes = [f["code"] for f in FRAMEWORKS]
    assert len(codes) == len(set(codes)), "框架 code 重复"
    assert len(FRAMEWORKS) >= 90
    for f in FRAMEWORKS:
        assert f["category"] in CATEGORIES, f["code"]
        assert f["name"] and f["summary"] and f["steps"] and f["example"], f["code"]
        assert all(s["name"] and s["desc"] for s in f["steps"]), f["code"]
    sources = {f["source"] for f in FRAMEWORKS}
    assert {"A", "C", "D", "自媒体助手"} <= sources, sources
    # 与自媒体助手重复的 4 个框架合并进了同名框架
    prep = next(f for f in FRAMEWORKS if f["code"] == "prep")
    assert prep["detail"] and any("写成文章" in t for t in prep["tips"])
    # 每个内置训练都有指南，且引用的框架都存在
    titles = [d["title"] for c in db.ALL_CATEGORIES for s in c["scenarios"] for d in s["drills"]]
    for t in titles:
        g = GUIDES.get(t) or next(d["guide"] for c in db.ALL_CATEGORIES for s in c["scenarios"]
                                  for d in s["drills"] if d["title"] == t and d.get("guide"))
        assert g["frameworks"] and g["pitfalls"], t
        assert all(code in codes for code, _ in g["frameworks"]), t
    print(f"✓ data：{len(FRAMEWORKS)} 个框架，{len(titles)} 个内置训练都有指南")


async def test_service():
    db.init_db()
    db.init_db()  # 幂等
    with db.get_conn() as c:
        n_fw = c.execute("SELECT COUNT(*) FROM framework").fetchone()[0]
        n_link = c.execute("SELECT COUNT(*) FROM drill_framework").fetchone()[0]
        n_public = c.execute("SELECT COUNT(*) FROM drill WHERE owner_id IS NULL").fetchone()[0]
        linked = c.execute("SELECT COUNT(DISTINCT drill_id) FROM drill_framework").fetchone()[0]
    assert n_fw == len(FRAMEWORKS) and linked == n_public and n_link >= n_public

    # 列表、分类、搜索
    lst = fw.list_frameworks()
    assert lst["total"] == len(FRAMEWORKS)
    assert [c["name"] for c in lst["categories"]] == [c for c in CATEGORIES if any(f["category"] == c for f in FRAMEWORKS)]
    assert all(f["category"] == "向上沟通" for f in fw.list_frameworks("向上沟通")["items"])
    hits = fw.list_frameworks(q="非暴力")["items"]
    assert hits and hits[0]["code"] == "nvc"
    assert next(f for f in lst["items"] if f["code"] == "prep")["drill_count"] >= 1

    # 详情：带关联训练和场景示例
    d = fw.get_framework("impromptu2")
    assert d["steps"][0]["name"] and d["drills"] and d["drills"][0]["example"]
    assert fw.get_framework(str(d["id"]))["code"] == "impromptu2"
    try:
        fw.get_framework("nope")
        raise AssertionError
    except svc.NotFound:
        pass

    # 训练详情带推荐框架 + 常见误区
    cats = svc.list_categories()
    sid = [s for c in cats if c["name"] == "当众表达" for s in c["scenarios"] if s["title"] == "临时点名发言"][0]["id"]
    drill = svc.get_drill(svc.get_scenario(sid)["drills"][0]["id"], "u1")
    assert [f["code"] for f in drill["frameworks"]][:2] == ["impromptu2", "prep"]
    assert drill["frameworks"][0]["scene_example"] and drill["frameworks"][0]["steps"]
    assert isinstance(drill["pitfalls"], list) and drill["pitfalls"]
    with db.get_conn() as c:
        text = fw.guide_text(c, drill["id"])
    assert "即兴发言 2 步走" in text and "稳住+感谢" in text

    # 新分类“自媒体口播”的训练关联自媒体框架
    self_media = [c for c in cats if c["name"] == "自媒体口播"][0]
    d2 = svc.get_drill(svc.get_scenario(self_media["scenarios"][0]["id"])["drills"][0]["id"])
    assert "dy_hook_3" in [f["code"] for f in d2["frameworks"]]

    # 自定义场景（Mock）自动带上推荐框架
    cd = await library.create_custom_drill("u1", "明天要跟房东谈退押金，他说墙面划痕要扣钱", "中压")
    assert [f["code"] for f in cd["frameworks"]] == ["nvc", "trade"] and cd["pitfalls"]
    # 私有训练的框架关联不会出现在别人看到的框架详情里
    assert all(x["id"] != cd["id"] for x in fw.get_framework("nvc", "other")["drills"])
    assert any(x["id"] == cd["id"] for x in fw.get_framework("nvc", "u1")["drills"])
    # 启动同步不会覆盖自定义场景的指南
    db.init_db()
    assert [f["code"] for f in svc.get_drill(cd["id"], "u1")["frameworks"]] == ["nvc", "trade"]
    # 框架示例可以示范朗读，任意文字不行；分句子串（≥6 字）也可读
    ex = fw.get_framework("prep")["example"]
    assert "audio_url" in await svc.tts(ex[:480].strip(), "u1")  # 不被拒绝
    chunk = ex.strip()[:40]
    assert len(chunk) >= 6 and "audio_url" in await svc.tts(chunk, "u1")
    try:
        await svc.tts("随便一句广告词", "u1")
        raise AssertionError
    except svc.BadRequest:
        pass
    try:
        await svc.tts("广告", "u1")  # 过短子串也不行
        raise AssertionError
    except svc.BadRequest:
        pass
    print("✓ service")
    await test_gateway()


class FakeResp:
    def __init__(self, js):
        self.status_code, self._js, self.headers = 200, js, {"Content-Type": "application/json"}
        self.text = json.dumps(js, ensure_ascii=False)
        self.content = b""

    def json(self):
        return self._js


class FakeClient:
    prompts = []

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def post(self, url, json=None, data=None, files=None, headers=None):
        p = json["messages"][-1]["content"]
        FakeClient.prompts.append(p)
        if "用户描述" in p:
            assert "nvc:非暴力沟通四步" in p and "xhs_seed" not in p  # 框架清单不含自媒体类
            c = ('{"title":"和房东谈押金","description":"你是租客……","ai_role":"房东","user_role":"租客",'
                 '"training_goal":"据理力争","opening_line":"划痕得扣钱","duration_min":3,'
                 '"frameworks":[{"code":"key_dialog","example":"先摆事实"},{"code":"not_exist","example":"x"}],'
                 '"pitfalls":["一上来就吵","不拿证据"]}')
        elif "四个维度" in p:
            assert "【推荐表达框架】即兴发言 2 步走" in p and "是否用上了框架" in p
            c = '{"scores":{"逻辑表达":8,"语言组织":7,"应变能力":6,"情绪管理":8},"summary":"ok","highlights":[],"improvements":[],"detail_comment":"d"}'
        elif "turn_reviews" in p:
            assert "推荐表达框架：即兴发言 2 步走" in p
            c = '{"turn_reviews":[{"turn":1,"better":"谢谢王总……","tip":"先稳住"}]}'
        else:
            c = "嗯。"
        return FakeResp({"choices": [{"message": {"content": c}}], "text": "我觉得要加强跟进"})


async def test_gateway():
    from app.services import gateway
    config.MOCK = False
    config.GATEWAY_API_KEY = "k"
    config.GATEWAY_BASE_URL = "http://gw"
    gateway._client = lambda: FakeClient()
    cd = await library.create_custom_drill("u2", "明天要跟房东谈退押金的事", "中压")
    assert [f["code"] for f in cd["frameworks"]] == ["key_dialog"], cd["frameworks"]  # 未知 code 被忽略
    assert cd["frameworks"][0]["scene_example"] == "先摆事实" and cd["pitfalls"] == ["一上来就吵", "不拿证据"]

    # 报告 / 逐句复盘的 Prompt 带上推荐框架
    cats = svc.list_categories()
    sid = [s for c in cats if c["name"] == "当众表达" for s in c["scenarios"] if s["title"] == "临时点名发言"][0]["id"]
    drill_id = svc.get_scenario(sid)["drills"][0]["id"]
    st = await svc.start_session("u2", drill_id)
    from datetime import timedelta
    with db.get_conn() as c:
        tr = [{"role": "ai", "text": "小李你说说"}, {"role": "user", "text": "我觉得要加强跟进"}]
        c.execute("UPDATE session SET transcript = ?, started_at = ? WHERE id = ?",
                  (json.dumps(tr, ensure_ascii=False), (db.now() - timedelta(seconds=90)).strftime(db.TIME_FMT),
                   st["session_id"]))
    await svc.end_session("u2", st["session_id"], "finish")
    await svc.drain_tasks()
    det = svc.get_session_detail("u2", st["session_id"])
    assert det["report_status"] == "ready" and det["drill"]["frameworks"][0]["code"] == "impromptu2"
    reviews = await svc.get_turn_reviews("u2", st["session_id"])
    assert reviews[0]["better"].startswith("谢谢王总")
    print("✓ gateway prompts")


test_data()
asyncio.run(test_service())
print("ALL FRAMEWORK TESTS PASSED")
