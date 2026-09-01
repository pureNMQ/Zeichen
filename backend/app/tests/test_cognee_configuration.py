"""Cognee configuration is a Web-only administrator capability."""

from .conftest import login


PAYLOAD = {
    "llm_provider": "custom",
    "llm_model": "test/test-model",
    "llm_endpoint": "https://llm.example.test/v1",
    "embedding_provider": "fastembed",
    "embedding_model": "test-embedding",
    "embedding_dimensions": 1536,
}


def test_cognee_configuration_is_admin_only(client, db, world):
    assert client.get("/api/cognee/configuration").status_code == 401

    login(client, "bob", "temporary-pass-1")
    client.post("/api/auth/set-password", json={"password": "member-pass-1"})
    assert client.get("/api/cognee/configuration").status_code == 403


def test_update_cognee_configuration_hides_key_and_marks_restart(client, db, world):
    login(client, "admin", "admin-pass-1")
    initial = client.get("/api/cognee/configuration")
    assert initial.status_code == 200
    assert initial.json()["llm_api_key_configured"] is False

    response = client.put(
        "/api/cognee/configuration", json={**PAYLOAD, "llm_api_key": "secret-value"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["llm_model"] == "test/test-model"
    assert body["llm_api_key_configured"] is True
    assert body["llm_api_key_source"] == "managed"
    assert body["llm_api_key_display"] == "sec********alue"
    assert body["pending_restart"] is True
    assert "llm_api_key" not in body
    assert "secret-value" not in response.text

    # Omitting the secret retains it while other fields can still be updated.
    response = client.put("/api/cognee/configuration", json={**PAYLOAD, "llm_model": "test/next-model"})
    assert response.status_code == 200
    assert response.json()["llm_api_key_configured"] is True


def test_update_rejects_llm_model_without_provider_prefix(client, db, world):
    """契约:llm_model 必须为 provider/model 限定格式,未限定值(如 deepseek-v4-flash)拒绝。

    cognee 1.4.1 经 litellm 以 model 串推断 provider,未限定串会导致全部 LLM
    调用失败(LLM Provider NOT provided),蒸馏因此返回 409(REQ bc36ae8b)。
    """
    login(client, "admin", "admin-pass-1")

    rejected = client.put(
        "/api/cognee/configuration", json={**PAYLOAD, "llm_model": "deepseek-v4-flash"}
    )
    assert rejected.status_code == 400, rejected.text

    accepted = client.put(
        "/api/cognee/configuration", json={**PAYLOAD, "llm_model": "deepseek/deepseek-v4-flash"}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["llm_model"] == "deepseek/deepseek-v4-flash"
    assert accepted.json()["pending_restart"] is True


def test_restart_is_admin_only_requires_confirmation_and_returns_a_job(client, db, world):
    assert client.post("/api/cognee/configuration/restarts", json={"confirmed": True}).status_code == 401
    login(client, "bob", "temporary-pass-1")
    client.post("/api/auth/set-password", json={"password": "member-pass-1"})
    assert client.post("/api/cognee/configuration/restarts", json={"confirmed": True}).status_code == 403

    login(client, "admin", "admin-pass-1")
    rejected = client.post("/api/cognee/configuration/restarts", json={"confirmed": False})
    assert rejected.status_code == 400

    accepted = client.post("/api/cognee/configuration/restarts", json={"confirmed": True})
    assert accepted.status_code == 202, accepted.text
    job = accepted.json()["job"]
    assert job["status"] == "queued"
    assert client.get(f"/api/cognee/configuration/restarts/{job['id']}").json()["job"]["id"] == job["id"]


def test_cognee_runtime_status_reports_reachability_and_latest_restart(client, db, world, monkeypatch):
    from app.services import cognee_configuration

    login(client, "admin", "admin-pass-1")
    monkeypatch.setattr(
        cognee_configuration,
        "probe_runtime",
        lambda: {"availability": "reachable", "detail": None, "checked_at": "2026-08-13T00:00:00+00:00"},
    )

    response = client.get("/api/cognee/configuration/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["runtime"]["availability"] == "reachable"
    assert body["latest_restart"] is None


def test_deployment_key_is_masked_without_exposing_its_plaintext(client, db, world, monkeypatch):
    from app.services import cognee_configuration

    login(client, "admin", "admin-pass-1")
    monkeypatch.setattr(cognee_configuration, "deployment_api_key", lambda: "sk-example-secret-9f2a")

    response = client.get("/api/cognee/configuration")
    assert response.status_code == 200
    body = response.json()
    assert body["llm_api_key_source"] == "deployment"
    assert body["llm_api_key_display"] == "sk-***************9f2a"
    assert "example-secret" not in response.text
