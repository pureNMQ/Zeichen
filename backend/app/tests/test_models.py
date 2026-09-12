"""模型层冒烟:建表、需求五态/任务五态 check 约束、多态 check 约束、软删字段。"""
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


def test_requirement_six_states_task_four_states(
    session: Session, world: tuple[User, Team, Project]
) -> None:
    """需求六态(verifying 合法,验收上移需求);任务四态(verifying 拒绝)。"""
    _, _, p = world
    req = Requirement(project_id=p.id, title="验收中需求", status="verifying")
    session.add(req)
    session.commit()
    assert req.status == "verifying"

    t = Task(project_id=p.id, title="非法验收态", status="verifying", requirement_id=req.id)
    session.add(t)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


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


def test_memory_grant_roundtrip_and_unique(session: Session, world: tuple[User, Team, Project]) -> None:
    from app.models import MemoryGrant

    alice, _, _ = world
    bob = User(username="bob", password_hash="x", is_agent=True)
    carol = User(username="carol", password_hash="x", is_agent=True)
    session.add_all([bob, carol])
    session.commit()

    session.add(
        MemoryGrant(grantor_id=alice.id, viewer_agent_id=bob.id, target_agent_id=carol.id)
    )
    session.commit()
    assert session.query(MemoryGrant).count() == 1

    session.add(
        MemoryGrant(grantor_id=alice.id, viewer_agent_id=bob.id, target_agent_id=carol.id)
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_memory_grant_rejects_self_viewer_target(session: Session, world: tuple[User, Team, Project]) -> None:
    from app.models import MemoryGrant

    alice, _, _ = world
    bob = User(username="bob", password_hash="x", is_agent=True)
    session.add(bob)
    session.commit()

    session.add(MemoryGrant(grantor_id=alice.id, viewer_agent_id=bob.id, target_agent_id=bob.id))
    with pytest.raises(IntegrityError):
        session.commit()


def test_project_filter_view_roundtrip_and_json_criteria(
    session: Session, world: tuple[User, Team, Project]
) -> None:
    """project_filter_view:表名契约、JSON criteria 往返、无软删/created_by。"""
    from app.models import ProjectFilterView

    u, _, p = world
    criteria = {"statuses": ["pending", "backlog"], "keyword": "搜索", "view_mode": "board"}
    view = ProjectFilterView(
        project_id=p.id,
        user_id=u.id,
        entity_type="requirement",
        name="全部需求",
        criteria=criteria,
    )
    session.add(view)
    session.commit()
    assert ProjectFilterView.__tablename__ == "project_filter_view"
    assert view.id is not None
    assert view.criteria == criteria
    # 契约:物理删除(无 deleted_at)、无 created_by
    assert not hasattr(view, "deleted_at")
    assert not hasattr(view, "created_by")


def test_project_filter_view_unique_constraint(
    session: Session, world: tuple[User, Team, Project]
) -> None:
    """唯一约束 (project_id, user_id, entity_type, name) 生效。"""
    from app.models import ProjectFilterView

    u, _, p = world
    session.add(
        ProjectFilterView(project_id=p.id, user_id=u.id, entity_type="task", name="同名", criteria={})
    )
    session.commit()
    session.add(
        ProjectFilterView(project_id=p.id, user_id=u.id, entity_type="task", name="同名", criteria={})
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
