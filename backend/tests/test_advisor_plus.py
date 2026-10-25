"""智囊团二、三期测试：python3 -m tests.test_advisor_plus（在 backend 目录）

圆桌会议、跟进提醒、报告长期对比、谋略/谋士/智囊团导入、私人谋士、记忆整理、效果统计。
"""
import asyncio
import json
import os
import sys
import tempfile
from datetime import timedelta

os.environ.update(DATA_DIR=tempfile.mkdtemp(), GATEWAY_API_KEY="", MOCK_MODE="true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db  # noqa: E402
from app.services import (advisor_admin, advisor_stats, catalog_import, consult, memory, my_advisors,  # noqa: E402
                          prompt_store, sessions as svc, strategies as st, workflow)
from app.services.sessions import BadRequest, NotFound  # noqa: E402


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    raise AssertionError(f"{fn.__name__} 应该抛出 {exc.__name__}")


async def araises(exc, coro):
    try:
        await coro
    except exc:
        return True
    raise AssertionError("应该抛出 " + exc.__name__)


def past(days=1):
    return (db.now() - timedelta(days=days)).strftime(db.TIME_FMT)


async def new_plan(uid, text="新来的王总总在会上否定我的方案，我想争取下季度的项目负责人", **kw):
    r = await consult.create(uid, text, **kw)
    return await consult.make_plan(uid, r["id"])


# ---------------- 跟进提醒 ----------------

async def test_followup():
    today = db.now().date()
    assert consult.hint_date("今天下班前") == today.isoformat()
    assert consult.hint_date("明天") == (today + timedelta(days=1)).isoformat()
    assert consult.hint_date("3天内") == (today + timedelta(days=3)).isoformat()
    assert consult.hint_date("下周") > today.isoformat()
    assert consult.hint_date("找个合适的机会") is None and consult.hint_date("") is None

    r = await new_plan("f1")
    cid = r["id"]
    assert r["follow_up_at"] > db.now_str()                     # 出锦囊后定了跟进时间
    assert any(a["remind_at"] for a in r["plan"]["actions"])    # “本周内 / 当天”自动换成提醒日期
    assert consult.due_followups("f1") == [] or all(d["due_actions"] for d in consult.due_followups("f1"))

    # 跟进时间到了 → 出现在“该跟进了”
    with db.get_conn() as c:
        c.execute("UPDATE consult SET follow_up_at = ? WHERE id = ?", (past(), cid))
        c.execute("UPDATE plan_action SET remind_at = NULL")
    due = consult.due_followups("f1")
    assert len(due) == 1 and due[0]["consult_id"] == cid and "跟进时间到了" in due[0]["reason"]
    assert consult.due_followups("other") == []

    # 稍后提醒
    consult.snooze("f1", cid, 2)
    assert consult.due_followups("f1") == []

    # 行动设了今天的提醒 → 到期
    act = r["plan"]["actions"][0]
    consult.update_action("f1", act["id"], remind_at=today.isoformat())
    due = consult.due_followups("f1")
    assert due and due[0]["due_actions"][0]["id"] == act["id"] and "该做了" in due[0]["reason"]
    raises(BadRequest, consult.update_action, "f1", act["id"], remind_at="下周三")
    consult.update_action("f1", act["id"], remind_at="")          # 取消提醒
    assert consult.due_followups("f1") == []

    # 行动全部做完 → 马上提醒回来复盘
    for a in r["plan"]["actions"]:
        consult.update_action("f1", a["id"], True)
    due = consult.due_followups("f1")
    assert due and "复盘" in due[0]["reason"] and due[0]["pending"] == 0
    # 复盘后不再提醒（行动都做完了）
    await consult.add_message("f1", cid, "谈成了，他同意我当负责人", "review")
    detail = consult.get_detail("f1", cid)
    if detail["plan"]["version"] == 1:       # 复盘没改锦囊：不再提醒
        assert detail["follow_up_at"] is None and consult.due_followups("f1") == []

    # 不用再提醒
    r2 = await new_plan("f1", "客户一直拖着不回款，催了三次了")
    with db.get_conn() as c:
        c.execute("UPDATE consult SET follow_up_at = ? WHERE id = ?", (past(), r2["id"]))
    assert consult.due_followups("f1")
    consult.stop_follow("f1", r2["id"])
    assert all(d["consult_id"] != r2["id"] for d in consult.due_followups("f1"))
    print("✓ follow-up reminders")


# ---------------- 圆桌会议 ----------------

async def test_roundtable():
    r = await consult.create("t1", "老板让我接一个没人要的烂项目，接还是不接")
    await araises(BadRequest, consult.roundtable("t1", r["id"]))       # 还没锦囊
    r = await consult.make_plan("t1", r["id"])
    n_msgs = len(r["messages"])
    r = await consult.roundtable("t1", r["id"], "要不要当面拒绝")
    m = r["messages"][-1]
    assert m["kind"] == "roundtable" and m["role"] == "advisor" and m["text"]
    d = m["data"]
    assert len({s["advisor"] for s in d["speeches"]}) >= 3 and any(s["round"] == 2 and s["reply_to"] for s in d["speeches"])
    assert d["verdict"]["adopt"] and d["moderator_name"] and d["question"] == "要不要当面拒绝"
    assert all(s["name"] for s in d["speeches"])
    assert r["messages"][-2]["kind"] == "roundtable_ask" and len(r["messages"]) == n_msgs + 2
    # 圆桌之后继续追问，正常工作
    r = await consult.add_message("t1", r["id"], "按裁决调整一下锦囊", "ask")
    assert r["messages"][-1]["kind"] == "reply"
    # normalize：不在场的谋士、空裁决被拒
    seats = ["junshi", "xinli", "zhanlue"]
    try:
        workflow.normalize_roundtable({"speeches": [{"advisor": "nobody", "text": "x"}], "verdict": {}}, seats)
        raise AssertionError
    except workflow.WorkflowError:
        pass
    # 安全路径不开圆桌
    r5 = await consult.create("t1", "我想报复我同事，在群里造谣他")
    await araises(BadRequest, consult.roundtable("t1", r5["id"]))
    print("✓ roundtable")


# ---------------- 私人谋士 ----------------

async def test_my_advisors():
    a = my_advisors.create("p1", {"name": "老周", "persona": "国企老处长，先看人再看事，说话直白", "schools": ["maoxuan", "bad"]})
    assert a["code"].startswith("my_") and a["schools"] == ["maoxuan"] and a["avatar"] == "老"
    raises(BadRequest, my_advisors.create, "p1", {"name": "", "persona": "xxxxxxx"})
    raises(BadRequest, my_advisors.create, "p1", {"name": "空", "persona": "短"})
    b = my_advisors.create("p2", {"name": "别人的", "persona": "另一个用户的私人谋士"})
    assert [x["code"] for x in my_advisors.list_mine("p1")] == [a["code"]]
    raises(NotFound, my_advisors.update, "p1", b["code"], {"name": "改", "persona": "想改别人的谋士"})
    my_advisors.update("p1", a["code"], {"name": "老周", "persona": "国企老处长，先看人再看事，说话很直", "style": "务实"})

    # 管理员配置智囊团时看不到私人谋士
    assert a["code"] not in {x["code"] for x in advisor_admin.options()["advisors"]}

    # 请来列席：别人的谋士会被过滤掉
    r = await consult.create("p1", "老板总在会上否定我的方案，我想争取项目负责人", advisors=[a["code"], b["code"]])
    assert [x["code"] for x in r["extra_advisors"]] == [a["code"]]
    r = await consult.make_plan("p1", r["id"])
    assert a["code"] in [v["advisor"] for v in r["plan"]["content"]["advisor_views"]]
    assert any(v["name"] == "老周" for v in r["plan"]["content"]["advisor_views"])
    council = workflow.get_council(r["council"]["code"])
    assert "私人谋士" in workflow.advisors_text(council, [a["code"]])
    rt = await consult.roundtable("p1", r["id"])
    assert a["code"] in {s["advisor"] for s in rt["messages"][-1]["data"]["speeches"]}

    # 改列席名单
    r = consult.set_extra_advisors("p1", r["id"], [b["code"]])
    assert r["extra_advisors"] == []
    consult.set_extra_advisors("p1", r["id"], [a["code"]])
    # 删除谋士 → 从问计里移除；历史锦囊里的发言保留
    my_advisors.delete("p1", a["code"])
    r = consult.get_detail("p1", r["id"])
    assert r["extra_advisors"] == [] and r["plan"]["content"]["advisor_views"]
    raises(NotFound, my_advisors.delete, "p1", a["code"])
    for i in range(my_advisors.MAX_PER_USER):
        my_advisors.create("p3", {"name": f"谋士{i}", "persona": "测试用的私人谋士人设"})
    raises(BadRequest, my_advisors.create, "p3", {"name": "超了", "persona": "测试用的私人谋士人设"})
    print("✓ private advisors")


# ---------------- 记忆整理 ----------------

async def test_memory_maintain():
    uid = "m1"
    with db.get_conn() as c:
        pid = memory.upsert_person(c, uid, "王总", [], "上级")
        for i in range(15):
            c.execute("""INSERT INTO memory_item(user_id, type, subject_id, text, source, created_at, updated_at)
                         VALUES (?,?,?,?,?,?,?)""", (uid, "fact", pid, f"王总的第{i}件事：喜欢看数据第{i}版", "", db.now_str(), db.now_str()))
        c.execute("UPDATE memory_item SET pinned = 1 WHERE subject_id = ? AND text LIKE '%第0件%'", (pid,))
        case = memory.upsert_case(c, uid, "争取项目负责人", "当上负责人")
        c.execute("UPDATE memory_subject SET last_seen = ? WHERE id = ?", (past(40), case))
        c.execute("""INSERT INTO memory_item(user_id, type, subject_id, text, created_at, updated_at)
                     VALUES (?,?,?,?,?,?)""", ("m2", "fact", None, "x", db.now_str(), db.now_str()))
    assert memory.needs_compact(pid)
    out = await memory.maintain()
    assert out["dormant"] >= 1 and out["compacted"] >= 1
    with db.get_conn() as c:
        items = [r[0] for r in c.execute("SELECT text FROM memory_item WHERE subject_id = ? AND pinned = 0", (pid,))]
        pinned = c.execute("SELECT COUNT(*) FROM memory_item WHERE subject_id = ? AND pinned = 1", (pid,)).fetchone()[0]
        status = c.execute("SELECT status FROM memory_subject WHERE id = ?", (case,)).fetchone()[0]
        compacted = c.execute("SELECT compacted_at FROM memory_subject WHERE id = ?", (pid,)).fetchone()[0]
    assert len(items) <= memory.COMPACT_LIMIT and pinned == 1 and status == "dormant" and compacted
    # 搁置的事不再带进问计；有新进展自动恢复
    block, refs = memory.context(uid, "争取项目负责人")
    assert not any(r["kind"] == "case" for r in refs)
    with db.get_conn() as c:
        memory.upsert_case(c, uid, "", "", case)
        assert c.execute("SELECT status FROM memory_subject WHERE id = ?", (case,)).fetchone()[0] == "open"
    # 手动整理：条目少时不动；别人的卡片不能整理
    res = await memory.compact_subject(uid, pid, force=True)
    assert res["after"] <= memory.COMPACT_LIMIT
    await araises(NotFound, memory.compact_subject("m2", pid, force=True))
    # 暂停记忆时不整理
    memory.set_paused(uid, True)
    with db.get_conn() as c:
        for i in range(14):
            c.execute("""INSERT INTO memory_item(user_id, type, subject_id, text, created_at, updated_at)
                         VALUES (?,?,?,?,?,?)""", (uid, "fact", pid, f"新事实{i}号很不一样{i * 7}", db.now_str(), db.now_str()))
    assert (await memory.maintain())["compacted"] == 0
    memory.set_paused(uid, False)
    print("✓ memory compaction & dormant")


# ---------------- 效果统计 ----------------

async def test_stats():
    r1 = await new_plan("s1")
    r2 = await new_plan("s2", "合伙人想多要股份，我想辞职做副业", council_code="startup")
    consult.rate_plan("s1", r1["plan"]["id"], 1)
    consult.rate_plan("s2", r2["plan"]["id"], -1, "太空泛了，没说具体怎么谈")
    raises(NotFound, consult.rate_plan, "s1", r2["plan"]["id"], 1)
    raises(BadRequest, consult.rate_plan, "s1", r1["plan"]["id"], 5)
    assert consult.get_detail("s1", r1["id"])["plan"]["rating"] == 1
    consult.rehearse("s1", r1["id"])
    ov = advisor_stats.overview(30)
    by = {c["code"]: c for c in ov["councils"]}
    assert by["upward"]["up"] >= 1 and by["upward"]["rehearsed"] >= 1 and by["startup"]["down"] == 1
    assert ov["total"]["rated"] >= 2 and 0 <= ov["total"]["up_rate"] <= 1
    assert ov["feedback"][0]["reason"].startswith("太空泛") and "王总" not in json.dumps(ov, ensure_ascii=False)
    assert any(p["key"] == "council.startup" and p["down"] == 1 and p["label"] == "默认版" for p in ov["prompts"])
    det = prompt_store.detail("council.startup")
    assert det["ratings"]["0"]["rated"] >= 1
    consult.rate_plan("s2", r2["plan"]["id"], 0)    # 撤销评价
    assert consult.get_detail("s2", r2["id"])["plan"]["rating"] is None
    assert "roundtable" in [p["key"] for p in prompt_store.list_prompts()]
    assert "memory_compact" in [p["key"] for p in prompt_store.list_prompts()]
    print("✓ stats & rating")


# ---------------- 报告：长期对比 ----------------

async def run_session(uid, drill_id, text):
    s = await svc.start_session(uid, drill_id)
    with db.get_conn() as conn:
        tr = [{"role": "ai", "text": "你好"}, {"role": "user", "text": text}]
        conn.execute("UPDATE session SET transcript = ?, started_at = ? WHERE id = ?",
                     (json.dumps(tr, ensure_ascii=False), (db.now() - timedelta(seconds=90)).strftime(db.TIME_FMT),
                      s["session_id"]))
    await svc.end_session(uid, s["session_id"], "finish")
    await svc.drain_tasks()
    return s["session_id"]


async def test_report_longterm():
    with db.get_conn() as c:
        drill_id = c.execute("SELECT id FROM drill WHERE owner_id IS NULL LIMIT 1").fetchone()[0]
    s1 = await run_session("r1", drill_id, "嗯，那个，我觉得这个方案可以，就是，嗯，再想想")
    s2 = await run_session("r1", drill_id, "我建议分两步走：第一步先试点，第二步再推广")
    d1, d2 = svc.get_session_detail("r1", s1), svc.get_session_detail("r1", s2)
    assert d1["report_status"] == "ready" and d1["longterm"] == {}           # 第一场没有历史
    assert d2["longterm"]["sessions"] == 1 and d2["longterm"]["avg"]         # 第二场对比的是第一场
    with db.get_conn() as c:
        assert memory.training_profile(c, "r1")["sessions"] == 2
    from app.services.prompts import build_report_messages
    msgs = build_report_messages({"title": "t", "description": "d", "user_role": "u", "ai_role": "a", "pressure_level": "低压",
                                  "training_goal": "g", "longterm_text": "最近 3 场训练；最弱的是应变能力"}, [], 60)
    assert "长期表现" in msgs[1]["content"] and "最弱的是应变能力" in msgs[1]["content"]
    print("✓ report long-term comparison")


# ---------------- 导入 ----------------

STRATEGY_MD = """# talktool-strategies

## 谋略：先礼后兵
- code: xianli_houbing
- 体系: 战国策 / 资治通鉴
- 出处: 民间智慧
- 领域: 谈判、为人处世、火星
- 框架: ask_first, nope_code
- 慎用: 否

### 原文
先礼后兵。

### 白话
先讲道理给台阶，对方不接再亮底线。

### 怎么做
1. 先私下沟通，给对方体面
2. 对方不接，再书面亮出底线

### 怎么说
我们先按合作的方式商量；如果谈不拢，我这边只能按合同办了。

### 常见误用
一上来就亮底牌。

## 谋略：曾国藩的拙诚
- code: zeng_zhuocheng
- 体系: 曾国藩家书
- 领域: 心态

### 白话
以拙破巧，以诚待人。

### 怎么做
- 说到做到
- 不耍小聪明

### 怎么说
这件事我没把握，但我会按时把每一步做扎实。
"""

ADVISOR_MD = """# talktool-advisors

## 谋士：老周
- code: laozhou
- 头像: 周
- 风格: 务实
- 体系: maoxuan, 战国策 / 资治通鉴

### 人设
国企老处长，先看人再看事，说话直白。
"""

COUNCIL_MD = """# talktool-councils

## 智囊团：职场新人团
- code: newbie
- 图标: 新
- 谋士: junshi, laozhou
- 体系: rujia, xiushen
- 领域: 职场

### 处理什么问题
刚工作一两年遇到的问题：不敢开口、被安排杂活、和带教关系。

### 特别要求
多鼓励，建议要小步可执行。

### 示例问题
- 带教总让我干杂活怎么办
- 第一次汇报很紧张
"""


def test_import():
    res = catalog_import.import_bytes(STRATEGY_MD.encode(), "s.md")
    assert res["strategies"] == {"added": 2, "updated": 0, "skipped": 0}, res
    assert any("火星" in w for w in res["warnings"]) and any("nope_code" in w for w in res["warnings"])
    s = st.get_strategy("xianli_houbing")
    assert s["school"] == "zhanguoce" and s["domains"] == ["谈判", "为人处世"] and s["framework_codes"] == ["ask_first"]
    assert len(s["how_to_do"]) == 2 and not s["caution"] and s["how_to_say"].startswith("我们先")
    assert any(x["code"] == "曾国藩家书" and x["group"] == "自定义" for x in st.schools())
    assert st.list_strategies(school="曾国藩家书")["total"] == 1
    # 重复导入：upsert 更新，add_only 跳过；导入的行不会被内置同步覆盖
    assert catalog_import.import_bytes(STRATEGY_MD.encode(), "s.md")["strategies"]["updated"] == 2
    assert catalog_import.import_bytes(STRATEGY_MD.encode(), "s.md", "add_only")["strategies"]["skipped"] == 2
    with db.get_conn() as c:
        assert c.execute("SELECT customized FROM strategy WHERE code = 'xianli_houbing'").fetchone()[0] == 1
    # 智囊团引用了还不存在的谋士 → 报错；先导谋士再导团
    raises(BadRequest, catalog_import.import_bytes, COUNCIL_MD.encode(), "c.md")
    res = catalog_import.import_bytes(ADVISOR_MD.encode(), "a.md")
    assert res["advisors"]["added"] == 1 and "谋士 +1" in res["summary"]
    res = catalog_import.import_bytes(COUNCIL_MD.encode(), "c.md")
    assert res["councils"]["added"] == 1
    c = workflow.get_council("newbie")
    assert c["advisors"] == ["junshi", "laozhou"] and len(c["examples"]) == 2 and c["requirement"].startswith("多鼓励")
    assert workflow.councils()[-1]["code"] == "general"              # 新团排在综合团前面
    assert prompt_store.get("council.newbie")["system"]               # 自动有默认提示词
    # 格式错误
    raises(BadRequest, catalog_import.import_bytes, "## 谋略：没 code\n- 体系: rujia\n### 白话\nx".encode(), "x.md")
    raises(BadRequest, catalog_import.import_bytes, "## 谋士：坏\n- code: my_bad\n### 人设\n很长的人设描述".encode(), "x.md")
    # 私人谋士（my_ 开头）不能被导入覆盖
    a = my_advisors.create("imp", {"name": "私人", "persona": "用户自己的私人谋士"})
    md = f"## 谋士：抢\n- code: {a['code']}\n### 人设\n想覆盖别人的私人谋士"
    raises(BadRequest, catalog_import.import_bytes, md.encode(), "x.md")
    print("✓ import strategies / advisors / councils")


async def test_gateway_nodes():
    """接网关时：提示词变量填对了，模型输出被规整（不在场的谋士丢掉、敏感记忆过滤）。"""
    from app import config
    from app.services import gateway
    seen = []
    a, b = workflow.roundtable_seats(workflow.get_council("upward"))[:2]

    async def fake_chat(messages, **kw):
        prompt = messages[-1]["content"]
        seen.append((kw.get("capability"), messages[0]["content"] + prompt))
        if "圆桌会议" in messages[0]["content"]:
            return json.dumps({"question": "接不接", "speeches": [
                {"advisor": a, "round": 1, "stance": "接", "text": "接下来是机会"},
                {"advisor": b, "round": 1, "stance": "不接", "text": "先保护自己"},
                {"advisor": "ghost", "round": 1, "stance": "?", "text": "不在场"},
                {"advisor": b, "round": 2, "stance": "反驳", "text": "烂项目背锅风险大", "reply_to": a}],
                "verdict": {"text": "有条件地接", "adopt": ["先谈资源"], "watch": "别口头答应"}}, ensure_ascii=False)
        if "整理智囊团的长期记忆" in messages[0]["content"]:
            return json.dumps({"summary": "直属上级", "items": ["看重数据", "看重数据", "最近在吃抗抑郁的药", "周一例会最忙"]},
                              ensure_ascii=False)
        raise AssertionError(prompt[:80])

    old_mock, old_chat = config.MOCK, gateway.chat
    config.MOCK, gateway.chat = False, fake_chat
    try:
        council = workflow.get_council("upward")
        rt, meta = await workflow.run_roundtable("g", "upward", "老板让我接烂项目", {"headline": "先谈条件"}, "", "（暂无）", 1)
        assert {s["advisor"] for s in rt["speeches"]} == {a, b} and rt["speeches"][-1]["reply_to_name"]
        assert seen[0][0] == "quality-chat" and "先谈条件" in seen[0][1] and "主持人（军师" in seen[0][1]
        assert all(a in workflow.roundtable_seats(council) for a in council["advisors"])
        with db.get_conn() as c:
            pid = memory.upsert_person(c, "g", "李总", [], "")
            for i in range(14):
                c.execute("""INSERT INTO memory_item(user_id, type, subject_id, text, created_at, updated_at)
                             VALUES (?,?,?,?,?,?)""", ("g", "fact", pid, f"条目{i}：内容各不相同{i * 13}", db.now_str(), db.now_str()))
        res = await memory.compact_subject("g", pid)
        with db.get_conn() as c:
            items = [r[0] for r in c.execute("SELECT text FROM memory_item WHERE subject_id = ?", (pid,))]
            summary = c.execute("SELECT summary FROM memory_subject WHERE id = ?", (pid,)).fetchone()[0]
        assert res["changed"] and items == ["看重数据", "周一例会最忙"] and summary == "直属上级", items
    finally:
        config.MOCK, gateway.chat = old_mock, old_chat
    print("✓ gateway nodes (roundtable / memory_compact)")


async def main():
    db.init_db()
    await test_followup()
    await test_roundtable()
    await test_my_advisors()
    await test_memory_maintain()
    await test_stats()
    await test_report_longterm()
    test_import()
    await test_gateway_nodes()
    print("ALL ADVISOR PLUS TESTS PASSED")


asyncio.run(main())
