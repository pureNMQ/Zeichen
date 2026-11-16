"""Worker 合并入口:单进程同时拉起全部常驻循环(REQ-3)。

worker 容器以 `python -m app.workers.main` 启动后,物理清理(24h 周期)
循环在守护线程内运行;循环崩溃退出不影响进程重启策略。
"""

import threading

from . import physical_purge

WORKER_MODULES = {
    "physical_purge": physical_purge,
}


def start_all() -> list[threading.Thread]:
    """以守护线程启动每个 worker 模块的 run() 循环(模块引用,便于测试注入)。"""
    threads: list[threading.Thread] = []
    for name, module in WORKER_MODULES.items():
        thread = threading.Thread(target=module.run, name=f"worker-{name}", daemon=True)
        thread.start()
        threads.append(thread)
    return threads


def run() -> None:
    threads = start_all()
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    run()
