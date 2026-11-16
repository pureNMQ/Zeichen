"""REQ-2 红灯:MCP 与 Web API 描述纯文本语义一致。

MCP 的 requirements.* / tasks.* 无独立校验路径,与 HTTP 同走
service 层 normalize_short_description;本文件经真实 MCP 服务验证:
Markdown 规范化、HTML/图片拒绝、长度上限,以及存量 Markdown 描述
读取原样返回、更新时才应用新规则。
"""

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SASession

from app.models import Requirement as ReqModel
from app.tests.test_mcp_e2e import RawMcpClient, mcp_server  # noqa: F401


def _client(mcp_server: dict) -> RawMcpClient:
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    return client


def test_mcp_requirement_description_plain_text_semantics(mcp_server: dict):
    client = _client(mcp_server)
    pid = mcp_server["project_id"]

    req = client.call(
        "requirements.create", project_id=pid, title="MCP 纯文本",
        description="**扫码** 或 [密码](https://example.com/doc) 登录",
    )
    assert req["description"] == "扫码 或 密码 登录"

    updated = client.call("requirements.update", id=req["id"], project_id=pid, description="`pytest` **回归**")
    assert updated["description"] == "pytest 回归"

    html = client.call(
        "requirements.create", project_id=pid, title="MCP 富文本", description="<div>富文本</div>"
    )
    assert "invalid_request" in html["error"]
    image = client.call(
        "requirements.create", project_id=pid, title="MCP 图片",
        description="界面 ![截图](https://example.com/a.png) 如下",
    )
    assert "invalid_request" in image["error"]

    over_limit = client.call(
        "requirements.create", project_id=pid, title="MCP 超长", description="a" * 513
    )
    assert "invalid_request" in over_limit["error"]


def test_mcp_task_description_plain_text_semantics(mcp_server: dict):
    client = _client(mcp_server)
    pid = mcp_server["project_id"]

    r = client.call("requirements.create", project_id=pid, title="MCP 任务挂载需求")
    client.call("requirements.set_status", id=r["id"], project_id=pid, status="backlog")
    t = client.call(
        "tasks.create",
        project_id=pid,
        title="MCP 任务",
        description="**红线** 用例",
        requirement_id=r["id"],
    )
    assert t["description"] == "红线 用例"

    html = client.call("tasks.update", id=t["id"], project_id=pid, description="<b>加粗</b>")
    assert "invalid_request" in html["error"]


def test_mcp_legacy_markdown_description_read_unaffected_and_normalized_on_update(mcp_server: dict):
    client = _client(mcp_server)
    pid = mcp_server["project_id"]
    legacy = "# 存量标题\n- 列表 **加粗**"

    db_path = mcp_server["log_file"].parent / "e2e.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"timeout": 10})
    with SASession(engine) as s:
        # 分配短码(ADR 0002):先取项目当前计数器值
        from app.models import ShortCodeCounter

        counter = s.get(ShortCodeCounter, (uuid.UUID(str(pid)), "requirement"))
        seq = (counter.last_seq if counter else 0) + 1
        code = f"REQ-{seq}"
        row = ReqModel(
            project_id=uuid.UUID(str(pid)), code=code, title="存量需求", description=legacy,
            status="backlog", created_by=uuid.UUID(mcp_server["agent_id"]),
        )
        s.add(row)
        s.commit()
        if counter:
            counter.last_seq = seq
            s.commit()
        rid = code
    engine.dispose()

    # 存量 Markdown 读取原样返回(不迁移、不丢数据)
    got = client.call("requirements.get", id=rid, project_id=pid)
    assert got["description"] == legacy
    # 仅更新标题:描述不动
    kept = client.call("requirements.update", id=rid, project_id=pid, title="只改标题")
    assert kept["description"] == legacy
    # 更新描述:应用新规则
    applied = client.call("requirements.update", id=rid, project_id=pid, description="[新](https://example.com/new) **描述**")
    assert applied["description"] == "新 描述"

    assert client.call("requirements.delete", id=rid, confirm_task_count=0, project_id=pid)["deleted"] is True
