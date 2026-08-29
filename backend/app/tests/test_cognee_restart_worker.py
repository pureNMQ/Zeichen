"""重启队列消费与执行通道契约(红灯用例,需求 2ecf73bb)。

契约(留给实现者):
- `app.services.cognee_restart_jobs` 提供模块级注入点
  `get_docker_channel()`,返回仅暴露 `recreate_cognee(runtime_env_file,
  project_dir)` 一个公开操作的通道对象;默认实现以固定 argv 调用 docker
  compose 重建 cognee 容器(docker.sock 通道),worker 与测试可注入替身。
- 持久 worker(`app.workers.cognee_restart`)在容器化部署下消费队列:
  queued -> running -> completed/failed,成功与失败都必须落终态,失败写
  error,不允许永久 queued。
- 重启成功 = 受管配置写入 runtime env 文件(重建容器经 env_file 生效)且
  pending_restart 清零;失败 = 配置保持待应用。

所有测试经替身通道注入,绝不调用真实 docker / docker.sock。
"""

import contextlib
import inspect
import subprocess
from pathlib import Path

import pytest

from app.config import get_settings
from app.models import CogneeRestartJob
from app.services import cognee_configuration, cognee_restart_jobs
from app.workers import cognee_restart as restart_worker

from .conftest import login

CONFIGURATION_VALUES = {
    "llm_provider": "custom",
    "llm_model": "test-model",
    "llm_endpoint": None,
    "embedding_provider": "fastembed",
    "embedding_model": "test-embedding",
    "embedding_dimensions": 384,
}


class FakeDockerChannel:
    """docker.sock 执行通道替身:记录调用,绝不触碰真实 docker。"""

    def __init__(self, error: Exception | None = None):
        self.calls: list[dict] = []
        self.error = error

    def recreate_cognee(self, *, runtime_env_file, project_dir):
        self.calls.append(
            {
                "runtime_env_file": Path(runtime_env_file),
                "project_dir": Path(project_dir),
            }
        )
        if self.error is not None:
            raise self.error


def _install_channel(monkeypatch, fake: FakeDockerChannel) -> None:
    if not hasattr(cognee_restart_jobs, "get_docker_channel"):
        pytest.fail(
            "缺少执行通道注入点 cognee_restart_jobs.get_docker_channel():"
            "worker 无法以替身 docker 通道消费重启队列,容器化部署没有可测的执行通道"
        )
    monkeypatch.setattr(cognee_restart_jobs, "get_docker_channel", lambda: fake)


def _patch_worker_session(monkeypatch, db) -> None:
    monkeypatch.setattr(
        restart_worker, "SessionLocal", lambda: contextlib.nullcontext(db)
    )


