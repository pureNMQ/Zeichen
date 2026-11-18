"""REQ-3 红灯:物理清理定时循环(记忆蒸馏 worker 同侧)· 调度契约。

需求 e86329d1 / 规格书 §8.2:清理任务每 24h 执行一次,保留期默认 90 天且环境变量可配置。
红灯阶段本文件因目标模块缺失而失败;实现后应全绿。

## 契约(供实现者)

- `app.workers.physical_purge.run_once() -> dict[str, int]`:执行一轮清理并返回与
  `app.services.physical_purge.purge_soft_deleted` 相同形状的报告;
- `app.workers.physical_purge.run()`:常驻循环,每轮调用 run_once 后按
  `settings.physical_purge_interval_seconds` 休眠(默认 24h);
- worker 经模块引用调用服务,便于测试注入;
- Settings 新增两个字段:
  - physical_purge_retention_days: int = 90(环境变量 PHYSICAL_PURGE_RETENTION_DAYS)
  - physical_purge_interval_seconds: float = 24 * 60 * 60
    (环境变量 PHYSICAL_PURGE_INTERVAL_SECONDS)
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings

# 红灯:worker 与服务模块尚不存在(REQ-3 任务 2「功能实现」补齐)
from app.services import physical_purge as physical_purge_service
from app.workers import physical_purge as worker


def test_legacy_worker_refuses_v2_database_before_purge(db, monkeypatch):
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(db.get_bind()))
    monkeypatch.setattr(physical_purge_service, "purge_soft_deleted", lambda _: pytest.fail("purge started"))
    with pytest.raises(RuntimeError, match="v2 database"):
        worker.run_once()


# ---------- Settings 契约(保留期可配置 + 24h 周期) ----------


def test_settings_default_retention_90_and_interval_24h():
    s = Settings(_env_file=None)
    assert s.physical_purge_retention_days == 90
    assert s.physical_purge_interval_seconds == 24 * 60 * 60


def test_settings_env_overrides(monkeypatch):
    monkeypatch.setenv("PHYSICAL_PURGE_RETENTION_DAYS", "30")
    monkeypatch.setenv("PHYSICAL_PURGE_INTERVAL_SECONDS", "3600")
    s = Settings(_env_file=None)
    assert s.physical_purge_retention_days == 30
    assert s.physical_purge_interval_seconds == 3600.0


# ---------- 调度契约:run_once 可注入触发,run 按 24h 周期循环 ----------


def test_run_once_executes_one_purge_pass_and_returns_report(monkeypatch):
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(create_engine("sqlite://")))
    sessions = []
    report = {"requirement": 2, "attachment": 1}

    def fake_purge(db, **kwargs):
        sessions.append(db)
        return report

    monkeypatch.setattr(physical_purge_service, "purge_soft_deleted", fake_purge)

    result = worker.run_once()

    assert result == report, "run_once 应透传服务层清理报告"
    assert len(sessions) == 1, "run_once 应以一个会话执行一轮清理"


def test_run_loops_every_24h(monkeypatch):
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(create_engine("sqlite://")))
    monkeypatch.setattr(physical_purge_service, "purge_soft_deleted", lambda db, **kwargs: {})
    runs = []
    monkeypatch.setattr(worker, "run_once", lambda: (runs.append(1), True)[1])
    sleeps = []
    monkeypatch.setattr(
        worker.time,
        "sleep",
        lambda seconds: (sleeps.append(seconds), (_ for _ in ()).throw(SystemExit)),
    )

    with pytest.raises(SystemExit):
        worker.run()

    assert len(runs) >= 1, "循环应先执行至少一轮清理"
    assert sleeps == [24 * 60 * 60], "清理循环应按 24h 周期调度"
