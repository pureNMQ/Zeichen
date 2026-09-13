"""REQ-2 红灯:需求/任务描述仅支持简短纯文本(规范化与拒绝规则)。

策略(经需求 57a18be0 评论定稿,Web API 与 MCP 共用同一入口):
- 既有单行约束不变:strip 后为空 → None;含换行 → invalid_request。
- Markdown 输入按「可剥离记号规范化为纯文本、不可安全剥离明确报错」处理:
  1) Markdown 图片 ![alt](url) → invalid_request(嵌入外部资源,不可安全剥离);
  2) HTML 标签(<script>、<div>、<br/> 等尖括号标签)→ invalid_request(富文本载体);
  3) 链接 [text](url) → text(URL 丢弃,文字保留);
  4) 行内代码 `code` → code;
  5) 成对强调 **x** / __x__ / ~~x~~ / *x* / _x_ → x;
     词内下划线(user_profile_service)与不成对星号(3*4=12)必须原样保留,
     不得把普通纯文本改坏。
- 长度上限沿用 512(与 ck_requirement/task_description_length、前端
  maxLength=512 一致),作用于规范化后的最终文本。
- 历史数据不迁移:存量 Markdown 描述读取原样返回,仅在更新描述时应用新规则。
"""

import pytest

from app.errors import AppError
from app.models import Requirement, Task
from app.services.requirements import create_requirement, get_requirement, update_requirement
from app.services.short_text import normalize_short_description
from app.services.tasks import create_task, get_task, update_task


# ---------- a) 规范化与拒绝:纯函数契约 ----------


def test_plain_text_single_line_unchanged():
    assert normalize_short_description("先做登录,再做权限") == "先做登录,再做权限"


def test_none_blank_and_trim_unchanged():
    assert normalize_short_description(None) is None
    assert normalize_short_description("   ") is None
    assert normalize_short_description("  标题  ") == "标题"


def test_newline_still_rejected():
    with pytest.raises(AppError) as e:
        normalize_short_description("第一行\n第二行")
    assert e.value.code == "invalid_request"


def test_emphasis_markers_stripped():
    assert normalize_short_description("**重点** 与 *次点*") == "重点 与 次点"


def test_underscore_strikethrough_and_inline_code_stripped():
    assert normalize_short_description("__粗体__ ~~删除~~ `pytest -q`") == "粗体 删除 pytest -q"


def test_link_textified():
    assert normalize_short_description("见 [说明](https://example.com/doc) 即可") == "见 说明 即可"


def test_combined_markdown_normalized_to_plain_text():
    raw = "**重要**：先看 [说明](https://example.com/doc)，再跑 `pytest`"
    assert normalize_short_description(raw) == "重要：先看 说明，再跑 pytest"


def test_markdown_image_rejected():
    with pytest.raises(AppError) as e:
        normalize_short_description("界面 ![截图](https://example.com/a.png) 如下")
    assert e.value.code == "invalid_request"


def test_html_tags_rejected():
    for bad in ("<script>alert(1)</script>", "<div>富文本</div>", "手动<br/>换行"):
        with pytest.raises(AppError) as e:
            normalize_short_description(bad)
        assert e.value.code == "invalid_request"


def test_intraword_underscore_and_unpaired_star_preserved():
    text = "关注 user_profile_service 与 3*4=12"
    assert normalize_short_description(text) == text


# ---------- b) 长度上限:作用于规范化后的最终文本 ----------


def test_length_limit_512_boundary():
    assert normalize_short_description("a" * 512) == "a" * 512
    with pytest.raises(AppError) as e:
        normalize_short_description("a" * 513)
    assert e.value.code == "invalid_request"


def test_markdown_length_counted_after_stripping():
    # 516 字符的 Markdown 剥离记号后恰好 512 → 通过,保存剥离结果
    assert normalize_short_description("**" + "b" * 512 + "**") == "b" * 512
    # 剥离后仍超限 → 拒绝
    with pytest.raises(AppError) as e:
        normalize_short_description("**" + "c" * 512 + "**x")
    assert e.value.code == "invalid_request"


