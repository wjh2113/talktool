"""智囊团工作流：意图识别 → 路由 → 智囊团出谋 → 后处理；以及追问、记忆提取。

每个节点用 prompt_store 里对应 key 的提示词（可在后台修改）；Mock 模式下用规则模拟，方便没接网关时联调界面。
"""
import json
import logging
import re

from .. import config
from ..db import get_conn, loads, row_to_dict
from . import gateway, prompt_store, generation_stream
from . import strategies as st

log = logging.getLogger("talktool.workflow")

RISKS = ("none", "safety", "self_harm", "illegal")
CONFIDENCE_ASK = 0.45   # 低于它：让用户在候选智囊团里点选


class WorkflowError(RuntimeError):
    pass


# ---------------- 智囊团配置 ----------------

def _council(row) -> dict:
    c = row_to_dict(row)
    for k in ("advisors", "schools", "domains", "examples"):
        c[k] = loads(c[k], [])
    c["enabled"] = bool(c["enabled"])
    return c


def councils(enabled_only: bool = True) -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM council " + ("WHERE enabled = 1 " if enabled_only else "") +
                            "ORDER BY sort_order, id").fetchall()
        advisors = {r["code"]: row_to_dict(r) for r in conn.execute("SELECT * FROM advisor")}
    out = []
    for r in rows:
        c = _council(r)
        c["advisor_list"] = [{"code": a, "name": advisors[a]["name"], "avatar": advisors[a]["avatar"],
                              "style": advisors[a]["style"]} for a in c["advisors"] if a in advisors]
        out.append(c)
    return out


def get_council(code: str) -> dict:
    for c in councils(enabled_only=False):
        if c["code"] == code:
            return c
    return next(c for c in councils(enabled_only=False) if c["code"] == "general")


def seat_codes(council: dict, extra: list = None) -> list:
    """在场谋士：智囊团的谋士 + 用户请来列席的私人谋士（最多 2 位）。"""
    return list(dict.fromkeys(list(council["advisors"]) + list(extra or [])[:2]))


def advisors_text(council: dict, extra: list = None) -> str:
    codes = seat_codes(council, extra)
    with get_conn() as conn:
        rows = {r["code"]: r for r in conn.execute("SELECT code, name, persona, owner_id FROM advisor")}
    out = []
    for a in codes:
        if a in rows:
            tag = "，用户自己请来的私人谋士" if rows[a]["owner_id"] else ""
            out.append(f"- {rows[a]['name']}（code: {a}{tag}）：{rows[a]['persona']}")
    return "\n".join(out)


def valid_extra(user_id: str, codes) -> list:
    """只保留属于该用户的私人谋士。"""
    codes = [c for c in (codes or []) if isinstance(c, str)][:2]
    if not codes:
        return []
    with get_conn() as conn:
        mine = {r[0] for r in conn.execute(
            f"SELECT code FROM advisor WHERE owner_id = ? AND code IN ({','.join('?' * len(codes))})", (user_id, *codes))}
    return [c for c in codes if c in mine]


def councils_menu() -> str:
    return "\n".join(f"{c['code']}：{c['name']}——{c['description']}" for c in councils())


# ---------------- 调模型 ----------------

async def _call(key: str, variables: dict, user_id: str, idem: tuple):
    messages, meta = prompt_store.render(key, variables)
    budget = meta["max_tokens"]
    for attempt in range(2):
        kwargs = dict(capability=meta["capability"], temperature=meta["temperature"], max_tokens=budget,
                      user_id=user_id, max_cost=config.MAX_COST_CONSULT, thinking=False,
                      idempotency_key=gateway.idem_key(key, meta["version"], budget, "stream-v1" if generation_stream.capture_for(key) else "direct", *idem))
        sink = generation_stream.capture_for(key)
        if sink:
            sink.begin(key, attempt)
            chunks = []
            try:
                async for delta in gateway.stream_chat(messages, **kwargs):
                    chunks.append(delta)
                    sink.feed(delta)
            finally:
                sink.feed('', force=True)
            text = ''.join(chunks)
        else:
            text = await gateway.chat(messages, **kwargs)
        if meta["output"] != "json":
            return text.strip(), meta
        try:
            data = gateway.extract_json(text)
            if not isinstance(data, dict) or not data:
                raise WorkflowError(f"{key} 返回的不是有效 JSON")
            return data, meta
        except (gateway.GatewayError, WorkflowError):
            if attempt:
                raise
            # 中文结构化输出可能耗尽额度而截断；提高预算重新生成，使用新的幂等键。
            budget = min(max(budget * 2, 1500), 8000)
            log.warning("%s JSON 不完整，提高输出预算至 %s 后重试一次", key, budget)



