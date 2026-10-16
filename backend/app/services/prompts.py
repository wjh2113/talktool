"""场景 System Prompt 模板 & 报告评估 Prompt。"""

PRESSURE_STYLE = {
    "低压": "态度友善、耐心，多鼓励和引导，用户卡壳时可以温和地给一点提示。",
    "中压": "态度正常偏挑剔，会对用户的回答提出合理质疑或追问细节，但不刻意刁难。",
    "高压": "态度强硬、情绪明显，会打断、追问施压、故意刁难，只有用户处理得当才会逐渐缓和。",
}

SCORE_DIMENSIONS = ["逻辑表达", "语言组织", "应变能力", "情绪管理"]


def build_system_prompt(drill: dict) -> str:
    if drill.get("system_prompt"):
        return drill["system_prompt"]
    pressure = drill.get("pressure_level", "低压")
    return f"""你正在进行一场沟通训练角色扮演。
【场景背景】{drill['description']}
【你的角色】{drill['ai_role']}
【用户角色】{drill['user_role']}
【压力模式】{pressure} —— {PRESSURE_STYLE.get(pressure, PRESSURE_STYLE['低压'])}
【训练目标】{drill['training_goal']}
【规则】
1. 你始终以“{drill['ai_role']}”的身份说话，不要跳出角色，不要提及自己是 AI，不要点评用户的表现。
2. 这是语音对话：全程口语化、简短自然，每次发言不超过 3 句话，不要使用列表、括号动作描写以外的书面格式。
3. 对话总时长控制在约 {drill['duration_min']} 分钟内；当训练目标基本达成或对话已充分展开时，用一句符合角色的话自然收尾。
4. 根据用户的回答真实地反应：说得好就认可或缓和，说得不好就继续追问或表达不满。
5. 如果用户的话明显没听清或很短，用角色口吻追问一句即可。"""


def build_report_messages(drill: dict, transcript: list, duration_sec: int, metrics_text: str = "") -> list:
    lines, n = [], 0
    for t in transcript:
        if t["role"] == "ai":
            lines.append(f"对方(AI)：{t['text']}")
        else:
            n += 1
            lines.append(f"用户[第{n}句]：{t['text']}")
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
【训练时长】{duration_sec} 秒
【表达数据】{metrics_text or '（无）'}

【对话记录】
{chr(10).join(lines)}

评估要求：
- 只评价“用户”的发言，从 {dims} 四个维度各打 1-10 分（整数），要严格、有区分度。
- highlights：2-3 条做得好的点，要引用或指向用户的具体说法。
- improvements：2-3 条改进建议，要具体到“可以怎么说”。
- turn_reviews：对用户的每一句（共 {n} 句）给出复盘：turn 为句子序号；better 是在同样情境下更好的说法
  （口语化、可以直接照着说，不超过 80 字）；tip 用一句话说明改在哪里（不超过 25 字）。
- detail_comment：用 Markdown 写详细点评（150-300 字），可结合表达数据（语速、口头禅、停顿）给建议。
- summary：一句话总评（不超过 30 字）。

严格按以下 JSON 结构输出，不要输出任何其他内容：
{{"scores": {{{scores_example}}}, "summary": "...", "highlights": ["..."], "improvements": ["..."],
"turn_reviews": [{{"turn": 1, "better": "...", "tip": "..."}}], "detail_comment": "..."}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_custom_drill_messages(description: str, pressure: str) -> list:
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
  "duration_min": 3}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_script_messages(drill: dict) -> list:
    system = "你是沟通表达教练，为训练场景写一段可以直接照着朗读练习的示范稿。只输出示范稿正文，不要标题和解释。"
    user = f"""【场景描述】{drill['description']}
【用户角色】{drill['user_role']}
【训练目标】{drill['training_goal']}
请以用户角色的口吻写一段示范发言：口语化、结构清晰（先表态再展开），120-200 字，适合朗读，不用括号和列表。"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