def _patch_runtime_paths(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(
        settings, "cognee_runtime_env_file", tmp_path / ".scratch" / "cognee-runtime.env"
    )
    monkeypatch.setattr(settings, "cognee_compose_project_dir", tmp_path / "compose-project")


def test_worker_consumes_queued_job_to_completed_with_fake_docker_channel(
    db, world, monkeypatch, tmp_path
):
    _patch_runtime_paths(monkeypatch, tmp_path)
    cognee_configuration.update(db, dict(CONFIGURATION_VALUES))
    job = cognee_restart_jobs.submit(db, world["admin"], confirmed=True)
    assert job["status"] == "queued"

    fake = FakeDockerChannel()
    _install_channel(monkeypatch, fake)
    _patch_worker_session(monkeypatch, db)

    assert restart_worker.run_once() is True, "worker 应消费队列中的重启任务"

    row = db.query(CogneeRestartJob).one()
    assert row.status == "completed", "成功重启必须落 completed 终态"
    assert row.error is None
    assert row.started_at is not None
    assert row.finished_at is not None
    assert row.status not in cognee_restart_jobs.ACTIVE_STATUSES, "不允许停留 queued/running"
    assert cognee_configuration.get_or_create(db).pending_restart is False

    assert len(fake.calls) == 1, "一次重启恰好触发一次容器重建"
    settings = get_settings()
    assert fake.calls[0]["project_dir"].resolve() == settings.cognee_compose_project_dir.resolve()
    assert (
        fake.calls[0]["runtime_env_file"].resolve()
        == settings.cognee_runtime_env_file.resolve()
    )


def test_worker_failure_lands_failed_with_error_and_keeps_config_pending(
    db, world, monkeypatch, tmp_path
):
    _patch_runtime_paths(monkeypatch, tmp_path)
    cognee_configuration.update(db, dict(CONFIGURATION_VALUES))
    job = cognee_restart_jobs.submit(db, world["admin"], confirmed=True)

    fake = FakeDockerChannel(error=RuntimeError("docker daemon unreachable"))
    _install_channel(monkeypatch, fake)
    _patch_worker_session(monkeypatch, db)

    assert restart_worker.run_once() is True

    row = db.query(CogneeRestartJob).one()
    assert row.status == "failed", "失败重启必须落 failed 终态,不允许永久排队"
    assert row.error and "docker daemon unreachable" in row.error, "失败必须写可读 error"
    assert row.finished_at is not None
    assert row.status not in cognee_restart_jobs.ACTIVE_STATUSES
    assert len(fake.calls) == 1, "失败前应已尝试一次容器重建"
    assert cognee_configuration.get_or_create(db).pending_restart is True, (
        "失败时已保存配置保持待应用"
    )


def test_worker_writes_pending_configuration_to_runtime_env_before_recreate(
    db, world, monkeypatch, tmp_path
):
    """待应用配置生效流程:先写受管 runtime env,再重建容器,成功后清 pending。"""
    _patch_runtime_paths(monkeypatch, tmp_path)
    cognee_configuration.update(
        db,
        {
            **CONFIGURATION_VALUES,
            "llm_model": "next-model",
            "embedding_dimensions": 1536,
            "llm_api_key": "sk-placeholder-managed-key-0000",
        },
    )
    cognee_restart_jobs.submit(db, world["admin"], confirmed=True)

    fake = FakeDockerChannel()
    _install_channel(monkeypatch, fake)
    _patch_worker_session(monkeypatch, db)

    assert restart_worker.run_once() is True

    settings = get_settings()
    content = settings.cognee_runtime_env_file.read_text(encoding="utf-8")
    assert "LLM_MODEL=next-model" in content, "更新的 LLM 模型必须进入 runtime env"
    assert "LLM_API_KEY=sk-placeholder-managed-key-0000" in content, (
        "受管密钥(解密后)必须进入 runtime env 以便重建容器生效"
    )
    assert "EMBEDDING_DIMENSIONS=1536" in content
    assert "LLM_PROVIDER=custom" in content
    assert cognee_configuration.get_or_create(db).pending_restart is False


def test_persistent_worker_loop_drains_queue_without_manual_trigger(
    db, world, monkeypatch, tmp_path
):
    """持久 worker 的 run() 循环:启动即恢复中断任务并无人值守消费队列。"""
    _patch_runtime_paths(monkeypatch, tmp_path)
    cognee_configuration.update(db, dict(CONFIGURATION_VALUES))
    cognee_restart_jobs.submit(db, world["admin"], confirmed=True)

    fake = FakeDockerChannel()
    _install_channel(monkeypatch, fake)
    _patch_worker_session(monkeypatch, db)
    monkeypatch.setattr(
        restart_worker.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(SystemExit),
    )

    with pytest.raises(SystemExit):
        restart_worker.run()

    row = db.query(CogneeRestartJob).one()
    assert row.status == "completed", "run() 循环应无人值守地把 queued 任务推到终态"
    assert row.status not in cognee_restart_jobs.ACTIVE_STATUSES


def test_failed_restart_error_visible_via_api_job_and_status(client, db, world, monkeypatch, tmp_path):
    """错误反馈:失败任务经重启任务 API 与运行状态 API 均可感知。"""
    login(client, "admin", "admin-pass-1")
    payload = {**CONFIGURATION_VALUES, "llm_endpoint": "https://llm.example.test/v1"}
    updated = client.put("/api/cognee/configuration", json={**payload, "llm_api_key": "sk-placeholder-key-1111"})
    assert updated.status_code == 200, updated.text

    accepted = client.post("/api/cognee/configuration/restarts", json={"confirmed": True})
    assert accepted.status_code == 202, accepted.text
    job = accepted.json()["job"]
    assert job["status"] == "queued"

    _patch_runtime_paths(monkeypatch, tmp_path)
    fake = FakeDockerChannel(error=RuntimeError("docker daemon unreachable"))
    _install_channel(monkeypatch, fake)
    _patch_worker_session(monkeypatch, db)
    assert restart_worker.run_once() is True

    detail = client.get(f"/api/cognee/configuration/restarts/{job['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()["job"]
    assert body["status"] == "failed"
    assert body["error"], "失败任务必须经 API 暴露 error"
    assert body["finished_at"] is not None

    monkeypatch.setattr(
        cognee_configuration,
        "probe_runtime",
        lambda: {"availability": "reachable", "detail": None, "checked_at": "2026-08-30T00:00:00+00:00"},
    )
    status = client.get("/api/cognee/configuration/status")
    assert status.status_code == 200, status.text
    latest = status.json()["latest_restart"]
    assert latest is not None
    assert latest["status"] == "failed"
    assert latest["status_label"] == "失败"
    assert latest["error"], "运行状态接口必须携带失败原因"


def test_docker_channel_exposes_only_fixed_cognee_recreation_operation():
    """最小权限契约:通道只暴露固定的 cognee 重建操作,无任意 docker 操作面。"""
    provider = getattr(cognee_restart_jobs, "get_docker_channel", None)
    if provider is None:
        pytest.fail(
            "缺少执行通道注入点 cognee_restart_jobs.get_docker_channel():"
            "无法约束最小权限执行通道"
        )
    channel = provider()
    public_operations = {
        name
        for name in dir(channel)
        if not name.startswith("_") and callable(getattr(channel, name))
    }
    assert public_operations == {"recreate_cognee"}, (
        f"执行通道只允许暴露 cognee 重建操作,实际公开操作:{sorted(public_operations)}"
    )
    signature = inspect.signature(channel.recreate_cognee)
    forbidden = {"service", "container", "target", "command", "args", "argv", "name"}
    params = {name for name in signature.parameters if name not in ("self",)}
    assert params <= {"runtime_env_file", "project_dir"}, (
        f"recreate_cognee 只接受 runtime_env_file/project_dir,不允许任意目标参数,实际:{sorted(params)}"
    )
    assert not (params & forbidden)


def test_channel_recreate_uses_fixed_safe_docker_compose_arguments(monkeypatch, tmp_path):
    """执行通道以服务端固定 argv 调用 docker compose,仅以 cognee 为目标。"""
    provider = getattr(cognee_restart_jobs, "get_docker_channel", None)
    if provider is None:
        pytest.fail(
            "缺少执行通道注入点 cognee_restart_jobs.get_docker_channel():"
            "无法验证固定 argv 执行契约"
        )

    settings = get_settings()
    runtime_env = tmp_path / ".scratch" / "cognee-runtime.env"
    project_dir = tmp_path / "compose-project"
    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    channel = provider()
    channel.recreate_cognee(runtime_env_file=runtime_env, project_dir=project_dir)

    argv = captured["argv"]
    kwargs = captured["kwargs"]
    assert argv[0] == settings.cognee_compose_executable, "执行器必须来自服务端配置"
    assert "compose" in argv[:2], "必须走 docker compose 子命令"
    assert argv[-1] == "cognee", "重建目标必须是固定的 cognee 服务"
    assert argv.count("cognee") == 1, "不允许出现第二个操作目标"
    for token in ("up", "-d", "--force-recreate"):
        assert token in argv, f"必须以 {token} 重建 cognee 容器(环境变量变更需 recreate)"
    assert "--env-file" in argv and str(runtime_env) in argv, "受管 runtime env 必须传入 compose"
    for forbidden_token in ("down", "rm", "kill", "exec", "run", "ps", "logs"):
        assert forbidden_token not in argv, f"执行通道不允许 docker {forbidden_token}"

    assert kwargs.get("cwd") in (project_dir, Path(project_dir)), (
        "cwd 必须是固定的 compose 项目目录"
    )
    assert kwargs.get("timeout") == settings.cognee_restart_timeout_seconds, "必须带超时防卡死"
    assert kwargs.get("check") is False, "由通道检查 returncode 并转成可读错误"
    assert kwargs.get("capture_output") is True, "必须捕获输出用于错误反馈"
    assert not kwargs.get("shell", False), "禁止 shell 插值"
