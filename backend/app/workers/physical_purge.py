"""软删实体物理清理定时 worker(REQ-3 / 规格书 §8.2)。

单职责常驻循环:每轮调用 services.physical_purge.purge_soft_deleted 执行一轮
清理,随后按 settings.physical_purge_interval_seconds(默认 24h)休眠;
经模块引用调用服务便于测试注入。
"""

import time

from sqlalchemy import inspect

from ..config import get_settings
from ..db import SessionLocal
from ..services import physical_purge


def run_once() -> dict[str, int]:
    with SessionLocal() as db:
        if inspect(db.connection()).has_table("v2_wiki"):
            raise RuntimeError("Legacy physical purge cannot run on a v2 database")
        return physical_purge.purge_soft_deleted(db)


def run() -> None:
    settings = get_settings()
    while True:
        run_once()
        time.sleep(settings.physical_purge_interval_seconds)


if __name__ == "__main__":
    run()
