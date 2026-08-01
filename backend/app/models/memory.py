"""memory_grant:记忆互通授权(§6.3)。

admin 授权 viewer_agent 只读 target_agent 的 Dataset;只读不写。
grantor = 授权者(管理员);撤销 = 软删。工作区级(跨项目),无 project_id。
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedByMixin, IdMixin, SoftDeleteMixin, TimestampMixin


class MemoryGrant(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, Base):
    __tablename__ = "memory_grant"
    __table_args__ = (
        UniqueConstraint(
            "grantor_id", "viewer_agent_id", "target_agent_id",
            name="uq_memory_grant_grantor_viewer_target",
        ),
        CheckConstraint(
            "viewer_agent_id <> target_agent_id", name="ck_memory_grant_not_self"
        ),
    )

    grantor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    viewer_agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
