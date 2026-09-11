"""活动 summary 中文化:状态流转与引用目标可读名(REQ 877727e8)。"""

import uuid

from sqlalchemy.orm import Session

from app.services import polymorphic as svc
from app.services import requirements as req_svc
from app.services import tasks as task_svc


def make_requirement(db: Session, world: dict, title: str = "需求") -> dict:
    return req_svc._requirement_dict(
        db, req_svc.create_requirement(db, world["admin"], world["project"].id, title)
    )


def test_requirement_status_summary_is_chinese(db: Session, world: dict):
    r = make_requirement(db, world)
    rid = uuid.UUID(r["id"])
    req_svc.set_requirement_status(db, world["admin"], rid, "in_progress")
    page = svc.list_activity(db, world["member"], "requirement", rid, None, 50)
    assert page["items"][-1]["summary"] == "待确认 → 实现中"


def test_task_status_summary_is_chinese(db: Session, world: dict):
    r = make_requirement(db, world)
    rid = uuid.UUID(r["id"])
    req_svc.set_requirement_status(db, world["admin"], rid, "backlog")
    t = task_svc._task_dict(
        db, task_svc.create_task(db, world["admin"], world["project"].id, "任务", None, rid)
    )
    tid = uuid.UUID(t["id"])
    task_svc.set_task_status(db, world["admin"], tid, "done")
    page = svc.list_activity(db, world["member"], "task", tid, None, 50)
    assert page["items"][-1]["summary"] == "待办 → 已完成"


def test_reference_summary_shows_readable_title(db: Session, world: dict):
    r1 = make_requirement(db, world, "来源需求")
    r2 = make_requirement(db, world, "目标需求")
    svc.create_reference(
        db, world["admin"], "requirement", uuid.UUID(r1["id"]), "requirement", uuid.UUID(r2["id"]), "derives"
    )
    page = svc.list_activity(db, world["member"], "requirement", uuid.UUID(r1["id"]), None, 50)
    assert page["items"][-1]["summary"] == "引用 需求《目标需求》"
