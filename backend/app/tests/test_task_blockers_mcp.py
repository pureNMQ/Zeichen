"""Task tools expose requirement-local identity and no blocker mutations."""
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


def test_task_tools_reject_blockers(mcp, mcp_server):
    pid = mcp_server["project_id"]
    rid = _mount_requirement(mcp, pid)
    task = mcp.call("tasks.create", project_id=pid, title="执行", requirement_id=rid)
    assert task["id"].startswith(rid + "-T")
    assert "blocked_by" not in task
    assert "error" in mcp.call("tasks.create", project_id=pid, title="错误", requirement_id=rid, blocked_by=[])
    assert "error" in mcp.call("tasks.update", project_id=pid, id=task["id"], blocked_by=[])
