"""软删实体物理清理服务(REQ-3 / 规格书 §2.1 / §8.2)。

- 范围:软删满保留期的 requirement / task / document(级联 document_version)/
  comment / reference / attachment(含 storage_path 物理文件)/ repository;
  「代码符号」表已随模块移除,project / user / activity / document_directory
  不在清理枚举内
- 边界:deleted_at <= now - retention_days(恰好满 90 天即清),比较放 SQL 侧,
  与 _now() 同一 UTC datetime 绑定格式
- 只清软删行:deleted_at IS NULL 永不命中;幂等可重跑(重复执行零删除)
- 墓碑:指向被清理实体的 reference / comment / activity 行保留;
  对可挂 activity 的类型(requirement / task / document / repository;comment /
  attachment 受 ck_*_target_type 枚举约束不可挂)写 action="purge" 留痕,
  执行者为空(系统操作,不产生站内通知)
- 附件:行删除后删除存储桶内的物理文件,配额随之释放;文件删除放在事务提交后,
  只删 storage root 内的路径,防止 storage_path 被篡改时误删任意文件
- 恢复语义:物理清理后行已不存在,各 restore 入口自然抛 not_found(AppError)
"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    Attachment,
    Comment,
    Document,
    DocumentVersion,
    Reference,
    Repository,
    Requirement,
    Task,
)
from .polymorphic import record_activity

# 可写 action="purge" activity 的类型(ck_activity_target_type 枚举内且属于清理范围)
ACTIVITY_TARGETABLE = ("requirement", "task", "document", "repository")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expired(column, cutoff: datetime) -> tuple:
    """软删且满保留期的过滤条件(只命中软删行,SQL 侧比较)。"""
    return (column.is_not(None), column <= cutoff)


def _attachment_file_paths(a: Attachment) -> list[Path]:
    """附件待删物理文件:storage_path 优先,规范路径兜底;仅保留存储桶内的路径。"""
    root = Path(get_settings().attachment_storage_dir).resolve()
    candidates: list[Path] = []
    storage = (a.storage_path or "").strip()
    if storage:
        candidates.append(Path(storage))
    if a.project_id is not None:
        from .attachments import _attachment_path

        candidates.append(_attachment_path(a.project_id, a.id))
    paths: list[Path] = []
    for raw in candidates:
        try:
            resolved = raw.resolve()
        except OSError:
            continue
        if resolved == root or root not in resolved.parents:
            continue  # 存储桶外(或根目录本身)一律不动,防误删
        if resolved not in paths:
            paths.append(resolved)
    return paths


def _remove_attachment_files(attachments: list[Attachment]) -> int:
    removed = 0
    for a in attachments:
        for path in _attachment_file_paths(a):
            if path.is_file():
                path.unlink()
                removed += 1
    return removed


def _record_purge_activities(db: Session, cutoff: datetime) -> int:
    """删除前收集到期实体并写 action="purge" activity(执行者为空)。"""
    recorded = 0
    for target_type in ACTIVITY_TARGETABLE:
        model = {
            "requirement": Requirement,
            "task": Task,
            "document": Document,
            "repository": Repository,
        }[target_type]
        id_column = model.code if target_type != "repository" else model.id
        rows = db.execute(
            select(id_column, model.project_id).where(*_expired(model.deleted_at, cutoff))
        ).all()
        for entity_id, project_id in rows:
            record_activity(
                db, project_id, None, target_type, entity_id, "purge", "物理清理(软删超过保留期)"
            )
            recorded += 1
    return recorded


def purge_soft_deleted(
    db: Session, *, now: datetime | None = None, retention_days: int | None = None
) -> dict[str, int]:
    """物理清理软删满保留期的实体,返回「实体类型 → 物理删除行数」。

    now 缺省取 UTC 当前时间;retention_days 缺省读 settings.physical_purge_retention_days。
    幂等:同一批数据重复执行第二次零删除、零错误。
    """
    if now is None:
        now = _now()
    if retention_days is None:
        retention_days = get_settings().physical_purge_retention_days
    cutoff = now - timedelta(days=retention_days)

    report: dict[str, int] = {}

    # 附件行先取全(需要 storage_path 在提交后删物理文件)
    attachments = db.scalars(
        select(Attachment).where(*_expired(Attachment.deleted_at, cutoff))
    ).all()

    _record_purge_activities(db, cutoff)

    # 版本链随文档一并物理删除(DB 无 FK 级联执行时也要成立,显式删);
    # 各 bulk delete 均以 synchronize_session="fetch" 把删除行同步移出
    # identity map(属性保留可读),避免同会话旧对象命中已删行缓存
    doc_rows = db.execute(
        select(Document.project_id, Document.code).where(*_expired(Document.deleted_at, cutoff))
    ).all()
    if doc_rows:
        from sqlalchemy import or_, tuple_

        conds = [
            (DocumentVersion.project_id == pid) & (DocumentVersion.document_id == code)
            for pid, code in doc_rows
        ]
        report["document_version"] = db.execute(
            delete(DocumentVersion).where(or_(*conds)).execution_options(synchronize_session="fetch")
        ).rowcount
    report["document"] = db.execute(
        delete(Document)
        .where(*_expired(Document.deleted_at, cutoff))
        .execution_options(synchronize_session="fetch")
    ).rowcount

    report["requirement"] = db.execute(
        delete(Requirement)
        .where(*_expired(Requirement.deleted_at, cutoff))
        .execution_options(synchronize_session="fetch")
    ).rowcount
    report["task"] = db.execute(
        delete(Task)
        .where(*_expired(Task.deleted_at, cutoff))
        .execution_options(synchronize_session="fetch")
    ).rowcount
    report["comment"] = db.execute(
        delete(Comment)
        .where(*_expired(Comment.deleted_at, cutoff))
        .execution_options(synchronize_session="fetch")
    ).rowcount
    report["reference"] = db.execute(
        delete(Reference)
        .where(*_expired(Reference.deleted_at, cutoff))
        .execution_options(synchronize_session="fetch")
    ).rowcount
    report["repository"] = db.execute(
        delete(Repository)
        .where(*_expired(Repository.deleted_at, cutoff))
        .execution_options(synchronize_session="fetch")
    ).rowcount
    report["attachment"] = db.execute(
        delete(Attachment)
        .where(*_expired(Attachment.deleted_at, cutoff))
        .execution_options(synchronize_session="fetch")
    ).rowcount

    db.commit()

    # 事务提交成功后再删物理文件:失败回滚不会丢文件
    _remove_attachment_files(attachments)

    # 兜底:清掉会话内其余过期状态,防同会话后续读取命中旧对象
    db.expire_all()
    return report