# ---------------- 节点：意图识别 ----------------

KEYWORDS = [
    ("finance", r"投资|理财|股票|基金|割肉|仓位|买房|存钱|亏了|理财"),
    ("startup", r"创业|合伙人|融资|投资人|股权|副业|开公司|辞职做"),
    ("negotiation", r"谈判|报价|涨价|降价|砍价|客户|供应商|回款|催款|offer|期望薪资|合同"),
    ("family", r"老公|老婆|伴侣|对象|男朋友|女朋友|爸|妈|父母|孩子|婆婆|岳母|亲戚|催婚"),
    ("upward", r"老板|领导|上级|[\u4e00-\u9fa5]总|晋升|加薪|涨薪|汇报|述职|站队|负责人"),
    ("team", r"下属|同事|团队|甩锅|抢功|跨部门|带人|管理"),
    ("social", r"借钱|帮忙|内推|拒绝|人情|朋友|邻居|人脉"),
    ("choice", r"跳槽|转行|辞职|选择|要不要|规划|迷茫"),
]
PEOPLE_RE = re.compile(r"(王总|李总|张总|刘总|陈总|[一-龥]总|老板|领导|老公|老婆|我妈|我爸|婆婆|同事[一-龥]?|客户)")


def _mock_intent(message: str, history: str) -> dict:
    text = f"{history}\n{message}"
    risk = "self_harm" if re.search(r"自杀|不想活|轻生|割腕", text) else \
        "safety" if re.search(r"家暴|打我|威胁我|跟踪我", text) else \
        "illegal" if re.search(r"报复|整死|搞垮他|造谣|偷拍", text) else "none"
    council = next((c for c, pat in KEYWORDS if re.search(pat, text)), "general")
    return {"council": council, "candidates": [], "confidence": 0.8 if council != "general" else 0.5,
            "title": re.sub(r"\s+", "", message)[:14], "counterpart": "", "people": list(dict.fromkeys(PEOPLE_RE.findall(text)))[:3],
            "goal": "", "urgency": "normal", "info_enough": len(text.strip()) >= 20, "missing": ["对方是谁、你想要什么结果"],
            "risk": risk, "summary": re.sub(r"\s+", " ", text).strip()[:150]}


def normalize_intent(raw: dict, message: str) -> dict:
    codes = {c["code"] for c in councils()}
    council = raw.get("council") if raw.get("council") in codes else "general"
    try:
        conf = max(0.0, min(1.0, float(raw.get("confidence", 0.7))))
    except (TypeError, ValueError):
        conf = 0.7
    risk = raw.get("risk") if raw.get("risk") in RISKS else "none"
    return {
        "council": council,
        "candidates": [c for c in (raw.get("candidates") or []) if c in codes and c != council][:2],
        "confidence": conf,
        "title": str(raw.get("title") or message)[:16],
        "counterpart": str(raw.get("counterpart") or "")[:30],
        "people": [str(p)[:12] for p in (raw.get("people") or []) if p][:5],
        "goal": str(raw.get("goal") or "")[:80],
        "urgency": raw.get("urgency") if raw.get("urgency") in ("high", "normal", "low") else "normal",
        "info_enough": raw.get("info_enough") is not False,
        "missing": [str(m)[:40] for m in (raw.get("missing") or [])][:4],
        "risk": risk,
        "summary": str(raw.get("summary") or message)[:300],
    }


async def run_intent(user_id: str, message: str, history: str, memory_text: str, consult_id: int) -> tuple:
    if config.MOCK:
        raw, meta = _mock_intent(message, history), {"version": 0}
    else:
        raw, meta = await _call("intent", {"message": message, "history": history or "（无）", "memory": memory_text,
                                           "councils": councils_menu()}, user_id, (consult_id, message, history))
    return normalize_intent(raw, message), meta


