"""短码核心(ADR 0002):计数器模型、分配与格式校验。

- 计数器:每项目每类型一行 (project_id, entity_type) → last_seq,持久化、只增不减。
- 分配:原子 UPDATE ... RETURNING 自增;行不存在时先 INSERT ON CONFLICT DO NOTHING 再自增。
- 校验:格式非法返回 invalid_request;旧 UUID 自然落入非法格式。
"""

import re
import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, insert, select, update
from sqlalchemy.orm import Mapped, mapped_column

from ..errors import invalid_request
from ..models.base import Base, TimestampMixin

# 实体类型 → 短码前缀(ADR 0002 决策 3)
CODE_PREFIXES = {
    "requirement": "REQ",
    "task": "TASK",
    "document": "DOC",  # doc_type=wiki
    "glossary_term": "TERM",  # document doc_type=glossary
    "document_directory": "DIR",
}

_CODE_PATTERN = {t: re.compile(rf"^{p}-([1-9][0-9]*)$") for t, p in CODE_PREFIXES.items()}
_CODE_PATTERN["task"] = re.compile(r"(?:TASK-[1-9][0-9]*|REQ-[1-9][0-9]*-T[1-9][0-9]*)")
# document 泛型寻址同时接受 Wiki(DOC)与词条(TERM);分配用 doc_type 专属键
_CODE_PATTERN["document"] = re.compile(r"^(DOC|TERM)-([1-9][0-9]*)$")


def is_valid_code(entity_type: str, code: str) -> bool:
    pattern = _CODE_PATTERN.get(entity_type)
    return bool(pattern and isinstance(code, str) and pattern.fullmatch(code))


def require_valid_code(entity_type: str, code: str) -> str:
    if not is_valid_code(entity_type, code):
        prefix = CODE_PREFIXES.get(entity_type, "?")
        example = "REQ-<需求序号>-T<任务序号>" if entity_type == "task" else f"{prefix}-<序号>"
        raise invalid_request(f"非法的短码格式(应为 {example},不补零): {code}")
    return code


class ShortCodeCounter(TimestampMixin, Base):
    """每项目每类型持久化计数器;last_seq 只增,序号不复用。"""

    __tablename__ = "short_code_counter"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    entity_type: Mapped[str] = mapped_column(String(24), primary_key=True)
    last_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


def allocate_code(db, project_id: uuid.UUID, entity_type: str, *, requirement_code: str | None = None) -> str:
    """分配一个新短码:并发安全(原子自增),不承诺绝对连续。调用方负责 commit。"""
    prefix = CODE_PREFIXES[entity_type] + "-"
    if entity_type == "task":
        require_valid_code("requirement", requirement_code)
        entity_type = requirement_code
        prefix = requirement_code + "-T"

    def _next_seq() -> int | None:
        row = db.execute(
            update(ShortCodeCounter)
            .where(
                ShortCodeCounter.project_id == project_id,
                ShortCodeCounter.entity_type == entity_type,
            )
            .values(last_seq=ShortCodeCounter.last_seq + 1)
            .returning(ShortCodeCounter.last_seq)
        ).scalar_one_or_none()
        return row

    seq = _next_seq()
    if seq is None:
        # 首次分配:建行(主键冲突即他人已建),再自增
        values = {"project_id": project_id, "entity_type": entity_type, "last_seq": 0}
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            db.execute(pg_insert(ShortCodeCounter).values(**values).on_conflict_do_nothing())
        else:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            db.execute(sqlite_insert(ShortCodeCounter).values(**values).on_conflict_do_nothing())
        seq = _next_seq()
        if seq is None:  # pragma: no cover - 极端并发下的防御
            seq = db.execute(
                select(ShortCodeCounter.last_seq).where(
                    ShortCodeCounter.project_id == project_id,
                    ShortCodeCounter.entity_type == entity_type,
                )
            ).scalar_one() + 1
    return f"{prefix}{seq}"
