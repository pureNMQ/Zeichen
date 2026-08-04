"""pytest 共享设施:sqlite 内存库 + API 客户端 + 世界工厂。

SESSION_SECRET 在导入 app 模块前经 env 固定,保证 JWT 可解码;
TestClient 自带 cookie jar,登录后直接带会话。
"""

import os

os.environ["SESSION_SECRET"] = "test-session-secret-0123456789abcdef"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import get_settings as config_get_settings  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Project,
    ProjectMember,
    Team,
    User,
    WorkspaceMember,
)

assert config_get_settings().session_secret == "test-session-secret-0123456789abcdef"


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing = sessionmaker(bind=engine, expire_on_commit=False)
    session = testing()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db: Session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_user(
    db: Session,
    username: str,
    role: str | None = "member",
    is_agent: bool = False,
    with_password: str | None = None,
) -> User:
    from app.security import hash_password

    user = User(
        username=username,
        password_hash=hash_password(with_password) if with_password else "",
        is_agent=is_agent,
    )
    db.add(user)
    db.flush()
    if role is not None:
        team = db.query(Team).first()
        db.add(WorkspaceMember(team_id=team.id, user_id=user.id, role=role))
    db.commit()
    return user


@pytest.fixture()
def world(db: Session) -> dict:
    """已引导的工作区:admin 有密码,member/agent 无密码,project 已建。"""
    db.add(Team(name="贼船"))
    db.commit()
    admin = make_user(db, "admin", role="admin", with_password="admin-pass-1")
    admin.is_bootstrap = True
    db.commit()
    member = make_user(db, "bob", role="member")
    agent = make_user(db, "agent-a", role=None, is_agent=True)
    project = Project(team_id=db.query(Team).first().id, name="demo")
    db.add(project)
    db.commit()
    db.add(ProjectMember(project_id=project.id, user_id=member.id, role="viewer"))
    db.add(ProjectMember(project_id=project.id, user_id=agent.id, role="editor"))
    db.commit()
    return {
        "team": db.query(Team).first(),
        "admin": admin,
        "member": member,
        "agent": agent,
        "project": project,
    }


def login(client: TestClient, username: str, password: str) -> None:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