def route(intent: dict, clarified: bool, skip_clarify: bool = False) -> str:
    """返回 safety / clarify / choose / council。"""
    if intent["risk"] != "none":
        return "safety"
    if not intent["info_enough"] and not clarified and not skip_clarify:
        return "clarify"
    if intent["confidence"] < CONFIDENCE_ASK and intent["candidates"] and not clarified:
        return "choose"
    return "council"


# ---------------- 节点：追问 / 安全回复 ----------------

async def run_clarify(user_id: str, message: str, intent: dict, memory_text: str, consult_id: int) -> dict:
    if config.MOCK:
        raw = {"intro": "为了给你更准的建议，先问两个问题：",
               "questions": [{"q": "对方是谁？和你是什么关系？", "options": ["上级", "同事", "客户", "家人"]},
                             {"q": "你最想要的结果是什么？", "options": ["争取利益", "化解矛盾", "体面拒绝", "还没想好"]}]}
    else:
        raw, _ = await _call("clarify", {"message": message, "missing": "、".join(intent["missing"]) or "关键细节",
                                         "memory": memory_text}, user_id, (consult_id, message))
    if config.MOCK:
        await generation_stream.mock("clarify", raw)
    qs = []
    for q in (raw.get("questions") or [])[:3]:
        if isinstance(q, dict) and q.get("q"):
            qs.append({"q": str(q["q"])[:60], "options": [str(o)[:20] for o in (q.get("options") or [])][:4]})
    return {"intro": str(raw.get("intro") or "先问几个问题：")[:60], "questions": qs}


SAFETY_FALLBACK = {
    "self_harm": "听起来你现在非常难受，谢谢你愿意说出来。请先联系一位你信任的人陪着你，也可以拨打心理援助热线 12356；如果有立即的危险，请拨打 120 或 110。你不需要一个人扛着。",
    "safety": "你的安全最重要。如果现在有危险，请先离开当前环境，联系信任的人，必要时拨打 110。安全之后，我们再一起想后面怎么处理。",
    "illegal": "这件事智囊不能帮着做，它可能带来法律风险，也会伤害到你自己。如果你愿意，我们可以换个思路，看看怎么用正当的方式维护你的利益。",
}


async def run_safety(user_id: str, message: str, risk: str, consult_id: int) -> str:
    if config.MOCK:
        return SAFETY_FALLBACK.get(risk, SAFETY_FALLBACK["safety"])
    try:
        text, _ = await _call("safety", {"message": message, "risk": risk}, user_id, (consult_id, message))
        return text[:600] or SAFETY_FALLBACK.get(risk, "")
    except Exception as e:  # noqa: BLE001  安全回复不能失败
        log.warning("安全回复生成失败，用兜底文案：%s", e)
        return SAFETY_FALLBACK.get(risk, SAFETY_FALLBACK["safety"])


# ---------------- 节点：智囊团出谋 ----------------

def _clip(v, n):
    return str(v or "").strip()[:n]


