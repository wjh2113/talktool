"""谋略库汇总：体系定义 + 全部内置谋略。新增谋略写到 strategies_cn / cn2 / 36 / west / more，或在后台导入。"""
from .strategies_36 import ZH36
from .strategies_cn import CN
from .strategies_cn2 import CN2
from .strategies_more import MORE
from .strategies_west import WEST

# 体系：code → (名称, 分组, 简介)
SCHOOLS = {
    "maoxuan": ("毛泽东选集", "中国经典", "矛盾分析、调查研究、持久战、集中兵力、统一战线等方法论"),
    "sunzi": ("孙子兵法", "中国经典", "知己知彼、先胜后战、避实击虚的竞争与博弈原则"),
    "sanshiliu": ("三十六计", "中国经典", "六套 36 计，标注正用与慎用"),
    "guiguzi": ("鬼谷子", "中国经典", "捭阖、揣摩、飞箝等说服与试探之术"),
    "zhanguoce": ("战国策 / 资治通鉴", "中国经典", "进言、借势、自荐等谋略故事"),
    "rujia": ("儒家", "中国经典", "论语、孟子、中庸里的为人处世之道"),
    "daojia": ("道家", "中国经典", "道德经、庄子里的以柔克刚与知止"),
    "fajia": ("法家（慎用）", "中国经典", "韩非子的法、术、势与进言之难"),
    "yijing": ("易经", "中国经典", "时位、谦卦、亢龙有悔等进退之道"),
    "xiushen": ("曾国藩 / 王阳明 / 菜根谭", "中国经典", "结硬寨打呆仗、知行合一、事上磨练"),
    "shiji": ("史记与名臣故事", "中国经典", "萧规曹随、负荆请罪、三顾茅庐、兼听则明等用人与处世故事"),
    "lingdao": ("中国式管理与领导", "中国经典", "以身作则、知人善任、复盘、会前通气、带着方案找领导"),
    "xinfa": ("心学与心态修炼", "中国经典", "破心中贼、致良知、慎独、觉察情绪、接受最坏的结果"),
    "ziliao": ("为人处世与谈判笔记", "中国经典", "资料 A / D：DISC、高情商、取势三张牌、红白脸"),
    "nego": ("谈判与博弈", "西方经典", "哈佛原则谈判、BATNA、囚徒困境、锚定"),
    "influence": ("影响力与说服", "西方经典", "互惠、承诺一致、社会认同、喜好、权威、稀缺、修辞三要素"),
    "interpersonal": ("人际与沟通", "西方经典", "卡耐基、非暴力沟通、关键对话、PAC、冲突模型"),
    "management": ("管理与领导", "西方经典", "情境领导、OKR、德鲁克、高效能习惯、SBI 反馈"),
    "philosophy": ("哲学与心态", "西方经典", "斯多葛、第一性原理、逆向思考、认知偏差"),
    "strategy": ("战略", "西方经典", "克劳塞维茨、五力、SWOT、蓝海"),
    "startup": ("创业与商业", "西方经典", "精益创业、从 0 到 1、商业模式、单位经济、融资"),
    "power": ("权术（慎用）", "西方经典", "君主论与权力法则类观点，只用于识别和防范"),
    "invest_value": ("价值投资", "投资理财", "能力圈、安全边际、市场先生、护城河"),
    "invest_risk": ("风险与周期", "投资理财", "第二层次思维、周期、反脆弱、黑天鹅、杠杆、流动性、识别骗局"),
    "behavior": ("行为金融与决策", "投资理财", "损失厌恶、心理账户、过度自信、羊群效应、事前验尸、决策日志"),
    "finance_basic": ("个人理财基础", "投资理财", "应急金、复利、量入为出、资产配置、保障"),
}

DOMAINS = ["职场", "生活", "为人处世", "谈判", "管理", "心态", "投资理财", "创业"]

STRATEGIES = CN + ZH36 + CN2 + WEST + MORE


def validate(framework_codes=None) -> list:
    """返回问题列表（测试和启动时检查用）。"""
    problems, seen = [], set()
    for s in STRATEGIES:
        if s["code"] in seen:
            problems.append(f"重复 code：{s['code']}")
        seen.add(s["code"])
        if s["school"] not in SCHOOLS:
            problems.append(f"{s['code']}：未知体系 {s['school']}")
        if not (s["name"] and s["plain"] and s["how_to_do"] and s["how_to_say"]):
            problems.append(f"{s['code']}：缺字段")
        bad = [d for d in s["domains"] if d not in DOMAINS]
        if bad:
            problems.append(f"{s['code']}：未知领域 {bad}")
        if framework_codes is not None:
            unknown = [c for c in s["framework_codes"] if c not in framework_codes]
            if unknown:
                problems.append(f"{s['code']}：未知表达框架 {unknown}")
    return problems
