"""REQ-3 红灯:软删实体物理清理定时任务(90 天,留墓碑)· 服务层行为。

需求 e86329d1(设计规格书 §2.1 / §8.2)。红灯阶段本文件因目标模块缺失而失败;
实现后应全绿。本文件锁定以下契约,供「功能实现」任务遵循:

## 契约

- 入口:`app.services.physical_purge.purge_soft_deleted(
    db, *, now=None, retention_days=None) -> dict[str, int]`
  物理清理 `deleted_at <= now - retention_days` 的软删实体,返回
  「实体类型 → 物理删除行数」(未清理的类型可为 0 或缺省;允许额外键,如 document_version)。
  now 缺省取 UTC 当前时间;retention_days 缺省读 settings.physical_purge_retention_days。
- 保留期:默认 90 天,环境变量 PHYSICAL_PURGE_RETENTION_DAYS 可配置;
  边界语义:恰好满 90 天即清理(<= 判定),89 天不清理。
- 清理范围(按当前 schema 全覆盖):
  - requirement / task / document(级联 document_version 版本链)/
    comment(自身被软删的行)/ reference(自身被软删的行)/
    attachment(行 + storage_path 物理文件删除,配额随之释放)/ repository;
  - 「代码符号」模块已随需求 3f0a80fe(移除 API 参考文档模块)整体删除,当前 schema
    无对应表,本文件省略该类型;
  - project / user / activity / document_directory 等不在本需求清理枚举内。
- 墓碑(需求已敲定:留墓碑):指向被清理实体的 reference / comment / activity 行保留;
  展示层因 target 缺失渲染「已删除」(reference 面板 target_label 已有该语义);
  记忆锚点不参与业务软删,不在清理范围。
- restore 语义:物理清理后行已不存在,restore 系列入口必须抛 not_found(AppError),
  与现软删恢复语义一致,不得 500。
- 幂等:同一批数据重复执行,第二次零删除、零错误。
- 只清软删:deleted_at IS NULL 的行永不被清理(即使保留期取极端值 0)。
- activity 留痕:对可挂 activity 的类型(requirement / task / document / repository;
  comment / attachment 受 ck_comment/ck_activity_target_type 枚举约束不可挂)
  写 action="purge" 的 activity(执行者为空,系统操作)。

实现提示(sqlite 兼容):deleted_at 比较建议放 SQL 侧(where deleted_at <= cutoff,
与 _now() 同一绑定格式);清理后如在同一会话继续读取,注意 bulk delete 不同步
identity map,必要时 expire_all,避免命中已删行的缓存。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.errors import AppError
from app.models import (
    Activity,
    Attachment,
    Comment,
    Document,
    DocumentVersion,
    Reference,
    Repository,
    Requirement,
    Task,
)
from app.services import attachments as attachments_svc
from app.services import polymorphic as polymorphic_svc
from app.services import requirements as requirements_svc
from app.services import tasks as tasks_svc

# 红灯:目标模块尚不存在(REQ-3 任务 2「功能实现」补齐)
from app.services import physical_purge
from app.services.physical_purge import purge_soft_deleted


def db_scalar_entity(db, entity):
    from sqlalchemy import select as _select

    model = type(entity)
    if hasattr(model, "code"):  # 五类实体:复合主键 (project_id, code)
        return db.scalar(
            _select(model).where(
                model.project_id == entity.project_id, model.code == entity.code
            )
        )
    return db.get(model, entity.id)


DAY = timedelta(days=1)

# ck_comment/ck_activity_target_type 枚举内、且属于本需求清理范围的类型
ACTIVITY_TARGETABLE = ("requirement", "task", "document", "repository")


@pytest.fixture()
def now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture()
def isolated_storage(monkeypatch, tmp_path):
    """附件存储指向临时目录,与既有 test_attachments.isolated_storage 同款。"""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "attachment_storage_dir", str(tmp_path / "attachments"))
    yield tmp_path / "attachments"


@pytest.fixture()
def reset_settings_cache():
    """清空 get_settings 缓存,让环境变量在用例内生效;结束后再清防止泄漏。"""
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _seed_soft_deleted_all(db, project, admin, *, now: datetime, age_days: int) -> dict:
    """按清理范围各造一条 age_days 天前软删的实体,返回 {类型: 实例}。"""
    deleted_at = now - age_days * DAY
    r = Requirement(
        project_id=project.id, code="REQ-1", title="到期需求", status="in_progress", deleted_at=deleted_at
    )
    db.add(r)
    db.flush()
    t = Task(
        project_id=project.id,
        code=f"{r.code}-T1",
        title="到期任务",
        status="backlog",
        deleted_at=deleted_at,
        requirement_id=r.code,
    )
    d = Document(project_id=project.id, code="DOC-1", title="到期文档", doc_type="wiki", deleted_at=deleted_at)
    db.add_all([t, d])
    db.flush()
    c = Comment(
        project_id=project.id,
        target_type="requirement",
        target_id=r.code,
        author_id=admin.id,
        body="到期评论",
        deleted_at=deleted_at,
    )
    ref = Reference(
        project_id=project.id,
        from_type="task",
        from_id=t.code,
        to_type="requirement",
        to_id=r.code,
        type="mentions",
        created_by=admin.id,
        deleted_at=deleted_at,
    )
    repo = Repository(
        project_id=project.id,
        name="到期仓库",
        vcs_type="git",
        url="https://example.com/x/y.git",
        normalized_url="https://example.com/x/y.git",
        deleted_at=deleted_at,
    )
    att = Attachment(
        project_id=project.id,
        target_type="requirement",
        target_id=r.code,
        file_name="old.txt",
        size=10,
        storage_path="seeded/old.bin",
        created_by=admin.id,
        deleted_at=deleted_at,
    )
    db.add_all([c, ref, repo, att])
    db.flush()
    return {
        "requirement": r,
        "task": t,
        "document": d,
        "comment": c,
        "reference": ref,
        "repository": repo,
        "attachment": att,
    }


def _make_soft_deleted(db, project, admin, kind: str, *, now: datetime, age_days: int = 91):
    """单个类型的软删实体(restore 语义参数化用)。"""
    deleted_at = now - age_days * DAY
    if kind == "requirement":
        entity = Requirement(
            project_id=project.id, code="REQ-7", title="待清理需求", status="backlog", deleted_at=deleted_at
        )
    elif kind == "task":
        _r = Requirement(
            project_id=project.id, code="REQ-9", title="待清理任务挂载", status="backlog", deleted_at=deleted_at
        )
        db.add(_r)
        db.flush()
        entity = Task(
            project_id=project.id,
            code=f"{_r.code}-T9",
            title="待清理任务",
            status="backlog",
            deleted_at=deleted_at,
            requirement_id=_r.code,
        )
    elif kind == "document":
        entity = Document(
            project_id=project.id, code="DOC-9", title="待清理文档", doc_type="wiki", deleted_at=deleted_at
        )
    elif kind == "repository":
        entity = Repository(
            project_id=project.id,
            name="待清理仓库",
            vcs_type="git",
            url="https://example.com/a/b.git",
            normalized_url="https://example.com/a/b.git",
            deleted_at=deleted_at,
        )
    elif kind == "attachment":
        entity = Attachment(
            project_id=project.id,
            target_type="project",
            target_id=str(project.id),
            file_name="f.bin",
            size=1,
            storage_path="seeded/f.bin",
            created_by=admin.id,
            deleted_at=deleted_at,
        )
    else:
        raise ValueError(f"未知类型: {kind}")
    db.add(entity)
    db.flush()
    return entity


def _restore_entry(kind: str):
    """各类型 restore 服务入口(物理清理后应全部 not_found)。"""
    if kind == "requirement":
        return requirements_svc.restore_requirement
    if kind == "task":
        return tasks_svc.restore_task
    if kind == "document":
        from app.services import documents as documents_svc

        return documents_svc.restore_document
    if kind == "repository":
        from app.services import repositories as repositories_svc

        return repositories_svc.restore_repository
    if kind == "attachment":
        return attachments_svc.restore
    raise ValueError(f"未知类型: {kind}")


# ---------- a) 保留期边界 ----------


def test_retention_89_days_not_purged(db, world, now):
    seeded = _seed_soft_deleted_all(db, world["project"], world["admin"], now=now, age_days=89)
    report = purge_soft_deleted(db, now=now, retention_days=90)
    db.expire_all()
    for kind, entity in seeded.items():
        assert db_scalar_entity(db, entity) is not None, f"{kind} 未满保留期不应被清理"
    assert not any(report.values()), "89 天时报告应为零删除"


def test_retention_90_days_purged(db, world, now):
    seeded = _seed_soft_deleted_all(db, world["project"], world["admin"], now=now, age_days=90)
    report = purge_soft_deleted(db, now=now, retention_days=90)
    db.expire_all()
    for kind, entity in seeded.items():
        assert db_scalar_entity(db, entity) is None, f"{kind} 满 90 天应被物理清理"
    for kind in seeded:
        assert report[kind] == 1, f"{kind} 报告计数应为 1"
    # 版本链随文档一并消失
    assert (
        db.scalar(
            select(func.count())
            .select_from(DocumentVersion)
            .where(DocumentVersion.document_id == seeded["document"].code)
        )
        == 0
    )


def test_retention_days_env_configurable(db, world, now, monkeypatch, reset_settings_cache):
    monkeypatch.setenv("PHYSICAL_PURGE_RETENTION_DAYS", "30")
    from app.config import get_settings

    assert get_settings().physical_purge_retention_days == 30
    seeded = _seed_soft_deleted_all(db, world["project"], world["admin"], now=now, age_days=31)
    # 不显式传保留期 → 走环境变量配置的 30 天
    purge_soft_deleted(db, now=now)
    db.expire_all()
    for kind, entity in seeded.items():
        assert db_scalar_entity(db, entity) is None, f"{kind} 超环境变量保留期应被清理"


# ---------- b) 实体类型覆盖 ----------


def test_document_purge_cascades_version_chain(db, world, now):
    d = Document(
        project_id=world["project"].id,
        code="DOC-8",
        title="多版本文档",
        doc_type="wiki",
        deleted_at=now - 91 * DAY,
    )
    db.add(d)
    db.flush()
    db.add_all(
        [
            DocumentVersion(
                project_id=world["project"].id,
                document_id=d.code,
                title="多版本文档",
                content=f"第 {n} 版",
                version_no=n,
            )
            for n in (1, 2, 3)
        ]
    )
    db.flush()
    purge_soft_deleted(db, now=now, retention_days=90)
    db.expire_all()
    assert db_scalar_entity(db, d) is None
    assert (
        db.scalar(
            select(func.count())
            .select_from(DocumentVersion)
            .where(DocumentVersion.document_id == d.code)
        )
        == 0
    ), "文档物理清理应级联删除 document_version 版本链"


def test_attachment_purge_deletes_physical_file_and_frees_quota(
    db, world, now, isolated_storage
):
    project, admin, agent = world["project"], world["admin"], world["agent"]
    r = requirements_svc.create_requirement(db, admin, project.id, "带附件的需求")
    a = attachments_svc.upload(db, agent, project.id, "requirement", r.code, "old.txt", b"hello")
    path = attachments_svc._attachment_path(project.id, a.id)
    assert path.is_file(), "前置:附件文件应真实落盘"
    requirements_svc.delete_requirement(db, admin, r.code, confirm_task_count=0)
    # 时间流逝:需求与被级联软删的附件都超过保留期
    db_scalar_entity(db, r).deleted_at = now - 91 * DAY
    db.get(Attachment, a.id).deleted_at = now - 91 * DAY
    db.commit()

    purge_soft_deleted(db, now=now, retention_days=90)
    db.expire_all()

    assert db.get(Attachment, a.id) is None, "到期附件行应被物理清理"
    assert not path.exists(), "storage_path 指向的物理文件应被删除"
    used = db.scalar(
        select(func.coalesce(func.sum(Attachment.size), 0)).where(
            Attachment.project_id == project.id
        )
    )
    assert used == 0, "附件行删除后项目配额占用应释放"


# ---------- c) 墓碑语义 ----------


def test_tombstone_rows_retained_and_target_shows_deleted(db, world, now):
    project, admin = world["project"], world["admin"]
    r = requirements_svc.create_requirement(db, admin, project.id, "被引用的需求")
    r2 = requirements_svc.create_requirement(db, admin, project.id, "引用方任务挂载需求")
    requirements_svc.set_requirement_status(db, admin, r2.code, "backlog")
    t = tasks_svc.create_task(db, admin, project.id, "引用方任务", requirement_id=r2.code)
    polymorphic_svc.create_reference(db, admin, "task", t.code, "requirement", r.code, "mentions")
    polymorphic_svc.create_comment(db, admin, "requirement", r.code, "留下评论")
    requirements_svc.delete_requirement(db, admin, r.code, confirm_task_count=0)
    db_scalar_entity(db, r).deleted_at = now - 91 * DAY
    db.commit()

    purge_soft_deleted(db, now=now, retention_days=90)
    db.expire_all()

    assert db_scalar_entity(db, r) is None, "实体行应被物理清理"
    # 墓碑:指向被清理实体的评论/引用/活动行保留
    assert (
        db.scalar(
            select(func.count())
            .select_from(Comment)
            .where(Comment.target_type == "requirement", Comment.target_id == r.code)
        )
        >= 1
    ), "评论行应保留(墓碑)"
    assert (
        db.scalar(
            select(func.count())
            .select_from(Reference)
            .where(Reference.to_type == "requirement", Reference.to_id == r.code)
        )
        >= 1
    ), "引用行应保留(墓碑)"
    assert (
        db.scalar(
            select(func.count())
            .select_from(Activity)
            .where(Activity.target_type == "requirement", Activity.target_id == r.code)
        )
        >= 1
    ), "活动行应保留(墓碑)"
    # 展示层语义:目标不再解析(not_found),引用面板把目标渲染为「已删除」
    with pytest.raises(AppError) as e:
        polymorphic_svc.resolve_target(db, "requirement", r.code, user=admin)
    assert e.value.code == "not_found"
    page = polymorphic_svc.list_references(db, admin, "task", t.code, None, 50)
    assert page["items"], "前置:引用行仍出现在面板"
    assert page["items"][0]["to_title"] == "已删除", "清理后引用目标应展示墓碑「已删除」"


@pytest.mark.parametrize("kind", ["requirement", "task", "document", "repository", "attachment"])
def test_restore_after_purge_is_not_found_not_500(db, world, now, kind):
    entity = _make_soft_deleted(db, world["project"], world["admin"], kind, now=now)
    purge_soft_deleted(db, now=now, retention_days=90)
    db.expire_all()
    assert db_scalar_entity(db, entity) is None, "前置:实体已被物理清理"
    with pytest.raises(AppError) as e:
        _restore_entry(kind)(db, world["admin"], getattr(entity, "code", None) or entity.id)
    assert e.value.code == "not_found", "物理清理后 restore 应与软删语义一致(not_found)"


# ---------- d) 幂等 ----------


def test_purge_is_idempotent_second_run_noop(db, world, now):
    seeded = _seed_soft_deleted_all(db, world["project"], world["admin"], now=now, age_days=91)
    purge_soft_deleted(db, now=now, retention_days=90)
    db.expire_all()
    for kind, entity in seeded.items():
        assert db_scalar_entity(db, entity) is None
    second = purge_soft_deleted(db, now=now, retention_days=90)
    assert not any(second.values()), "第二次执行应零删除"
    db.expire_all()
    for kind, entity in seeded.items():
        assert db_scalar_entity(db, entity) is None


# ---------- e) 只清软删 ----------


def test_live_entities_never_purged(db, world, now):
    project, admin = world["project"], world["admin"]
    r = Requirement(project_id=project.id, code="REQ-3", title="活跃需求", status="in_progress")
    db.add(r)
    db.flush()
    r2 = Requirement(project_id=project.id, code="REQ-2", title="活跃任务挂载", status="backlog")
    db.add(r2)
    db.flush()
    t = Task(project_id=project.id, code=f"{r2.code}-T2", title="活跃任务", status="backlog", requirement_id=r2.code)
    d = Document(project_id=project.id, code="DOC-2", title="活跃文档", doc_type="wiki")
    c = Comment(
        project_id=project.id,
        target_type="requirement",
        target_id=r.code,
        author_id=admin.id,
        body="活跃评论",
    )
    # 先落 t/d:ref.from_id 需要任务真实主键(客户端默认主键 flush 时才生成)
    db.add_all([t, d, c])
    db.flush()
    ref = Reference(
        project_id=project.id,
        from_type="task",
        from_id=t.code,
        to_type="requirement",
        to_id=r.code,
        type="mentions",
        created_by=admin.id,
    )
    repo = Repository(
        project_id=project.id,
        name="活跃仓库",
        vcs_type="git",
        url="https://example.com/live/repo.git",
        normalized_url="https://example.com/live/repo.git",
    )
    att = Attachment(
        project_id=project.id,
        target_type="requirement",
        target_id=r.code,
        file_name="live.txt",
        size=3,
        storage_path="seeded/live.bin",
        created_by=admin.id,
    )
    db.add_all([ref, repo, att])
    # 刚软删(0 天)的实体:保留期取极端值 0 时应被清理,证明清理逻辑真实生效
    dead = Requirement(
        project_id=project.id, code="REQ-8", title="刚软删需求", status="backlog", deleted_at=now
    )
    db.add(dead)
    db.flush()

    purge_soft_deleted(db, now=now, retention_days=0)
    db.expire_all()

    for entity in (r, t, d, c, ref, repo, att):
        assert db_scalar_entity(db, entity) is not None, "未软删实体永不被清理"
    assert db_scalar_entity(db, dead) is None, "保留期 0 时软删行(即使刚删)应被清理"


# ---------- g) activity 留痕 ----------


def test_purge_records_activity_for_targetable_types(db, world, now):
    project, admin = world["project"], world["admin"]
    ids = {}
    for kind in ACTIVITY_TARGETABLE:
        entity = _make_soft_deleted(db, project, admin, kind, now=now)
        ids[kind] = getattr(entity, "code", None) or entity.id
    purge_soft_deleted(db, now=now, retention_days=90)
    db.expire_all()
    for etype, eid in ids.items():
        rows = db.scalars(
            select(Activity).where(
                Activity.project_id == project.id,
                Activity.target_type == etype,
                Activity.target_id == str(eid),
                Activity.action == "purge",
            )
        ).all()
        assert rows, f"{etype} 物理清理应写 action=purge 的 activity 留痕"
