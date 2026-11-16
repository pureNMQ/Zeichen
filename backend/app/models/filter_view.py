"""个人筛选视图持久化:project_filter_view。

- 视图属主 user_id,仅本人可见可改(服务层按 (id, user_id) 过滤,不泄露他人视图存在性)
- criteria 为 JSON dict;白名单键 + 实体状态集校验在服务层(services/filter_views.py)
- 唯一约束 (project_id, user_id, entity_type, name) 跨 sqlite/pg 有效
- 契约:物理删除(无 deleted_at)、无 created_by
"""

import uuid

from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, ProjectScopeMixin, TimestampMixin


class ProjectFilterView(IdMixin, TimestampMixin, ProjectScopeMixin, Base):
    __tablename__ = "project_filter_view"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "user_id",
            "entity_type",
            "name",
            name="uq_project_filter_view_scope_name",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    criteria: Mapped[dict] = mapped_column(JSON, nullable=False)
