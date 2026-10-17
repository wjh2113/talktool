"""场景库 Markdown / ZIP 导入：python3 -m tests.test_catalog_import（在 backend 目录）"""
import io
import os
import sys
import tempfile
import zipfile

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=tmp, GATEWAY_API_KEY="", MOCK_MODE="true",
                  ADMIN_USERNAME="boss", ADMIN_PASSWORD="boss-pass-1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db  # noqa: E402
from app.db import get_conn  # noqa: E402
from app.services import catalog_import  # noqa: E402
from app.services.sessions import BadRequest  # noqa: E402

SAMPLE_CATALOG = """# talktool-catalog v1

# 分类：导入测试分类

## 场景：导入测试场景
副标题：这是副标题

### 训练：导入测试训练甲

- 压力：中压
- 时长分钟：3
- 用户角色：项目负责人
- AI角色：技术部张工，忙碌但讲理
- 训练目标：换位思考、提出协作方案
- 开场白：又是你们市场部？排期满了。

#### 场景描述

你是市场部负责人，需要技术部支援一个落地页。对方说排期满了，请你争取支持。

#### 常见误区

- 一上来就说老板定的
- 不给缩小范围的选项

#### 推荐框架

- prep｜我认为可以先做简版落地页。
- need_formula｜为了共同目标，我需要……

### 训练：导入测试训练乙

- 压力：低压
- 时长分钟：2
- 用户角色：员工
- AI角色：领导
- 训练目标：简洁汇报
- 开场白：说吧，什么事？

#### 场景描述

向领导用一分钟汇报今天三件事。

#### 常见误区

- 流水账
"""

SAMPLE_FW = """# talktool-frameworks v1

## 框架：导入测试框架

- code：import_test_fw
- 分类：结构表达
- 摘要：导入用的测试框架
- 适用：测试场合
- 来源：测试

### 步骤

1. A｜第一步｜先说结论
2. B｜第二步｜再给理由

### 通用示例

结论是……理由是……

### 常见误区

- 铺垫太长

### 小技巧

- 先说观点
"""


def test_parse_and_upsert():
    db.init_db()
    cats = catalog_import.parse_catalog_md(SAMPLE_CATALOG)
    assert len(cats) == 1 and cats[0]["name"] == "导入测试分类"
    assert len(cats[0]["scenarios"][0]["drills"]) == 2
    d0 = cats[0]["scenarios"][0]["drills"][0]
    assert d0["pressure"] == "中压" and "落地页" in d0["description"]
    assert d0["guide_frameworks"][0]["code"] == "prep"

    fws = catalog_import.parse_frameworks_md(SAMPLE_FW)
    assert fws[0]["code"] == "import_test_fw" and len(fws[0]["steps"]) == 2

    r1 = catalog_import.import_bytes(SAMPLE_FW.encode("utf-8"), "fw.md", mode="upsert")
    assert r1["frameworks"]["added"] == 1
    r2 = catalog_import.import_bytes(SAMPLE_CATALOG.encode("utf-8"), "cat.md", mode="upsert")
    assert r2["catalog"]["drills_added"] == 2

    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM drill WHERE title LIKE '导入测试训练%'").fetchone()[0]
        assert n == 2
        pit = conn.execute("SELECT pitfalls FROM drill WHERE title = ?", ("导入测试训练甲",)).fetchone()[0]
        assert "老板" in pit
        links = conn.execute(
            """SELECT COUNT(*) FROM drill_framework df JOIN drill d ON d.id = df.drill_id
               WHERE d.title = ?""", ("导入测试训练甲",)).fetchone()[0]
        assert links >= 1

    # 更新
    updated_md = SAMPLE_CATALOG.replace("排期满了。", "排期满了，改一版开场。")
    r3 = catalog_import.import_bytes(updated_md.encode("utf-8"), "cat.md", mode="upsert")
    assert r3["catalog"]["drills_updated"] == 2 and r3["catalog"]["drills_added"] == 0
    with get_conn() as conn:
        line = conn.execute("SELECT opening_line FROM drill WHERE title = ?", ("导入测试训练甲",)).fetchone()[0]
        assert "改一版开场" in line

    # add_only 跳过
    r4 = catalog_import.import_bytes(SAMPLE_CATALOG.encode("utf-8"), "cat.md", mode="add_only")
    assert r4["catalog"]["drills_skipped"] == 2


def test_zip_import():
    db.init_db()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("frameworks.md", SAMPLE_FW)
        zf.writestr("catalog/drills.md", SAMPLE_CATALOG.replace("导入测试训练甲", "ZIP训练甲")
                    .replace("导入测试训练乙", "ZIP训练乙")
                    .replace("导入测试分类", "ZIP分类")
                    .replace("导入测试场景", "ZIP场景"))
    r = catalog_import.import_bytes(buf.getvalue(), "pack.zip", mode="upsert")
    assert r["frameworks"]["added"] + r["frameworks"]["updated"] >= 1
    assert r["catalog"]["drills_added"] == 2


def test_bad_pressure():
    db.init_db()
    bad = SAMPLE_CATALOG.replace("中压", "超级压")
    try:
        catalog_import.parse_catalog_md(bad)
        raise AssertionError("应拒绝非法压力")
    except BadRequest as e:
        assert "压力" in str(e)


if __name__ == "__main__":
    test_parse_and_upsert()
    test_zip_import()
    test_bad_pressure()
    print("catalog_import tests ok")
