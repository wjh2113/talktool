"""启动时把内置的谋略、谋士、智囊团同步进数据库。

规则：按 code 新增或更新；customized=1 的行（后台改过或导入的）不覆盖；代码里删掉的内置条目不删库（避免历史锦囊引用失效）。
"""
import json

from ..councils_data import ADVISORS, COUNCILS
from ..strategies_data import SCHOOLS, STRATEGIES


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def sync_advisor_content(conn) -> None:
    school_order = {k: i for i, k in enumerate(SCHOOLS)}
    for i, s in enumerate(STRATEGIES):
        vals = (s["school"], s["name"], s.get("sub", ""), s["origin"], s["plain"], _j(s["domains"]),
                _j(s["how_to_do"]), s["how_to_say"], _j(s["framework_codes"]), s["misuses"],
                1 if s["caution"] else 0, school_order.get(s["school"], 99) * 1000 + i)
        row = conn.execute("SELECT customized FROM strategy WHERE code = ?", (s["code"],)).fetchone()
        if row is None:
            conn.execute("""INSERT INTO strategy(school, name, sub, origin, plain, domains, how_to_do, how_to_say,
                            framework_codes, misuses, caution, sort_order, code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         vals + (s["code"],))
        elif not row[0]:
            conn.execute("""UPDATE strategy SET school=?, name=?, sub=?, origin=?, plain=?, domains=?, how_to_do=?,
                            how_to_say=?, framework_codes=?, misuses=?, caution=?, sort_order=? WHERE code=?""",
                         vals + (s["code"],))

    for i, a in enumerate(ADVISORS):
        vals = (a["name"], a["avatar"], _j(a["schools"]), a["persona"], a["style"], i)
        row = conn.execute("SELECT customized FROM advisor WHERE code = ?", (a["code"],)).fetchone()
        if row is None:
            conn.execute("""INSERT INTO advisor(name, avatar, schools, persona, style, sort_order, code)
                            VALUES (?,?,?,?,?,?,?)""", vals + (a["code"],))
        elif not row[0]:
            conn.execute("""UPDATE advisor SET name=?, avatar=?, schools=?, persona=?, style=?, sort_order=?
                            WHERE code=?""", vals + (a["code"],))

    for i, c in enumerate(COUNCILS):
        vals = (c["name"], c["icon"], c["desc"], _j(c["advisors"]), _j(c["schools"]), _j(c["domains"]),
                c["requirement"], _j(c["examples"]), i)
        row = conn.execute("SELECT customized FROM council WHERE code = ?", (c["code"],)).fetchone()
        if row is None:
            conn.execute("""INSERT INTO council(name, icon, description, advisors, schools, domains, requirement,
                            examples, sort_order, code) VALUES (?,?,?,?,?,?,?,?,?,?)""", vals + (c["code"],))
        elif not row[0]:
            conn.execute("""UPDATE council SET name=?, icon=?, description=?, advisors=?, schools=?, domains=?,
                            requirement=?, examples=?, sort_order=? WHERE code=?""", vals + (c["code"],))
