"""Project-to-cognee dataset mapping.

The memory content and session cache remain wholly in cognee.  This table only
records the opaque dataset identifier required to scope every bridge call.
"""

import uuid

from sqlalchemy import ForeignKey, String, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin


class MemoryDataset(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "memory_dataset"
    __table_args__ = (UniqueConstraint("project_id", name="uq_memory_dataset_project"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cognee_dataset_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
