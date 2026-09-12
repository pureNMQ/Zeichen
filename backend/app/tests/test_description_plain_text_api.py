"""REQ-2 红灯:描述纯文本规则经 HTTP API 生效(与 service/MCP 同层语义)。

覆盖:需求与任务的创建/更新走 normalize_short_description;HTML 与 Markdown
图片返回 400 invalid_request;长度上限 512(规范化后)在 API 边界生效。
"""

from fastapi.testclient import TestClient

from app.tests.conftest import login


def _login_admin(client: TestClient, world: dict) -> str:
    login(client, "admin", "admin-pass-1")
    return str(world["project"].id)


def test_requirement_description_markdown_normalized_over_api(client, world):
    pid = _login_admin(client, world)
    resp = client.post(
        f"/api/projects/{pid}/requirements",
        json={"title": "统一登录", "description": "**扫码** 或 [密码](https://example.com/doc) 登录"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["description"] == "扫码 或 密码 登录"
    rid = resp.json()["id"]

    resp = client.patch(f"/api/requirements/{rid}", json={"description": "纯文本 **更新**"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "纯文本 更新"


def test_requirement_description_html_and_image_rejected_over_api(client, world):
    pid = _login_admin(client, world)
    for bad in ("<div>富文本</div>", "界面 ![截图](https://example.com/a.png) 如下"):
        resp = client.post(f"/api/projects/{pid}/requirements", json={"title": "需求", "description": bad})
        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "invalid_request"


def test_requirement_description_length_boundary_over_api(client, world):
    pid = _login_admin(client, world)
    resp = client.post(f"/api/projects/{pid}/requirements", json={"title": "上限内", "description": "a" * 512})
    assert resp.status_code == 201, resp.text
    resp = client.post(f"/api/projects/{pid}/requirements", json={"title": "超限", "description": "a" * 513})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"


def test_requirement_description_markdown_over_limit_counted_after_stripping(client, world):
    pid = _login_admin(client, world)
    # 记号剥离后 513 字符 → 拒绝(上限作用于规范化后文本)
    resp = client.post(
        f"/api/projects/{pid}/requirements",
        json={"title": "剥离后超限", "description": "**" + "b" * 512 + "**x"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"


def test_task_description_markdown_normalized_and_html_rejected_over_api(client, world):
    pid = _login_admin(client, world)
    rid = client.post(f"/api/projects/{pid}/requirements", json={"title": "挂载需求"}).json()["id"]
    client.post(f"/api/requirements/{rid}/status", json={"status": "backlog"})
    resp = client.post(
        f"/api/projects/{pid}/tasks",
        json={
            "title": "写测试",
            "description": "覆盖 `normalize` 的 **红线** 用例",
            "requirement_id": rid,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["description"] == "覆盖 normalize 的 红线 用例"
    tid = resp.json()["id"]

    resp = client.patch(f"/api/tasks/{tid}", json={"description": "<em>斜体</em>描述"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"

    resp = client.patch(f"/api/tasks/{tid}", json={"description": "`ls` [列表](https://example.com/ls)"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "ls 列表"
