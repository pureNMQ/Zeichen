"""team(单例根)/ workspace_member / project / project_member。

规格书 §2.2:team 为工作区根节点(单例,未来多团队 = 多行);
project 为资源容器,授权的最小单位;人 + agent 共用 project_member。
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedByMixin, IdMixin, SoftDeleteMixin, TimestampMixin
from .user import WORKSPACE_ROLE_VALUES

PROJECT_ROLE_VALUES = ("owner", "editor", "viewer")


class Team(IdMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "team"

    name: Mapped[str] = mapped_column(String(128), nullable=False)

    projects: Mapped[list["Project"]] = relationship(back_populates="team")


class WorkspaceMember(IdMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "workspace_member"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_workspace_member_team_user"),
        CheckConstraint(
            f"role IN {WORKSPACE_ROLE_VALUES}", name="ck_workspace_member_role"
        ),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("team.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)


class Project(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, Base):
    __tablename__ = "project"

    team_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("team.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    team: Mapped[Team] = relationship(back_populates="projects")
    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project")


class ProjectMember(IdMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "project_member"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member_project_user"),
        CheckConstraint(f"role IN {PROJECT_ROLE_VALUES}", name="ck_project_member_role"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)

    project: Mapped[Project] = relationship(back_populates="members")