def normalize_plan(raw: dict, strategy_codes: set, framework_codes: set, advisor_codes: list) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    goal = raw.get("goal") if isinstance(raw.get("goal"), dict) else {}
    plan = {
        "headline": _clip(raw.get("headline"), 80),
        "situation": _clip(raw.get("situation"), 500),
        "their_concerns": _clip(raw.get("their_concerns"), 200),
        "goal": {"best": _clip(goal.get("best"), 80), "acceptable": _clip(goal.get("acceptable"), 80),
                 "bottom": _clip(goal.get("bottom"), 80)},
        "strategies": [], "actions": [], "lines": [], "risks": [], "donts": [], "advisor_views": [],
        "rehearsal": {}, "summary": _clip(raw.get("summary"), 300),
    }
    for s in raw.get("strategies") or []:
        if isinstance(s, dict) and s.get("code") in strategy_codes and len(plan["strategies"]) < 3:
            if s["code"] not in [x["code"] for x in plan["strategies"]]:
                plan["strategies"].append({"code": s["code"], "use": _clip(s.get("use"), 160)})
    for a in (raw.get("actions") or [])[:8]:
        if isinstance(a, dict) and a.get("text"):
            plan["actions"].append({"text": _clip(a["text"], 120), "when": _clip(a.get("when"), 30)})
        elif isinstance(a, str) and a.strip():
            plan["actions"].append({"text": _clip(a, 120), "when": ""})
    for ln in (raw.get("lines") or [])[:5]:
        if isinstance(ln, dict) and ln.get("text"):
            fw = ln.get("framework") if ln.get("framework") in framework_codes else ""
            plan["lines"].append({"moment": _clip(ln.get("moment"), 30), "text": _clip(ln["text"], 300),
                                  "framework": fw, "why": _clip(ln.get("why"), 120)})
    for r in (raw.get("risks") or [])[:4]:
        if isinstance(r, dict) and (r.get("if") or r.get("then")):
            plan["risks"].append({"if": _clip(r.get("if"), 100), "then": _clip(r.get("then"), 160)})
    plan["donts"] = [_clip(d, 80) for d in (raw.get("donts") or []) if d][:4]
    for v in raw.get("advisor_views") or []:
        if isinstance(v, dict) and v.get("advisor") in advisor_codes and v.get("view"):
            plan["advisor_views"].append({"advisor": v["advisor"], "view": _clip(v["view"], 160)})
    reh = raw.get("rehearsal") if isinstance(raw.get("rehearsal"), dict) else {}
    plan["rehearsal"] = {"ai_role": _clip(reh.get("ai_role"), 80), "user_role": _clip(reh.get("user_role"), 40),
                         "opening_line": _clip(reh.get("opening_line"), 120), "goal": _clip(reh.get("goal"), 80)}
    if not plan["headline"] or not (plan["actions"] or plan["lines"]):
        raise WorkflowError("锦囊内容不完整")
    return plan


def _mock_plan(council: dict, catalog: list, fws: list, situation: str) -> dict:
    s1, s2 = catalog[0], catalog[1]
    f1 = fws[0]["code"]
    return {
        "headline": f"（Mock）先摸清对方的真实顾虑，再用「{s1['name']}」争取主动",
        "situation": f"（Mock）{situation[:120]}",
        "their_concerns": "对方可能担心风险和面子",
        "goal": {"best": "达成你的诉求", "acceptable": "先达成部分共识", "bottom": "关系不破裂"},
        "strategies": [{"code": s1["code"], "use": s1["plain"][:60]}, {"code": s2["code"], "use": s2["plain"][:60]}],
        "actions": [{"text": "本周内约对方私下聊 20 分钟", "when": "本周内"},
                    {"text": "聊之前把事实和数据整理成一页纸", "when": "约谈前"},
                    {"text": "聊完当天发一条消息确认共识", "when": "当天"}],
        "lines": [{"moment": "开场", "text": "我想跟您聊聊这件事，主要是想听听您的想法。", "framework": f1, "why": "先让对方开口"},
                  {"moment": "对方反对时", "text": "我理解您的顾虑，我们看看有没有两边都能接受的办法。", "framework": fws[1]["code"],
                   "why": "不正面顶撞"}],
        "risks": [{"if": "对方说再想想", "then": "约一个具体的下次时间"}],
        "donts": ["当众争对错", "一上来就摊牌"],
        "advisor_views": [{"advisor": a, "view": "（Mock）我的看法是先稳住，再推进。"} for a in council["advisors"]],
        "rehearsal": {"ai_role": "你要沟通的对方，有顾虑但讲道理", "user_role": "你自己",
                      "opening_line": "你找我有什么事？", "goal": "清楚表达诉求，回应顾虑"},
        "summary": situation[:150],
    }


async def run_council(user_id: str, council_code: str, situation: str, memory_text: str, consult_id: int,
                      extra: list = None) -> tuple:
    """返回 (plan, meta)；meta 含使用的提示词版本。extra = 列席的私人谋士。"""
    council = get_council(council_code)
    seats = seat_codes(council, extra)
    catalog = st.catalog_for(council, situation)
    fws = st.frameworks_for(catalog)
    key = f"council.{council['code']}"
    if config.MOCK:
        raw, meta = _mock_plan(dict(council, advisors=seats), catalog, fws, situation), {"version": 0}
    else:
        variables = {"council_name": council["name"], "advisors": advisors_text(council, extra), "situation": situation,
                     "memory": memory_text, "strategies": st.catalog_text(catalog), "frameworks": st.frameworks_text(fws)}
        raw, meta = await _call(key, variables, user_id, (consult_id, situation, *seats))
    if config.MOCK:
        await generation_stream.mock(key, raw)
    plan = normalize_plan(raw, {s["code"] for s in catalog}, {f["code"] for f in fws}, seats)
    return plan, {"prompt_versions": {key: meta.get("version", 0)}, "council": council["code"]}


