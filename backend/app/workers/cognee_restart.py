"""Durable worker that owns Cognee recreation outside the Web request."""

import time

from ..config import get_settings
from ..db import SessionLocal
from ..services import cognee_restart_jobs


def run_once() -> bool:
    with SessionLocal() as db:
        job_id = cognee_restart_jobs.claim_next(db)
    if job_id is None:
        return False
    with SessionLocal() as db:
        cognee_restart_jobs.execute(db, job_id)
    return True


def run() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        cognee_restart_jobs.recover_interrupted_jobs(db)
    while True:
        if not run_once():
            time.sleep(settings.cognee_improve_worker_poll_seconds)


if __name__ == "__main__":
    run()