# ---------- a) 规范化与拒绝:需求/任务服务创建与更新 ----------


def _confirmed_requirement(world, db) -> "uuid.UUID":
    from app.services.requirements import set_requirement_status

    r = create_requirement(db, world["admin"], world["project"].id, "挂载需求")
    set_requirement_status(db, world["admin"], r.id, "backlog")
    return r.id


def test_create_requirement_markdown_normalized(world, db):
    r = create_requirement(
        db, world["admin"], world["project"].id, "统一登录",
        "**扫码** 或 [密码](https://example.com/doc) 登录",
    )
    assert r.description == "扫码 或 密码 登录"


def test_create_requirement_html_rejected(world, db):
    with pytest.raises(AppError) as e:
        create_requirement(db, world["admin"], world["project"].id, "统一登录", "<b>加粗</b>标题")
    assert e.value.code == "invalid_request"


def test_create_task_markdown_normalized_and_html_rejected(world, db):
    rid = _confirmed_requirement(world, db)
    t = create_task(db, world["admin"], world["project"].id, "写测试", "覆盖 `normalize` 的 **红线** 用例", rid)
    assert t.description == "覆盖 normalize 的 红线 用例"
    with pytest.raises(AppError) as e:
        create_task(db, world["admin"], world["project"].id, "写测试", "<em>斜体</em>描述", rid)
    assert e.value.code == "invalid_request"


def test_update_requirement_and_task_apply_plain_text_rules(world, db):
    r = create_requirement(db, world["admin"], world["project"].id, "需求A", "原描述")
    updated = update_requirement(db, world["admin"], r.id, None, "**新描述**")
    assert updated.description == "新描述"
    rid = _confirmed_requirement(world, db)
    t = create_task(db, world["admin"], world["project"].id, "任务A", "原任务描述", rid)
    ut = update_task(db, world["admin"], t.id, description="`ls` [列表](https://example.com/ls)")
    assert ut.description == "ls 列表"


# ---------- d) 历史兼容:存量 Markdown 读取不受影响,更新时才应用新规则 ----------


def _legacy_requirement(db, world, description: str) -> Requirement:
    r = Requirement(
        project_id=world["project"].id,
        title="存量需求",
        description=description,
        status="backlog",
        created_by=world["admin"].id,
    )
    db.add(r)
    db.commit()
    return r


def _legacy_task(db, world, description: str) -> Task:
    rid = _confirmed_requirement(world, db)
    t = Task(
        project_id=world["project"].id,
        title="存量任务",
        description=description,
        status="backlog",
        created_by=world["admin"].id,
        requirement_id=rid,
    )
    db.add(t)
    db.commit()
    return t


def test_legacy_markdown_requirement_description_read_unaffected(world, db):
    legacy = "# 大标题\n- 列表一 **加粗**\n- 列表二"
    r = _legacy_requirement(db, world, legacy)
    assert get_requirement(db, world["admin"], r.id).description == legacy


def test_legacy_markdown_task_description_read_unaffected(world, db):
    legacy = "## 任务\n1. 步骤一 `a`\n2. 步骤二"
    t = _legacy_task(db, world, legacy)
    assert get_task(db, world["admin"], t.id).description == legacy


def test_requirement_title_only_update_keeps_legacy_markdown(world, db):
    legacy = "**加粗** 与 `代码`"
    r = _legacy_requirement(db, world, legacy)
    update_requirement(db, world["admin"], r.id, "只改标题", None)
    assert r.title == "只改标题"
    assert r.description == legacy


def test_legacy_markdown_normalized_when_description_updated(world, db):
    r = _legacy_requirement(db, world, "**旧** 描述")
    updated = update_requirement(db, world["admin"], r.id, None, "[新](https://example.com/new) **描述**")
    assert updated.description == "新 描述"


def test_legacy_markdown_task_normalized_when_description_updated(world, db):
    t = _legacy_task(db, world, "~~旧~~ 任务")
    updated = update_task(db, world["admin"], t.id, description="**新** 任务")
    assert updated.description == "新 任务"