# ---------------- 节点：追问 / 修改锦囊 ----------------

async def run_followup(user_id: str, council_code: str, summary: str, plan: dict, history: str, message: str,
                       memory_text: str, consult_id: int, turn: int, extra: list = None) -> tuple:
    council = get_council(council_code)
    seats = seat_codes(council, extra)
    catalog = st.catalog_for(council, summary + message)
    fws = st.frameworks_for(catalog, [ln.get("framework") for ln in plan.get("lines", []) if ln.get("framework")])
    if config.MOCK:
        update = bool(re.search(r"改|换|如果|不想|结果", message))
        new = dict(plan, headline=f"（Mock 已调整）{plan.get('headline', '')}"[:80]) if update else None
        raw = {"reply": f"（Mock）关于「{message[:20]}」：我的建议是先稳住节奏，按锦囊第一步推进。", "update_plan": update,
               "plan": new, "summary": summary}
        meta = {"version": 0}
    else:
        variables = {"council_name": council["name"], "advisors": advisors_text(council, extra), "summary": summary,
                     "plan": json.dumps(plan, ensure_ascii=False), "history": history, "message": message,
                     "memory": memory_text, "strategies": st.catalog_text(catalog), "frameworks": st.frameworks_text(fws)}
        raw, meta = await _call("followup", variables, user_id, (consult_id, turn, message))
    if config.MOCK:
        await generation_stream.mock("followup", raw)
    new_plan = None
    if raw.get("update_plan") and isinstance(raw.get("plan"), dict):
        try:
            new_plan = normalize_plan(raw["plan"], {s["code"] for s in catalog} | {s["code"] for s in plan.get("strategies", [])},
                                      {f["code"] for f in fws}, seats)
        except WorkflowError:
            new_plan = None
    reply = _clip(raw.get("reply"), 800) or ("锦囊已按你的情况更新。" if new_plan else "收到。")
    return {"reply": reply, "plan": new_plan, "summary": _clip(raw.get("summary"), 300) or summary}, \
        {"prompt_versions": {"followup": meta.get("version", 0)}}


# ---------------- 节点：记忆提取 ----------------

def _mock_memory(conversation: str, intent: dict) -> dict:
    people = [{"name": p, "aliases": [], "relation": "", "facts": []} for p in intent.get("people", [])]
    profile = []
    m = re.search(r"我是(做|一名|个)?([一-龥A-Za-z]{2,10})", conversation)
    if m:
        profile.append(f"是{m.group(2)}")
    forget = re.findall(r"忘掉(.{2,12})", conversation)
    return {"profile": profile, "people": people,
            "case": {"title": intent.get("title", ""), "goal": intent.get("goal", ""), "update": "", "status": "open"},
            "forget": forget}


async def run_memory_extract(user_id: str, conversation: str, existing: str, intent: dict, key: tuple) -> dict:
    if config.MOCK:
        return _mock_memory(conversation, intent)
    data, _ = await _call("memory_extract", {"memory": existing, "conversation": conversation}, user_id, key)
    return data


# ---------------- 节点：圆桌会议 ----------------

MODERATOR = "junshi"


def _advisor_names(codes: list) -> dict:
    with get_conn() as conn:
        return {r["code"]: r["name"] for r in conn.execute("SELECT code, name FROM advisor")
                if r["code"] in codes}


def roundtable_seats(council: dict, extra: list = None) -> list:
    """圆桌至少 3 位：智囊团的谋士 + 列席谋士，不够时请军师、心理顾问补位。"""
    seats = seat_codes(council, extra)
    for c in (MODERATOR, "xinli", "zhanlue"):
        if len(seats) >= 3:
            break
        if c not in seats:
            seats.append(c)
    return seats[:5]


