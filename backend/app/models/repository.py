"""Project-scoped source-code repository records.

Repositories only describe a code source.  They never contain credentials and
are not a local checkout or a synchronization job.
"""

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedByMixin, IdMixin, ProjectScopeMixin, SoftDeleteMixin, TimestampMixin


REPOSITORY_VCS_TYPES = ("git", "svn", "other")


class Repository(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin, Base):
    __tablename__ = "repository"
    __table_args__ = (
        CheckConstraint(f"vcs_type IN {REPOSITORY_VCS_TYPES}", name="ck_repository_vcs_type"),
        CheckConstraint(
            "(vcs_type = 'other' AND other_vcs_type IS NOT NULL) OR "
            "(vcs_type IN ('git', 'svn') AND other_vcs_type IS NULL)",
            name="ck_repository_other_vcs_type",
        ),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    vcs_type: Mapped[str] = mapped_column(String(16), nullable=False)
    other_vcs_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(256), nullable=True)
