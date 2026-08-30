"""合并入口冒烟(REQ-3):单进程同时拉起记忆蒸馏与物理清理两个常驻循环。

worker 容器以 `python -m app.workers.main` 启动;两循环均为守护线程,
经模块引用(module.run)启动,便于测试注入与 monkeypatch。
"""

import threading

from app.workers import main as worker_main
from app.workers import memory_improve as memory_worker
from app.workers import physical_purge as purge_worker


def test_start_all_runs_both_loops_in_daemon_threads(monkeypatch):
    started = []
    release = threading.Event()

    def fake_run(name):
        def _run():
            started.append(name)
            release.wait(timeout=5)

        return _run

    monkeypatch.setattr(memory_worker, "run", fake_run("memory_improve"))
    monkeypatch.setattr(purge_worker, "run", fake_run("physical_purge"))

    threads = worker_main.start_all()
    try:
        for thread in threads:
            thread.join(timeout=5)
        assert sorted(started) == ["memory_improve", "physical_purge"], "两个循环都应被启动"
        assert {t.name for t in threads} == {"worker-memory_improve", "worker-physical_purge"}
        assert all(t.daemon for t in threads), "worker 循环应为守护线程"
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=5)


def test_run_joins_all_worker_threads(monkeypatch):
    joins = []

    class FakeThread:
        def __init__(self, name):
            self.name = name

        def join(self):
            joins.append(self.name)

    monkeypatch.setattr(
        worker_main, "start_all", lambda: [FakeThread("memory_improve"), FakeThread("physical_purge")]
    )

    worker_main.run()

    assert joins == ["memory_improve", "physical_purge"], "主线程应 join 等待全部 worker 循环"
