"""REQ-7 任务阻塞依赖:MCP 一致性红灯用例(真实 MCP 服务,复用 e2e fixture)。

契约:MCP 与 Web API 语义一致——
- ``tasks.create`` 支持 ``blocked_by: list[str]``(前置任务 id);
- ``tasks.update`` 支持 ``blocked_by``(整体替换;``blocked_by=[]`` 清空);
- ``tasks.get`` / ``tasks.list`` 返回 ``blocked``(bool)与 ``blocked_by``
  (前置摘要 [{"id","title","status","resolved"}]);
- 规则拒绝与 Web API 同码:自依赖 → invalid_request,循环 → conflict,
  跨项目 → invalid_request,重复 → conflict。
"""

import pytest

from app.tests.test_mcp_e2e import RawMcpClient, mcp_server  # noqa: F401


@pytest.fixture()
def mcp(mcp_server: dict) -> RawMcpClient:
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    return client


def _mount_requirement(mcp: RawMcpClient, pid: str, title="MCP 挂载需求") -> str:
    r = mcp.call("requirements.create", project_id=pid, title=title)
    mcp.call("requirements.set_status", id=r["id"], project_id=pid, status="backlog")
    return r["id"]


def test_task_blockers_crud_over_mcp(mcp: RawMcpClient, mcp_server: dict):
    pid = mcp_server["project_id"]
    rid = _mount_requirement(mcp, pid)
    a = mcp.call("tasks.create", project_id=pid, title="前置任务", requirement_id=rid)
    b = mcp.call(
        "tasks.create", project_id=pid, title="被阻塞任务", requirement_id=rid, blocked_by=[a["id"]]
    )
    assert "error" not in b, b
    assert b["blocked"] is True
    assert [i["id"] for i in b["blocked_by"]] == [a["id"]]

    got = mcp.call("tasks.get", id=b["id"], project_id=pid)
    assert got["blocked"] is True
    assert got["blocked_by"][0]["id"] == a["id"]
    assert got["blocked_by"][0]["title"] == "前置任务"
    assert got["blocked_by"][0]["status"] == "backlog"
    assert got["blocked_by"][0]["resolved"] is False

    # 整体替换 / 清空
    cleared = mcp.call("tasks.update", id=b["id"], project_id=pid, blocked_by=[])
    assert cleared["blocked"] is False and cleared["blocked_by"] == []
    readded = mcp.call("tasks.update", id=b["id"], project_id=pid, blocked_by=[a["id"]])
    assert readded["blocked"] is True

    # 列表同样携带阻塞状态(看板/执行视图数据源)
    page = mcp.call("tasks.list", project_id=pid)
    by_id = {i["id"]: i for i in page["items"]}
    assert by_id[b["id"]]["blocked"] is True


def test_task_blocker_rules_over_mcp(mcp: RawMcpClient, mcp_server: dict):
    pid = mcp_server["project_id"]
    rid = _mount_requirement(mcp, pid)
    a = mcp.call("tasks.create", project_id=pid, title="任务A", requirement_id=rid)
    b = mcp.call("tasks.create", project_id=pid, title="任务B", requirement_id=rid)

    self_dep = mcp.call("tasks.update", id=a["id"], project_id=pid, blocked_by=[a["id"]])
    assert "error" in self_dep and "invalid_request" in self_dep["error"], self_dep

    assert "error" not in mcp.call("tasks.update", id=b["id"], project_id=pid, blocked_by=[a["id"]])
    cycle = mcp.call("tasks.update", id=a["id"], project_id=pid, blocked_by=[b["id"]])
    assert "error" in cycle and "conflict" in cycle["error"], cycle

    dup = mcp.call("tasks.update", id=b["id"], project_id=pid, blocked_by=[a["id"], a["id"]])
    assert "error" in dup and "conflict" in dup["error"], dup
