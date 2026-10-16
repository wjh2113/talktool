"""训练报告生成：边界判定（too_short / abandoned）+ LLM 结构化评估。"""
from .. import config
from . import gateway
from .prompts import SCORE_DIMENSIONS, build_report_messages

TOO_SHORT_TEXT = "本次对话时长过短，无法生成报告，可重新练习生成。"
ABANDONED_TEXT = "本次会话已主动放弃，未生成报告，可重新练习生成。"
FAILED_TEXT = "报告生成失败，可稍后重试或重新练习。"


def decide_status(reason: str, duration_sec: int, user_turns: int) -> str:
    """
    reason: finish = 用户点击“结束训练”；exit = 中途返回/关闭页面
    规则（还原参考产品）：
      - 中途退出且没有有效对话          → abandoned（主动放弃）
      - 时长 < MIN_DURATION_SEC 或用户发言不足 → too_short（时长过短）
      - 其他                            → completed（生成报告）
    """
    if reason == "exit" and user_turns == 0:
        return "abandoned"
    if duration_sec < config.MIN_DURATION_SEC or user_turns < config.MIN_USER_TURNS:
        return "too_short"
    return "completed"


def _clamp_score(v) -> int:
    try:
        return max(1, min(10, int(round(float(v)))))
    except (TypeError, ValueError):
        return 5


def _user_texts(transcript: list) -> list:
    return [t["text"] for t in transcript or [] if t.get("role") == "user"]


def normalize_turn_reviews(raw_list, transcript: list) -> list:
    """把 LLM 给的逐句复盘对齐到用户的每一句原话。"""
    users = _user_texts(transcript)
    by_turn = {}
    for i, item in enumerate(raw_list if isinstance(raw_list, list) else []):
        if not isinstance(item, dict):
            continue
        try:
            turn = int(item.get("turn") or i + 1)
        except (TypeError, ValueError):
            turn = i + 1
        better = str(item.get("better") or "").strip()
        if better and 1 <= turn <= len(users):
            by_turn.setdefault(turn, {"better": better[:200], "tip": str(item.get("tip") or "").strip()[:60]})
    return [{"turn": n, "user_text": users[n - 1], **v} for n, v in sorted(by_turn.items())]


def normalize_report(raw: dict, transcript: list = None) -> dict:
    scores_in = raw.get("scores") or {}
    scores = {d: _clamp_score(scores_in.get(d)) for d in SCORE_DIMENSIONS}
    as_list = lambda v: [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])
    return {
        "scores": scores,
        "total_score": round(sum(scores.values()) / len(scores) * 10),  # 百分制
        "summary": str(raw.get("summary") or "").strip(),
        "highlights": as_list(raw.get("highlights"))[:5],
        "improvements": as_list(raw.get("improvements"))[:5],
        "detail_comment": str(raw.get("detail_comment") or "").strip(),
        "turn_reviews": normalize_turn_reviews(raw.get("turn_reviews"), transcript),
    }


def mock_report(transcript: list) -> dict:
    reviews = [{"turn": i + 1, "better": "我的看法有两点：第一，首次拜访用统一的需求清单把客户痛点问清楚；第二，每周复盘一次丢单原因。",
                "tip": "先给结论，再分点展开"} for i in range(len(_user_texts(transcript)))]
    return normalize_report({
        "turn_reviews": reviews,
        "scores": {"逻辑表达": 7, "语言组织": 6, "应变能力": 7, "情绪管理": 8},
        "summary": "（Mock 报告）表态及时，展开还可以更有条理",
        "highlights": ["被点名后能第一时间表态，没有冷场", "能结合自己接触客户的经验来谈"],
        "improvements": [
            "先给结论再展开，例如：“我的建议有两点：第一……第二……”",
            "补充一个具体案例或数据，增强说服力",
        ],
        "detail_comment": "**整体表现**：回应及时、态度积极。\n\n**参考示范**：“谢谢王总。我的看法是转化率卡在需求挖掘这一步。"
                          "建议有两点：第一，首次拜访用统一的需求清单；第二，每周复盘丢单原因。上季度我按这个方法跟进的 5 个客户成交了 3 个。”\n\n"
                          "> 这是 Mock 模式下的示例报告，配置网关 Key 后会由大模型根据真实对话生成。",
    }, transcript)


async def generate_report(drill: dict, transcript: list, duration_sec: int, metrics_text: str = "") -> dict:
    if config.MOCK:
        return mock_report(transcript)
    msgs = build_report_messages(drill, transcript, duration_sec, metrics_text)
    text = await gateway.chat(msgs, capability=config.REPORT_CAPABILITY, temperature=0.3, max_tokens=2500)
    return normalize_report(gateway.extract_json(text), transcript)