def normalize_roundtable(raw: dict, seats: list) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    names = _advisor_names(seats)
    speeches = []
    for sp in (raw.get("speeches") or [])[:10]:
        if not isinstance(sp, dict) or sp.get("advisor") not in seats or not sp.get("text"):
            continue
        rnd = 2 if str(sp.get("round")) == "2" or sp.get("reply_to") else 1
        reply_to = sp.get("reply_to") if sp.get("reply_to") in seats and sp.get("reply_to") != sp["advisor"] else ""
        speeches.append({"advisor": sp["advisor"], "name": names.get(sp["advisor"], sp["advisor"]), "round": rnd,
                         "stance": _clip(sp.get("stance"), 30), "text": _clip(sp["text"], 240), "reply_to": reply_to,
                         "reply_to_name": names.get(reply_to, "")})
    v = raw.get("verdict") if isinstance(raw.get("verdict"), dict) else {}
    verdict = {"text": _clip(v.get("text"), 300), "adopt": [_clip(x, 80) for x in (v.get("adopt") or []) if x][:4],
               "watch": _clip(v.get("watch"), 100)}
    if len(speeches) < 2 or not verdict["text"]:
        raise WorkflowError("圆桌会议内容不完整")
    return {"question": _clip(raw.get("question"), 60), "speeches": speeches, "verdict": verdict,
            "consensus": [_clip(x, 80) for x in (raw.get("consensus") or []) if x][:3],
            "moderator": MODERATOR, "moderator_name": _advisor_names([MODERATOR]).get(MODERATOR, "军师")}


def _mock_roundtable(seats: list, topic: str) -> dict:
    a, b = seats[0], seats[1]
    speeches = [{"advisor": c, "round": 1, "stance": ["先稳后攻", "当面摊牌", "先照顾情绪"][i % 3],
                 "text": f"（Mock）我主张{['先稳住，摸清底牌再动', '直接把诉求讲清楚，拖久了更被动', '先处理关系和情绪，再谈事'][i % 3]}。"}
                for i, c in enumerate(seats)]
    speeches.append({"advisor": b, "round": 2, "stance": "反对拖延", "text": "（Mock）一直摸底会错过窗口期。", "reply_to": a})
    speeches.append({"advisor": a, "round": 2, "stance": "反对冒进", "text": "（Mock）没摸清就摊牌，容易一次谈崩。", "reply_to": b})
    return {"question": topic or "先稳还是先攻", "speeches": speeches,
            "verdict": {"text": "（Mock）两边都有道理：先用一周摸清对方顾虑，再带着方案当面谈，不要无限期拖。",
                        "adopt": ["本周内私下摸底", "下周带方案当面谈"], "watch": "别在公开场合摊牌"},
            "consensus": ["目标一致：既拿到结果又不伤关系"]}


async def run_roundtable(user_id: str, council_code: str, situation: str, plan: dict, topic: str, memory_text: str,
                         consult_id: int, extra: list = None, turn: int = 0) -> tuple:
    council = get_council(council_code)
    seats = roundtable_seats(council, extra)
    if config.MOCK:
        raw, meta = _mock_roundtable(seats, topic), {"version": 0}
    else:
        names = _advisor_names([MODERATOR])
        brief = {k: plan.get(k) for k in ("headline", "goal", "strategies", "actions", "lines") if plan.get(k)}
        variables = {"situation": situation, "advisors": advisors_text({"advisors": seats}),
                     "plan": json.dumps(brief, ensure_ascii=False)[:2500], "topic": topic or "锦囊的思路对不对、有没有更好的打法",
                     "memory": memory_text, "moderator": names.get(MODERATOR, "军师")}
        raw, meta = await _call("roundtable", variables, user_id, (consult_id, "rt", turn, topic, *seats))
    if config.MOCK:
        await generation_stream.mock("roundtable", raw)
    return normalize_roundtable(raw, seats), {"prompt_versions": {"roundtable": meta.get("version", 0)}}


# ---------------- 节点：记忆整理 ----------------

def _mock_compact(items: list, limit: int) -> dict:
    keep = list(dict.fromkeys(items))[-limit:]
    return {"summary": "（Mock 整理）" + (keep[-1][:20] if keep else ""), "items": keep}


async def run_memory_compact(user_id: str, kind: str, name: str, items: list, limit: int, subject_id: int) -> dict:
    if config.MOCK:
        return _mock_compact(items, limit)
    text = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(items))
    data, _ = await _call("memory_compact", {"kind": "人物卡" if kind == "person" else "事件线", "name": name,
                                             "items": text, "limit": limit}, user_id, ("compact", subject_id, text))
    return data
