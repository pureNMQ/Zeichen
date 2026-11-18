from uuid import uuid4

import pytest

from app.tests.test_mcp_e2e import RawMcpClient, mcp_server  # noqa: F401


@pytest.mark.parametrize("kind", ["requirements", "tasks"])
def test_work_markdown_revision_protocol_over_mcp(mcp_server, kind):
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    pid = mcp_server["project_id"]
    scope = {"project_id": pid}
    text = "# 工作说明\n" + "**详细正文** " * 100
    payload = {"title": "文稿", "description": text, "request_id": str(uuid4())}
    if kind == "tasks":
        parent = client.call("requirements.create", title="所属需求", **scope)
        client.call("requirements.set_status", status="backlog", id=parent["id"], **scope)
        payload["requirement_id"] = parent["id"]
    item = client.call(f"{kind}.create", **payload, **scope)
    assert item["description"] == text and item["version"] == 1
    assert client.call(f"{kind}.create", **payload, **scope) == item
    target = dict(id=item["id"], **scope)
    updated = client.call(f"{kind}.update", description="更新", expected_version=1, **target)
    assert updated["version"] == 2
    assert "conflict" in client.call(f"{kind}.update", description="迟到的更新", expected_version=1, **target)["error"]
    assert client.call("work.read_version", kind=kind, **target, version=1)["description"] == text
    restored = client.call("work.restore_version", kind=kind, version=1, expected_version=2, **target)
    assert restored["description"] == text
    versions = client.call("work.versions", kind=kind, **target)["items"]
    assert [v["version"] for v in versions] == [3, 2, 1]
