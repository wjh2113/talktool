"""AI 智囊团测试：python3 -m tests.test_consult（在 backend 目录）"""
import asyncio
import json
import os
import re
import sys
import tempfile
from datetime import timedelta

os.environ.update(DATA_DIR=tempfile.mkdtemp(), GATEWAY_API_KEY="", MOCK_MODE="true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db  # noqa: E402
from app.councils_data import ADVISORS, COUNCILS  # noqa: E402
from app.frameworks_data import FRAMEWORKS  # noqa: E402
from app.prompts_default import DEFAULTS  # noqa: E402
from app.strategies_data import SCHOOLS, STRATEGIES, validate  # noqa: E402
from app.services import (advisor_admin, consult, memory, prompt_store, sessions as svc,  # noqa: E402
                          strategies as st, workflow)


def test_data():
    assert validate({f["code"] for f in FRAMEWORKS}) == []
    assert len(STRATEGIES) >= 390
    adv = {a["code"] for a in ADVISORS}
    for c in COUNCILS:
        assert set(c["advisors"]) <= adv, c["code"]
        for s in c["schools"]:
            assert s in SCHOOLS and any(x["school"] == s for x in STRATEGIES), (c["code"], s)
        assert f"council.{c['code']}" in DEFAULTS
    assert "startup" in {c["code"] for c in COUNCILS}
    assert any(s["school"] == "maoxuan" for s in STRATEGIES)
    assert sum(1 for s in STRATEGIES if s["school"] == "sanshiliu") == 36
    for key, d in DEFAULTS.items():
        present = set(prompt_store.VAR_RE.findall(d["system"] + d["user"]))
        assert set(d["required"]) <= present, key
    print(f"✓ data：{len(STRATEGIES)} 条谋略、{len(ADVISORS)} 位谋士、{len(COUNCILS)} 个智囊团")


async def test_mock_flow():
    db.init_db()
    db.init_db()  # 幂等
    with db.get_conn() as c:
        assert c.execute("SELECT COUNT(*) FROM strategy").fetchone()[0] == len(STRATEGIES)
        assert c.execute("SELECT COUNT(*) FROM council").fetchone()[0] == len(COUNCILS)

    # 谋略库
    lst = st.list_strategies(school="maoxuan")
    assert lst["total"] >= 15 and all(x["school"] == "maoxuan" for x in lst["items"])
    assert st.list_strategies(q="知己知彼")["items"][0]["code"] == "sunzi_know"
    d = st.get_strategy("ji_jiedao")
    assert d["caution"] and d["sub"].startswith("第3计")
    assert any(x["code"] == "sunzi_know" for x in st.related_to_framework("ask_first"))

    # 正常问计：识别 → 分派 → 出锦囊
    r = await consult.create("u1", "新来的王总总在会上否定我的方案，我想争取下季度的项目负责人")
    assert r["status"] == "routed" and r["council"]["code"] == "upward", r["council"]
    r = await consult.make_plan("u1", r["id"])
    plan = r["plan"]
    assert r["status"] == "planned" and plan["version"] == 1 and plan["actions"] and plan["content"]["lines"]
    assert plan["content"]["strategies"][0]["name"] and plan["content"]["advisor_views"][0]["name"]
    cid = r["id"]
    await svc.drain_tasks()
    ov = memory.overview("u1")
    assert any(p["name"] == "王总" for p in ov["people"]) and ov["cases"]
    with db.get_conn() as c:
        assert c.execute("SELECT case_id FROM consult WHERE id = ?", (cid,)).fetchone()[0]

    # 继续问 → 新版本锦囊
    r = await consult.add_message("u1", cid, "如果他当众反驳我怎么办？我不想太强硬，帮我改一下", "ask")
    assert r["plan"]["version"] == 2 and r["plan"]["versions"] == [1, 2]
    assert consult.get_detail("u1", cid, version=1)["plan"]["version"] == 1

    # 行动打勾 → 事件线
    act = r["plan"]["actions"][0]
    consult.update_action("u1", act["id"], True, "约上了，周三聊")
    case = [c for c in memory.overview("u1")["cases"]][0]
    assert any("完成" in i["text"] for i in case["items"])
    assert consult.ongoing_cases("u1")[0]["consult_id"] == cid

    # 去演练：生成对练，带框架和误区，可重复调用不重复生成
    drill = consult.rehearse("u1", cid)
    assert drill["title"].startswith("演练：") and drill["frameworks"] and drill["pitfalls"]
    assert consult.rehearse("u1", cid)["id"] == drill["id"]
    with db.get_conn() as c:
        assert "判断" in consult.plan_points_for_drill(c, dict(c.execute("SELECT * FROM drill WHERE id = ?", (drill["id"],)).fetchone()))

    # 示范朗读白名单：锦囊话术可以读，别人的不行
    line = r["plan"]["content"]["lines"][0]["text"]
    assert svc._tts_allowed("u1", line) and not svc._tts_allowed("u2", line)

    # 追问路径：信息不足 → 追问 → 回答后重新识别
    r2 = await consult.create("u1", "怎么办")
    assert r2["status"] == "clarifying" and r2["messages"][-1]["data"]["questions"]
    r2 = await consult.add_message("u1", r2["id"], "对方是我老婆，她嫌我总加班不陪她", "answer")
    assert r2["status"] == "routed" and r2["council"]["code"] == "family"
    # 跳过追问
    r3 = await consult.create("u1", "帮帮我")
    r3 = await consult.add_message("u1", r3["id"], "", "skip")
    assert r3["status"] == "routed"

    # 用户指定智囊团 + 换团重出
    r4 = await consult.create("u1", "我想辞职做一个小程序，合伙人想多要股份", council_code="startup")
    assert r4["council"]["code"] == "startup"
    r4 = await consult.make_plan("u1", r4["id"])
    r4 = await consult.make_plan("u1", r4["id"], council_code="negotiation")
    assert r4["council"]["code"] == "negotiation" and r4["plan"]["version"] == 2

    # 安全路径：不出谋略
    r5 = await consult.create("u1", "我想报复我同事，在群里造谣他")
    assert r5["status"] == "safety" and r5["plan"] is None
    try:
        await consult.make_plan("u1", r5["id"])
        raise AssertionError
    except svc.BadRequest:
        pass
    r6 = await consult.create("u1", "我不想活了，太累了")
    assert r6["status"] == "safety" and "12356" in r6["messages"][-1]["text"]

    # 别人看不到
    try:
        consult.get_detail("u2", cid)
        raise AssertionError
    except svc.NotFound:
        pass
    assert len(consult.list_consults("u1")) == 6 and consult.list_consults("u2") == []
    print("✓ mock flow")
    return cid


def test_memory():
    u = "m1"
    res = memory.apply_extraction(u, {
        "profile": ["产品经理，带 5 人团队", "我的身份证号是 110…", "月薪 3 万"],
        "people": [{"name": "王总", "aliases": ["王强"], "relation": "新来的部门领导", "facts": ["D 型，只看数据", "10 月 12 日会上否定了方案"]}],
        "case": {"title": "争取项目负责人", "goal": "当上负责人", "update": "已约一对一", "status": "open"},
    }, source="测试")
    ov = memory.overview(u)
    assert [i["text"] for i in ov["profile"]] == ["产品经理，带 5 人团队"]  # 敏感信息不记
    wang = ov["people"][0]
    assert wang["aliases"] == ["王强"] and len(wang["items"]) == 2 and res["case_id"]
    # 去重 + 别名匹配
    memory.apply_extraction(u, {"people": [{"name": "王强", "facts": ["D型，只看数据"]}]})
    assert len(memory.overview(u)["people"]) == 1 and len(memory.overview(u)["people"][0]["items"]) == 2
    # 读：提到别名就带上人物卡
    text, refs = memory.context(u, "王强又在会上挑刺了")
    assert "人物卡·王总" in text and "我的档案" in text and any(r["kind"] == "person" for r in refs)
    text2, _ = memory.context(u, "和老婆吵架了")
    assert "人物卡" not in text2
    # 忘掉
    memory.apply_extraction(u, {"forget": ["只看数据"]})
    assert len(memory.overview(u)["people"][0]["items"]) == 1
    # 合并人物卡
    memory.apply_extraction(u, {"people": [{"name": "老王", "facts": ["喜欢早上开会"]}]})
    people = memory.overview(u)["people"]
    keep = next(p for p in people if p["name"] == "王总")
    other = next(p for p in people if p["name"] == "老王")
    memory.merge_subjects(u, keep["id"], other["id"])
    merged = memory.overview(u)["people"]
    assert len(merged) == 1 and "老王" in merged[0]["aliases"] and len(merged[0]["items"]) == 2
    # 暂停：不读不写
    memory.set_paused(u, True)
    assert memory.context(u, "王总")[0] == "（用户暂停了记忆）"
    assert memory.apply_extraction(u, {"profile": ["新事实"]})["added"] == 0
    memory.set_paused(u, False)
    # 编辑 / 删除 / 清空
    item = memory.overview(u)["profile"][0]
    memory.update_item(u, item["id"], "产品经理，带 6 人团队", pinned=True)
    assert memory.overview(u)["profile"][0]["text"] == "产品经理，带 6 人团队"
    try:
        memory.delete_item("other", item["id"])
        raise AssertionError
    except svc.NotFound:
        pass
    memory.clear_all(u)
    ov = memory.overview(u)
    assert not ov["profile"] and not ov["people"] and not ov["cases"]
    print("✓ memory")


def test_prompt_store():
    key = "council.upward"
    base = prompt_store.get(key)
    assert base["source"] == "default" and "{{council_name}}" in base["system"] and "领导的顾虑" in base["system"]
    try:
        prompt_store.save_draft(key, {"system": "x", "user": "{{situation}} 只要 JSON"}, 1)  # 缺 strategies/frameworks
        raise AssertionError
    except svc.BadRequest as e:
        assert "strategies" in str(e)
    body = {"system": base["system"] + "\n【测试版】", "user": base["user"], "capability": "quality-chat",
            "max_tokens": 2000, "temperature": 0.5, "note": "加测试标记"}
    d = prompt_store.save_draft(key, body, 1)
    assert d["draft"]["version"] == 1 and d["active"] is None
    assert prompt_store.get(key)["source"] == "default"  # 草稿不生效
    with prompt_store.use_override(prompt_store.draft_override(key)):
        assert "【测试版】" in prompt_store.get(key)["system"]
    prompt_store.publish(key, 1)
    assert "【测试版】" in prompt_store.get(key)["system"] and prompt_store.get(key)["version"] == 1
    prompt_store.save_draft(key, dict(body, system=base["system"] + "\n【第二版】"), 1)
    prompt_store.publish(key, 1)
    assert prompt_store.get(key)["version"] == 2
    d = prompt_store.rollback(key, 1, 1)
    assert d["active"]["version"] == 3 and "【测试版】" in prompt_store.get(key)["system"]
    assert [h["version"] for h in d["history"]] == [3, 2, 1]
    prompt_store.reset(key)
    assert prompt_store.get(key)["source"] == "default"
    keys = [p["key"] for p in prompt_store.list_prompts()]
    assert keys[0] == "intent" and "council.startup" in keys and "memory_extract" in keys
    msgs, meta = prompt_store.render("intent", {"message": "你好", "councils": "x"})
    assert "你好" in msgs[-1]["content"] and "（无）" in msgs[-1]["content"] and meta["capability"] == "fast-chat"
    print("✓ prompt store")


def test_council_admin():
    r = advisor_admin.create_council({"code": "newbie", "name": "职场新人团", "description": "刚入职、试用期",
                                      "advisors": ["xiansheng", "zhixin"], "schools": ["rujia", "interpersonal"],
                                      "domains": ["职场"], "requirement": "语气更像学长学姐"})
    assert r["prompt_key"] == "council.newbie"
    assert "newbie：职场新人团" in workflow.councils_menu()
    assert "学长学姐" in prompt_store.get("council.newbie")["system"]
    assert "council.newbie" in [p["key"] for p in prompt_store.list_prompts()]
    assert [c["code"] for c in workflow.councils()][-1] == "general"
    advisor_admin.update_council("upward", {"name": "向上管理团", "advisors": ["zhanlue"], "schools": ["maoxuan"]})
    db.init_db()  # 后台改过的不被启动同步覆盖
    assert workflow.get_council("upward")["name"] == "向上管理团"
    for bad in ({"code": "Bad-Code", "name": "x", "advisors": ["junshi"]}, {"code": "ok_code", "name": "", "advisors": ["junshi"]}):
        try:
            advisor_admin.create_council(bad)
            raise AssertionError
        except svc.BadRequest:
            pass
    try:
        advisor_admin.update_council("general", {"name": "综合团", "advisors": ["junshi"], "enabled": False})
        raise AssertionError
    except svc.BadRequest:
        pass
    print("✓ council admin")


# ---------------- 接真网关（假网关） ----------------

class FakeResp:
    def __init__(self, js):
        self.status_code, self._js, self.headers = 200, js, {"Content-Type": "application/json"}
        self.text, self.content = json.dumps(js, ensure_ascii=False), b""

    def json(self):
        return self._js


class FakeClient:
    seen = []

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def post(self, url, json=None, data=None, files=None, headers=None):
        if url.endswith("/api/ai/transcribe"):
            return FakeResp({"text": "供应商要涨价百分之十五"})
        msgs = json["messages"]
        allp = "\n".join(m["content"] for m in msgs)
        FakeClient.seen.append((json["capability"], allp))
        if "【测试草稿】" in allp:
            c = {"council": "negotiation", "confidence": 0.9, "title": "草稿测试", "info_enough": True, "risk": "none",
                 "summary": "草稿"}
        elif "接待员" in allp and "可选的智囊团" in allp:
            c = {"council": "negotiation", "confidence": 0.9, "title": "供应商涨价", "people": ["老李"],
                 "info_enough": True, "risk": "none", "summary": "供应商老李要求涨价 15%"}
        elif "多位谋士组成的智囊团" in allp:
            assert "【可用谋略】" in allp and "neg_batna｜" in allp and "谈判官" in allp
            assert "目标价、底线和替代方案" in allp  # 本团特别要求
            assert "人物卡·老李" in allp or "暂无" in allp
            c = {"headline": "先算清替代方案，再用有条件让步", "situation": "对方成本上涨",
                 "goal": {"best": "不涨", "acceptable": "涨 5%", "bottom": "涨 8%"},
                 "strategies": [{"code": "neg_batna", "use": "先找两家备选"}, {"code": "not_exist", "use": "x"}],
                 "actions": [{"text": "本周询价两家备选", "when": "本周"}],
                 "lines": [{"moment": "开场", "text": "老李，我们合作三年了，这次涨价我想先了解一下成本变化。", "framework": "ask_first", "why": "先问"},
                           {"moment": "压价", "text": "涨 5% 可以，但账期要延长到 60 天。", "framework": "bogus", "why": "交换"}],
                 "risks": [{"if": "他说不涨就停供", "then": "启动备选"}], "donts": ["先报底线"],
                 "advisor_views": [{"advisor": "tanpan", "view": "先算账"}, {"advisor": "nobody", "view": "x"}],
                 "rehearsal": {"ai_role": "供应商老李，强硬", "opening_line": "原材料涨了，必须涨 15%"},
                 "summary": "供应商老李要求涨价 15%，用户希望控制在 5% 以内"}
        elif "正在和用户继续讨论" in allp:
            c = {"reply": "可以先接受 5%，换账期。", "update_plan": False, "plan": None, "summary": "同上"}
        elif "整理长期记忆" in allp:
            c = {"profile": ["负责采购"], "people": [{"name": "老李", "relation": "供应商", "facts": ["合作三年", "说话强硬"]}],
                 "case": {"title": "供应商涨价", "goal": "控制在 5% 以内", "update": "", "status": "open"}}
        elif "四个维度" in allp:
            assert "【智囊锦囊要点】判断：先算清替代方案" in allp
            c = {"scores": {"逻辑表达": 8, "语言组织": 7, "应变能力": 6, "情绪管理": 8}, "summary": "ok",
                 "highlights": [], "improvements": [], "detail_comment": "d"}
        else:
            c = "嗯。"
        content = c if isinstance(c, str) else json_dumps(c)
        return FakeResp({"choices": [{"message": {"content": content}}]})


def json_dumps(o):
    return json.dumps(o, ensure_ascii=False)


async def test_gateway(first_cid):
    from app.services import gateway
    config.MOCK = False
    config.GATEWAY_API_KEY = "k"
    config.GATEWAY_BASE_URL = "http://gw"
    gateway._client = lambda: FakeClient()
    r = await consult.create("g1", "供应商老李要涨价 15%，说原材料涨了")
    assert r["status"] == "routed" and r["council"]["code"] == "negotiation"
    r = await consult.make_plan("g1", r["id"])
    c = r["plan"]["content"]
    assert [s["code"] for s in c["strategies"]] == ["neg_batna"]            # 不在候选里的谋略被丢掉
    assert c["lines"][0]["framework"] == "ask_first" and c["lines"][1]["framework"] == ""  # 未知框架清空
    assert [v["advisor"] for v in c["advisor_views"]] == ["tanpan"]
    assert FakeClient.seen[0][0] == "fast-chat" and FakeClient.seen[1][0] == "quality-chat"
    await svc.drain_tasks()
    ov = memory.overview("g1")
    assert ov["people"][0]["name"] == "老李" and ov["profile"][0]["text"] == "负责采购"
    # 第二次问计会带上老李的人物卡
    r2 = await consult.create("g1", "老李又打电话来催涨价了，说下周就停供")
    await consult.make_plan("g1", r2["id"])
    assert any("人物卡·老李" in p for cap, p in FakeClient.seen if "多位谋士组成的智囊团" in p)
    # 追问
    r3 = await consult.add_message("g1", r2["id"], "如果他真停供呢？", "ask")
    assert r3["messages"][-1]["text"] == "可以先接受 5%，换账期。" and r3["plan"]["version"] == 1
    # 演练 → 报告带锦囊要点
    drill = consult.rehearse("g1", r["id"])
    assert "老李" in drill["ai_role"]
    st_ = await svc.start_session("g1", drill["id"])
    with db.get_conn() as conn:
        tr = [{"role": "ai", "text": "必须涨 15%"}, {"role": "user", "text": "老李，我们合作三年了"}]
        conn.execute("UPDATE session SET transcript = ?, started_at = ? WHERE id = ?",
                     (json.dumps(tr, ensure_ascii=False), (db.now() - timedelta(seconds=120)).strftime(db.TIME_FMT), st_["session_id"]))
    await svc.end_session("g1", st_["session_id"], "finish")
    await svc.drain_tasks()
    assert svc.get_session_detail("g1", st_["session_id"])["report_status"] == "ready"
    case = memory.overview("g1")["cases"][0]
    assert any("演练了一次" in i["text"] for i in case["items"])
    # 语音输入
    assert await consult.resolve_text("", b"\0" * 4000, "pcm", 16000) == "供应商要涨价百分之十五"
    # 后台试运行草稿：用的是编辑框里的内容，不写问计
    n_before = len(consult.list_consults("admin-x"))
    base = prompt_store.get("intent")
    out = await advisor_admin.test_prompt("intent", "测试一下", {"system": base["system"] + "【测试草稿】", "user": base["user"]}, "admin-x")
    assert out["intent"]["title"] == "草稿测试" and len(consult.list_consults("admin-x")) == n_before
    # 删除问计：由它产生的记忆一起删
    consult.delete_consult("g1", r["id"])
    with db.get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_item WHERE consult_id = ?", (r["id"],)).fetchone()[0] == 0
    print("✓ gateway")


test_data()
cid = asyncio.run(test_mock_flow())
test_memory()
test_prompt_store()
test_council_admin()
asyncio.run(test_gateway(cid))
print("ALL CONSULT TESTS PASSED")
