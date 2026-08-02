"""模型层冒烟:建表、需求四态/任务五态 check 约束、多态 check 约束、软删字段。"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Activity,
    Base,
    Comment,
    Project,
    Reference,
    Requirement,
    Task,
    Team,
    User,
    WorkspaceMember,
)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def session() -> Session:
    Base.metadata.create_all(engine)
    db = TestingSession()
    yield db
    db.close()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def world(session: Session) -> tuple[User, Team, Project]:
    u = User(username="alice", password_hash="x", is_agent=False)
    t = Team(name="贼船")
    session.add_all([u, t])
    session.flush()
    session.add(WorkspaceMember(team_id=t.id, user_id=u.id, role="admin"))
    session.commit()
    p = Project(team_id=t.id, name="demo")
    session.add(p)
    session.commit()
    return u, t, p


def test_roundtrip(session: Session, world: tuple[User, Team, Project]) -> None:
    u, _, p = world
    req = Requirement(project_id=p.id, title="做个搜索", status="backlog")
    session.add(req)
    session.commit()
    assert req.id is not None and req.status == "backlog"
    assert req.deleted_at is None

    t = Task(project_id=p.id, title="建索引", requirement_id=req.id, assignee_id=u.id)
    session.add(t)
    session.commit()
    assert t.requirement_id == req.id


def test_status_check_constraint(session: Session, world: tuple[User, Team, Project]) -> None:
    _, _, p = world
    req = Requirement(project_id=p.id, title="坏状态", status="nonsense")
    session.add(req)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_requirement_four_states_task_five_states(
    session: Session, world: tuple[User, Team, Project]
) -> None:
    """需求四态(拒 verifying);任务五态(verifying 合法)。"""
    _, _, p = world
    req = Requirement(project_id=p.id, title="验收中已删", status="verifying")
    session.add(req)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    t = Task(project_id=p.id, title="普通状态", status="verifying")
    session.add(t)
    session.commit()
    assert t.status == "verifying"


def test_polymorphic_target_check(session: Session, world: tuple[User, Team, Project]) -> None:
    u, _, p = world
    comment = Comment(
        project_id=p.id,
        target_type="spaceship",
        target_id=uuid.uuid4(),
        author_id=u.id,
        body="hello",
    )
    session.add(comment)
    with pytest.raises(IntegrityError):
        session.commit()


def test_polymorphic_roundtrip(session: Session, world: tuple[User, Team, Project]) -> None:
    u, _, p = world
    req = Requirement(project_id=p.id, title="r1")
    session.add(req)
    session.commit()

    session.add(
        Comment(
            project_id=p.id,
            target_type="requirement",
            target_id=req.id,
            author_id=u.id,
            body="先看下设计",
        )
    )
    session.add(
        Activity(
            project_id=p.id,
            target_type="requirement",
            target_id=req.id,
            actor_id=u.id,
            action="create",
            summary="创建需求 r1",
        )
    )
    session.add(
        Reference(
            project_id=p.id,
            from_type="task",
            from_id=uuid.uuid4(),
            to_type="requirement",
            to_id=req.id,
            type="derives",
        )
    )
    session.commit()
    assert session.query(Comment).count() == 1
    assert session.query(Activity).count() == 1
    assert session.query(Reference).count() == 1


def test_reference_enum_check(session: Session, world: tuple[User, Team, Project]) -> None:
    _, _, p = world
    ref = Reference(
        project_id=p.id,
        from_type="task",
        from_id=uuid.uuid4(),
        to_type="requirement",
        to_id=uuid.uuid4(),
        type="teleports",
    )
    session.add(ref)
    with pytest.raises(IntegrityError):
        session.commit()
