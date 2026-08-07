"""Single-purpose durable worker for long-running Cognee session improve jobs."""

import time

from ..config import get_settings
from ..db import SessionLocal
from ..services import memory_improve_jobs


def run_once() -> bool:
    with SessionLocal() as db:
        job_id = memory_improve_jobs.claim_next(db)
    if job_id is None:
        return False
    with SessionLocal() as db:
        memory_improve_jobs.execute(db, job_id)
    return True


def run() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        memory_improve_jobs.recover_interrupted_jobs(db)
    while True:
        if not run_once():
            time.sleep(settings.cognee_improve_worker_poll_seconds)


if __name__ == "__main__":
    run()
