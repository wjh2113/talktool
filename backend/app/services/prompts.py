"""场景 System Prompt 模板 & 报告评估 Prompt。"""

PRESSURE_STYLE = {
    "低压": "友善耐心，多鼓励，对方卡壳可温和提示",
    "中压": "偏挑剔，合理质疑、追问细节，不刻意刁难",
    "高压": "强硬有情绪，打断、施压、刁难，对方处理得当才缓和",
}

SCORE_DIMENSIONS = ["逻辑表达", "语言组织", "应变能力", "情绪管理"]


def build_system_prompt(drill: dict) -> str:
    """对练角色设定（精简版：每轮都会发送，越短越省 Token）。"""
    if drill.get("system_prompt"):
        return drill["system_prompt"]
    pressure = drill.get("pressure_level", "低压")
    return f"""沟通训练角色扮演。你扮演：{drill['ai_role']}。对方（用户）扮演：{drill['user_role']}。
场景：{drill['description']}
态度：{pressure}，{PRESSURE_STYLE.get(pressure, PRESSURE_STYLE['低压'])}。
规则：始终保持角色，不提自己是 AI，不点评对方；口语化，每次最多 3 句，不用列表；按对方表现真实反应；
约 {drill['duration_min']} 分钟内，目标达成时用一句话自然收尾；没听清就追问一句。"""


def build_report_messages(drill: dict, transcript: list, duration_sec: int, metrics_text: str = "") -> list:
    lines, n = [], 0
    for t in transcript:
        if t["role"] == "ai":
            lines.append(f"对方(AI)：{t['text']}")
        else:
            n += 1
            lines.append(f"用户：{t['text']}")
    dims = "、".join(SCORE_DIMENSIONS)
    scores_example = ", ".join(f'"{d}": 7' for d in SCORE_DIMENSIONS)
    system = "你是一名资深的沟通表达教练，擅长根据对话记录给出专业、具体、可执行的反馈。只输出 JSON。"
    user = f"""请评估用户在下面这场沟通训练中的表现。

【场景】{drill['title']}
【场景描述】{drill['description']}
【用户角色】{drill['user_role']}
【对方角色】{drill['ai_role']}
【压力等级】{drill['pressure_level']}
【训练目标】{drill['training_goal']}
【推荐表达框架】{drill.get('guide_text') or '（无）'}
【训练时长】{duration_sec} 秒
【表达数据】{metrics_text or '（无）'}

【对话记录】
{chr(10).join(lines)}

评估要求：
- 只评价“用户”的发言，从 {dims} 四个维度各打 1-10 分（整数），要严格、有区分度。
- highlights：2-3 条做得好的点，要引用或指向用户的具体说法。
- improvements：2-3 条改进建议，要具体到“可以怎么说”。
- detail_comment：用 Markdown 写详细点评（150-300 字），可结合表达数据（语速、口头禅、停顿）给建议；
  如果有推荐表达框架，点评用户是否用上了框架、哪一步缺失，并给出按框架重组后的示范。
- summary：一句话总评（不超过 30 字）。

严格按以下 JSON 结构输出，不要输出任何其他内容：
{{"scores": {{{scores_example}}}, "summary": "...", "highlights": ["..."], "improvements": ["..."], "detail_comment": "..."}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_turn_review_messages(drill: dict, transcript: list) -> list:
    """逐句复盘（按需生成）：只发每句用户发言和它前面那句 AI 的话。"""
    lines, n, last_ai = [], 0, ""
    for t in transcript:
        if t["role"] == "ai":
            last_ai = t["text"]
        else:
            n += 1
            lines.append(f"[{n}] 对方：{last_ai}\n    用户：{t['text']}")
    system = "你是沟通表达教练。只输出 JSON。"
    fw = f"\n推荐表达框架：{drill['guide_text']}（更好的说法尽量体现这些框架的结构）" if drill.get("guide_text") else ""
    user = f"""场景：{drill['title']}（用户角色：{drill['user_role']}；训练目标：{drill['training_goal']}）{fw}
下面是用户的 {n} 句发言及对方当时说的话：
{chr(10).join(lines)}

为每一句给出复盘：better 是同样情境下更好的说法（口语化、可以直接照着说，不超过 80 字）；tip 一句话说明改在哪里（不超过 25 字）。
只输出：{{"turn_reviews": [{{"turn": 1, "better": "...", "tip": "..."}}]}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_custom_drill_messages(description: str, pressure: str, framework_menu: str = "") -> list:
    system = ("你是沟通训练课程设计师，把用户描述的真实沟通情境改写成一个可以和 AI 语音对练的角色扮演场景。只输出 JSON。"
              "如果描述涉及违法、伤害他人、色情或与沟通训练无关的内容，输出 {\"error\": \"原因\"}。")
    user = f"""用户描述：{description}
压力等级：{pressure}（{PRESSURE_STYLE.get(pressure, PRESSURE_STYLE['中压'])}）

请输出 JSON：
{{"title": "训练标题（12-24 字，概括情境与目标）",
  "description": "场景描述（120-220 字，第二人称“你是……”，包含你的角色、背景、对方如何开场、你的训练任务）",
  "ai_role": "AI 扮演的角色（含身份、性格、态度，30 字内）",
  "user_role": "用户的角色（15 字内）",
  "training_goal": "训练目标（考察的 2-3 个能力点，30 字内）",
  "opening_line": "AI 角色的第一句话（口语化，符合压力等级，40 字内）",
  "duration_min": 3,
  "frameworks": [{{"code": "从下面的框架清单里选 1-2 个最合适的 code", "example": "用这个框架在本场景下的示范说法（60 字内）"}}],
  "pitfalls": ["本场景常见误区（2-3 条，每条 15 字内）"]}}

可选的表达框架清单（code:名称）：
{framework_menu}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_script_messages(drill: dict) -> list:
    system = "你是沟通表达教练，为训练场景写一段可以直接照着朗读练习的示范稿。只输出示范稿正文，不要标题和解释。"
    user = f"""【场景描述】{drill['description']}
【用户角色】{drill['user_role']}
【训练目标】{drill['training_goal']}
请以用户角色的口吻写一段示范发言：口语化、结构清晰（先表态再展开），120-200 字，适合朗读，不用括号和列表。"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
