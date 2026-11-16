"""Wiki 文档领域服务(REQ-59:过程记录式 LLM 知识层)。

- glossary 合并进 wiki:doc_type 仅 'wiki',TERM-n 短码保留,Directory 废弃;
- frontmatter 解析管线:正文顶部可选 YAML(summary/doc_kind/tags/aliases),写入时合并进 doc_metadata;
- [[双链]]:写入时解析落 doc_link 表,断链行保留(to_code NULL)+保存响应警告;
- 溯源:页面/版本投影 author(人名或 agent 名+其主人,ADR 0004);
- INDEX:后端从 frontmatter 投影生成(kind 分节+未分类兜底+lint 信号),零维护。
"""

from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone

import yaml
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found
from ..models import Document, DocLink, DocumentVersion, Reference, User
from .pagination import decode_cursor, page_result
from .permissions import get_accessible_project, require_project_role
from .polymorphic import _ref_dict, record_activity

DOC_TYPES = ("wiki",)

# 九形态(Q2④ 裁定):约定值,系统不硬校验(未知值原样保留,INDEX 自成节)
DOC_KINDS = (
    "decision",
    "incident",
    "preference",
    "concept",
    "entity",
    "comparison",
    "research",
    "howto",
    "spec",
)
DOC_KIND_LABELS = {
    "decision": "决策",
    "incident": "事故",
    "preference": "偏好",
    "concept": "概念",
    "entity": "实体",
    "comparison": "对比",
    "research": "调研",
    "howto": "操作指南",
    "spec": "规格",
}
UNCATEGORIZED_LABEL = "未分类"

# 标题/别名禁止的链接语法字符([[..]]、|、# 小节分隔)
TITLE_FORBIDDEN_CHARS = ("[", "]", "|", "#")

FRONTMATTER_KEYS = ("summary", "doc_kind", "tags", "aliases")

INDEX_SUMMARY_FALLBACK_LENGTH = 120

_UNSET = object()

_SHORT_CODE_RE = re.compile(r"^(DOC|TERM)-[1-9][0-9]*$", re.IGNORECASE)
# [[目标|显示文本]]:目标可含 #小节;目标/显示文本不含 [ ] | 以避免嵌套歧义
_LINK_RE = re.compile(r"\[\[\s*([^\[\]|]+?)\s*(?:\|\s*([^\[\]|]+?)\s*)?\]\]")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_module(module: str) -> None:
    if module not in DOC_TYPES:
        raise invalid_request("不支持的文档模块(wiki 与词条已合并,统一为 wiki)")


# --------------------------------------------------------------------------
# frontmatter 解析(REQ-59 ①:D4 summary 创作时写 + 九形态 doc_kind)
# --------------------------------------------------------------------------


def split_frontmatter(content: str | None) -> tuple[dict, str]:
    """拆出正文顶部 YAML frontmatter。

    返回 (frontmatter_dict, body);无 frontmatter 或解析失败时原样返回正文
    (frontmatter 属正文一部分,存储不剥离,仅读取侧拆分)。
    """
    if not content:
        return {}, content or ""
    if not content.startswith("---"):
        return {}, content
    lines = content.splitlines()
    if len(lines) < 2:
        return {}, content
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        return {}, content
    block = "\n".join(lines[1:closing])
    try:
        parsed = yaml.safe_load(block)
    except yaml.YAMLError:
        return {}, content
    if not isinstance(parsed, dict):
        return {}, content
    body = "\n".join(lines[closing + 1 :])
    return _normalize_frontmatter(parsed), body


def _normalize_frontmatter(parsed: dict) -> dict:
    """类型宽松归一:tags/aliases 接受 str 或 list;summary/doc_kind 保留 str。

    系统不硬校验 doc_kind 取值(九形态为约定值,未知值原样保留)。
    """
    normalized: dict = {}
    for key, value in parsed.items():
        if key in ("tags", "aliases"):
            if isinstance(value, str):
                normalized[key] = [item.strip() for item in value.split(",") if item.strip()]
            elif isinstance(value, list):
                normalized[key] = [str(item).strip() for item in value if str(item).strip()]
        elif key in ("summary", "doc_kind"):
            if isinstance(value, str):
                normalized[key] = value.strip()
        else:
            normalized[key] = value
    return normalized


def merge_metadata(base: dict | None, frontmatter: dict | None) -> dict:
    """显式 metadata(或存量 doc_metadata)与 frontmatter 合并:frontmatter 键优先。"""
    merged = copy.deepcopy(base or {})
    if frontmatter:
        merged.update(copy.deepcopy(frontmatter))
    return merged


def _validate_title_text(title: str) -> str:
    title = title.strip()
    if not title:
        raise invalid_request("标题不能为空")
    for char in TITLE_FORBIDDEN_CHARS:
        if char in title:
            raise invalid_request(
                f"标题不能包含链接语法字符 {' '.join(TITLE_FORBIDDEN_CHARS)}(双链解析歧义)"
            )
    return title


def _validate_aliases(metadata: dict) -> None:
    aliases = metadata.get("aliases")
    if aliases is None:
        return
    if not isinstance(aliases, list):
        aliases = [aliases]
    for alias in aliases:
        for char in TITLE_FORBIDDEN_CHARS:
            if char in str(alias):
                raise invalid_request(
                    f"别名不能包含链接语法字符 {' '.join(TITLE_FORBIDDEN_CHARS)}(双链解析歧义)"
                )


# --------------------------------------------------------------------------
# 溯源投影(REQ-59 ④:人名或 agent 名+其主人)
# --------------------------------------------------------------------------


class _UserCache:
    """一次请求内批量解析 user,避免 N+1。"""

    def __init__(self, db: Session):
        self.db = db
        self._users: dict[uuid.UUID, User] = {}

    def get(self, user_id: uuid.UUID | None) -> User | None:
        if user_id is None:
            return None
        if user_id not in self._users:
            self._users[user_id] = self.db.get(User, user_id)
        return self._users.get(user_id)

    def author(self, user_id: uuid.UUID | None) -> dict | None:
        user = self.get(user_id)
        if user is None:
            return None
        owner = self.get(user.owner_id) if user.is_agent and user.owner_id else None
        return {
            "id": str(user.id),
            "username": user.username,
            "nickname": user.nickname,
            "is_agent": user.is_agent,
            "owner": (
                {
                    "id": str(owner.id),
                    "username": owner.username,
                    "nickname": owner.nickname,
                }
                if owner is not None
                else None
            ),
        }


# --------------------------------------------------------------------------
# 文档行投影
# --------------------------------------------------------------------------


def _document_dict(
    db: Session,
    document: Document,
    warning: dict | None = None,
    with_links: bool = False,
    user_cache: _UserCache | None = None,
) -> dict:
    cache = user_cache or _UserCache(db)
    result = {
        "id": document.code,
        "node_kind": "document",
        "title": document.title,
        "doc_type": document.doc_type,
        "content": document.content,
        "metadata": copy.deepcopy(document.doc_metadata or {}),
        "project_id": str(document.project_id),
        "parent_id": document.parent_id,
        "created_by": str(document.created_by) if document.created_by else None,
        "author": cache.author(document.created_by),
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
        "deleted_at": document.deleted_at.isoformat() if document.deleted_at else None,
        "has_children": _document_has_children(db, document),
    }
    if with_links:
        result["links"] = _links_payload(db, document)
    if warning is not None:
        result["reference_warning"] = warning
    return result


def _version_dict(version: DocumentVersion, user_cache: _UserCache | None = None) -> dict:
    author = user_cache.author(version.created_by) if user_cache is not None else None
    return {
        "id": str(version.id),
        "version_no": version.version_no,
        "title": version.title,
        "content": version.content,
        "metadata": copy.deepcopy(version.doc_metadata or {}),
        "created_by": str(version.created_by) if version.created_by else None,
        "author": author,
        "created_at": version.created_at.isoformat(),
    }


def _document_has_children(db: Session, document: Document) -> bool:
    return db.scalar(
        select(Document.code).where(
            Document.project_id == document.project_id,
            Document.parent_id == document.code,
            Document.deleted_at.is_(None),
        ).limit(1)
    ) is not None


# --------------------------------------------------------------------------
# [[双链]]解析与落表(REQ-59 ②:W1/D5)
# --------------------------------------------------------------------------


class _LinkResolver:
    """项目内目标解析:短码精确 → 标题精确 → 别名精确(同名多义视为断链)。"""

    def __init__(self, db: Session, project_id: uuid.UUID):
        self.by_code: dict[str, str] = {}
        self.by_title: dict[str, list[str]] = {}
        self.by_alias: dict[str, list[str]] = {}
        rows = db.execute(
            select(Document.code, Document.title, Document.doc_metadata).where(
                Document.project_id == project_id,
                Document.deleted_at.is_(None),
            )
        ).all()
        for code, title, metadata in rows:
            self.by_code[code] = title
            self.by_title.setdefault(title, []).append(code)
            for alias in (metadata or {}).get("aliases") or []:
                if isinstance(alias, str) and alias:
                    self.by_alias.setdefault(alias, []).append(code)

    def resolve(self, target: str) -> tuple[str | None, str | None]:
        """返回 (to_code, 断链原因);命中时原因为 None。"""
        if _SHORT_CODE_RE.match(target):
            code = target.upper()
            if code in self.by_code:
                return code, None
            return None, f"短码 {target} 不存在或已删除"
        codes = self.by_title.get(target)
        if codes:
            if len(codes) == 1:
                return codes[0], None
            return None, f"标题「{target}」存在多个同名页面({', '.join(codes)}),建议改用短码链接"
        codes = self.by_alias.get(target)
        if codes:
            if len(codes) == 1:
                return codes[0], None
            return None, f"别名「{target}」命中多个页面({', '.join(codes)}),建议改用短码链接"
        return None, f"未找到标题或别名为「{target}」的页面"


def parse_wiki_links(content: str | None) -> list[dict]:
    """解析正文(去 frontmatter)中的 [[双链]],返回去重后的链接描述列表。"""
    _frontmatter, body = split_frontmatter(content)
    seen: set[tuple[str, str | None, str | None]] = set()
    links: list[dict] = []
    for match in _LINK_RE.finditer(body):
        target_part, display = match.group(1), match.group(2)
        section = None
        if "#" in target_part:
            target_part, _, section = target_part.partition("#")
            target_part = target_part.strip()
            section = section.strip() or None
        if not target_part:
            continue
        display = (display or "").strip() or None
        key = (target_part, display, section)
        if key in seen:
            continue
        seen.add(key)
        links.append({"target": target_part, "display": display, "section": section})
    return links


def sync_doc_links(db: Session, document: Document) -> list[dict]:
    """写入时落表:整表替换该文档的 doc_link 行,返回断链警告(不阻塞保存)。

    断链行保留(to_code NULL + raw_text 原文),目标页创建后重新保存源页即可接上。
    """
    db.execute(
        delete(DocLink).where(
            DocLink.project_id == document.project_id,
            DocLink.from_code == document.code,
        )
    )
    resolver = _LinkResolver(db, document.project_id)
    warnings: list[dict] = []
    for link in parse_wiki_links(document.content):
        to_code, reason = resolver.resolve(link["target"])
        if to_code is None:
            warnings.append({"raw_text": link["target"], "reason": reason, "display": link["display"]})
        db.add(
            DocLink(
                project_id=document.project_id,
                from_code=document.code,
                to_code=to_code,
                raw_text=link["target"][:256],
                display_text=(link["display"] or "")[:256] or None,
                section=(link["section"] or "")[:256] or None,
            )
        )
    db.flush()
    return warnings


def _link_warning(warnings: list[dict]) -> dict | None:
    if not warnings:
        return None
    return {"count": len(warnings), "items": warnings}


def _links_payload(db: Session, document: Document) -> dict:
    """详情聚合:正向链接(含断链)+ 反向链接(谁链我)。"""
    code_map: dict[str, Document] = {}
    missing_codes: set[str] = set()

    def _load(codes: set[str]) -> None:
        todo = {code for code in codes if code} - code_map.keys() - missing_codes
        if not todo:
            return
        for doc in db.scalars(
            select(Document).where(
                Document.project_id == document.project_id,
                Document.code.in_(todo),
            )
        ).all():
            code_map[doc.code] = doc
        for code in todo - code_map.keys():
            missing_codes.add(code)

    outgoing_rows = db.scalars(
        select(DocLink)
        .where(DocLink.project_id == document.project_id, DocLink.from_code == document.code)
        .order_by(DocLink.created_at, DocLink.id)
    ).all()
    _load({row.to_code for row in outgoing_rows if row.to_code})
    outgoing = []
    for row in outgoing_rows:
        target = code_map.get(row.to_code) if row.to_code else None
        target_live = target is not None and target.deleted_at is None
        outgoing.append(
            {
                "raw_text": row.raw_text,
                "display": row.display_text,
                "section": row.section,
                "to_code": row.to_code,
                "to_title": target.title if target_live else None,
                "broken": not target_live,
            }
        )

    incoming_rows = db.scalars(
        select(DocLink)
        .where(DocLink.project_id == document.project_id, DocLink.to_code == document.code)
        .order_by(DocLink.created_at, DocLink.id)
    ).all()
    _load({row.from_code for row in incoming_rows})
    incoming = []
    for row in incoming_rows:
        source = code_map.get(row.from_code)
        if source is None or source.deleted_at is not None:
            continue
        incoming.append(
            {
                "from_code": row.from_code,
                "from_title": source.title,
                "raw_text": row.raw_text,
                "display": row.display_text,
                "section": row.section,
            }
        )
    return {
        "outgoing": outgoing,
        "incoming": incoming,
        "broken_count": sum(1 for item in outgoing if item["broken"]),
    }


# --------------------------------------------------------------------------
# 取用与校验
# --------------------------------------------------------------------------


def _get_document_raw(db: Session, project_id: uuid.UUID, code: str) -> Document:
    from .short_codes import require_valid_code

    require_valid_code("document", code)
    document = db.scalar(
        select(Document).where(Document.project_id == project_id, Document.code == code)
    )
    if document is None:
        raise not_found("文档不存在")
    return document


def _visible_document(
    db: Session, user: User, document_id: str, include_deleted: bool = False,
    project_id: uuid.UUID | None = None,
) -> Document:
    from .short_code_lookup import resolve_by_code
    from .short_codes import require_valid_code

    require_valid_code("document", document_id)
    if include_deleted:
        # 恢复语义:允许已删行,扫描同码已删文档(显式 project_id 时仅限该项目)
        from .projects import list_projects

        if project_id is not None:
            get_accessible_project(db, user.id, project_id, min_level="viewer")
            project_ids = [project_id]
        else:
            projects = [p for p, _r in list_projects(db, user)]
            project_ids = [p.id for p in projects]
        rows = db.scalars(
            select(Document).where(
                Document.code == document_id,
                Document.project_id.in_(project_ids),
                Document.deleted_at.is_not(None),
            )
        ).all()
        if not rows:
            raise not_found("文档不存在")
        if len(rows) > 1:
            raise invalid_request(f"短码 {document_id} 在多个项目中存在,请通过项目内接口访问")
        document = rows[0]
        get_accessible_project(db, user.id, document.project_id, min_level="viewer")
        return document
    document, _project = resolve_by_code(db, user, "document", document_id, project_id=project_id)
    return document


def _editable_document(
    db: Session, user: User, document_id: str, include_deleted: bool = False,
    project_id: uuid.UUID | None = None,
) -> Document:
    document = _visible_document(db, user, document_id, include_deleted, project_id=project_id)
    require_project_role(db, user.id, document.project_id, min_level="editor")
    return document


def get_document(
    db: Session, user: User, document_id: str, module: str | None = None,
    project_id: uuid.UUID | None = None,
) -> Document:
    document = _visible_document(db, user, document_id, project_id=project_id)
    if module is not None and document.doc_type != module:
        raise not_found("文档不存在")
    return document


def _validate_location(
    db: Session,
    project_id: uuid.UUID,
    parent_id: str | None,
    document_id: str | None = None,
) -> None:
    from .short_codes import require_valid_code

    if parent_id is None:
        return
    require_valid_code("document", parent_id)
    parent = _get_document_raw(db, project_id, parent_id)
    if parent.code == document_id:
        raise invalid_request("不能将 Wiki 移动到自身")
    if parent.deleted_at is not None or parent.project_id != project_id:
        raise invalid_request("父 Wiki 必须属于同项目且未删除")
    if document_id is not None and parent.code in _wiki_subtree_ids(db, project_id, document_id):
        raise invalid_request("不能将 Wiki 移动到其后代")


def _assert_document_title_unique(
    db: Session,
    project_id: uuid.UUID,
    title: str,
    parent_id: str | None,
    exclude_ids: set[str] | None = None,
) -> None:
    exclude_ids = exclude_ids or set()
    rows = db.scalars(
        select(Document.code).where(
            Document.project_id == project_id,
            Document.deleted_at.is_(None),
            Document.title == title,
            Document.parent_id == parent_id,
        )
    ).all()
    if any(code not in exclude_ids for code in rows):
        raise conflict("同级 Wiki 标题已存在")


def _create_version(db: Session, document: Document, actor_id: uuid.UUID) -> DocumentVersion:
    next_no = (
        db.scalar(
            select(DocumentVersion.version_no)
            .where(
                DocumentVersion.project_id == document.project_id,
                DocumentVersion.document_id == document.code,
            )
            .order_by(DocumentVersion.version_no.desc())
            .limit(1)
        )
        or 0
    ) + 1
    version = DocumentVersion(
        project_id=document.project_id,
        document_id=document.code,
        version_no=next_no,
        title=document.title,
        content=document.content or "",
        doc_metadata=copy.deepcopy(document.doc_metadata or {}),
        created_by=actor_id,
    )
    db.add(version)
    db.flush()
    old_ids = db.scalars(
        select(DocumentVersion.id)
        .where(
            DocumentVersion.project_id == document.project_id,
            DocumentVersion.document_id == document.code,
        )
        .order_by(DocumentVersion.version_no.desc())
        .offset(20)
    ).all()
    if old_ids:
        db.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(old_ids)))
    return version


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------


def create_document(
    db: Session,
    actor: User,
    project_id: uuid.UUID,
    title: str,
    doc_type: str,
    content: str | None,
    metadata: dict | None,
    parent_id: str | None = None,
    directory_id: str | None = None,
) -> tuple[Document, dict | None]:
    from .short_codes import allocate_code

    _require_module(doc_type)
    if directory_id:
        raise invalid_request("目录已废弃(词条并入 wiki,统一走父文档树)")
    require_project_role(db, actor.id, project_id, min_level="editor")
    title = _validate_title_text(title)
    _validate_location(db, project_id, parent_id)
    _assert_document_title_unique(db, project_id, title, parent_id)
    frontmatter, _body = split_frontmatter(content)
    doc_metadata = merge_metadata(metadata, frontmatter)
    _validate_aliases(doc_metadata)
    code = allocate_code(db, project_id, "document")
    document = Document(
        project_id=project_id,
        code=code,
        title=title,
        doc_type="wiki",
        content=content or "",
        doc_metadata=doc_metadata,
        parent_id=parent_id,
        created_by=actor.id,
    )
    db.add(document)
    db.flush()
    warnings = sync_doc_links(db, document)
    _create_version(db, document, actor.id)
    record_activity(db, project_id, actor.id, "document", code, "create", "创建 wiki 文档")
    db.commit()
    return document, _link_warning(warnings)


def update_document(
    db: Session,
    actor: User,
    document_id: str,
    title: str | None = None,
    content: str | None = None,
    metadata: object = _UNSET,
    project_id: uuid.UUID | None = None,
) -> tuple[Document, dict | None]:
    document = _editable_document(db, actor, document_id, project_id=project_id)
    if title is not None:
        title = _validate_title_text(title)
        _assert_document_title_unique(db, document.project_id, title, document.parent_id, {document.code})
        document.title = title
    if content is not None:
        document.content = content
    if metadata is not _UNSET:
        if not isinstance(metadata, dict):
            raise invalid_request("metadata 必须是对象")
        base: dict | None = metadata
    else:
        base = document.doc_metadata
    frontmatter, _body = split_frontmatter(document.content)
    document.doc_metadata = merge_metadata(base, frontmatter)
    _validate_aliases(document.doc_metadata)
    warnings = sync_doc_links(db, document)
    _create_version(db, document, actor.id)
    record_activity(db, document.project_id, actor.id, "document", document.code, "save", "保存文档版本")
    db.commit()
    return document, _link_warning(warnings)


def move_document(
    db: Session,
    actor: User,
    document_id: str,
    parent_id: str | None = None,
    directory_id: str | None = None,
    project_id: uuid.UUID | None = None,
) -> Document:
    if directory_id:
        raise invalid_request("目录已废弃(词条并入 wiki,统一走父文档树)")
    document = _editable_document(db, actor, document_id, project_id=project_id)
    _validate_location(db, document.project_id, parent_id, document.code)
    _assert_document_title_unique(db, document.project_id, document.title, parent_id, {document.code})
    document.parent_id = parent_id
    record_activity(db, document.project_id, actor.id, "document", document.code, "move", "调整文档归属")
    db.commit()
    return document


def _wiki_subtree_ids(db: Session, project_id: uuid.UUID, root_code: str) -> set[str]:
    found: set[str] = set()
    pending = [root_code]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(
            db.scalars(
                select(Document.code).where(
                    Document.project_id == project_id,
                    Document.parent_id == current,
                )
            ).all()
        )
    return found


def delete_impact_document(
    db: Session, user: User, document_id: str, project_id: uuid.UUID | None = None
) -> dict:
    document = _visible_document(db, user, document_id, project_id=project_id)
    ids = _wiki_subtree_ids(db, document.project_id, document.code)
    return {"documents": len(ids)}


def delete_document(
    db: Session, actor: User, document_id: str, project_id: uuid.UUID | None = None
) -> None:
    document = _editable_document(db, actor, document_id, project_id=project_id)
    ids = _wiki_subtree_ids(db, document.project_id, document.code)
    rows = db.scalars(
        select(Document).where(
            Document.project_id == document.project_id,
            Document.code.in_(ids),
            Document.deleted_at.is_(None),
        )
    ).all()
    timestamp = _now()
    for row in rows:
        row.deleted_at = timestamp
    # 被删文档的出链行一并清理;入链行保留(渲染为断链,目标已删)
    db.execute(
        delete(DocLink).where(
            DocLink.project_id == document.project_id,
            DocLink.from_code.in_(ids),
        )
    )
    from .attachments import soft_delete_for_target

    for row in rows:
        soft_delete_for_target(db, row.project_id, "document", row.code)
    record_activity(db, document.project_id, actor.id, "document", document.code, "delete", f"递归删除 {len(rows)} 篇文档")
    db.commit()


def _validate_restore_documents(db: Session, documents: list[Document]) -> None:
    ids = {document.code for document in documents}
    for document in documents:
        if document.parent_id and document.parent_id not in ids:
            parent = _get_document_raw(db, document.project_id, document.parent_id)
            if parent.deleted_at is not None:
                raise conflict("恢复失败:父 Wiki 已删除")
        _assert_document_title_unique(
            db,
            document.project_id,
            document.title,
            document.parent_id,
            ids,
        )


def restore_document(
    db: Session, actor: User, document_id: str, project_id: uuid.UUID | None = None
) -> Document:
    document = _editable_document(
        db, actor, document_id, include_deleted=True, project_id=project_id
    )
    if document.deleted_at is None:
        raise not_found("已删除的文档不存在")
    ids = _wiki_subtree_ids(db, document.project_id, document.code)
    rows = db.scalars(
        select(Document).where(
            Document.project_id == document.project_id, Document.code.in_(ids)
        )
    ).all()
    _validate_restore_documents(db, rows)
    for row in rows:
        row.deleted_at = None
    # 恢复后按当前正文重建出链(目标可能仍在或已变)
    for row in sorted(rows, key=lambda row: row.code):
        sync_doc_links(db, row)
    record_activity(db, document.project_id, actor.id, "document", document.code, "restore", f"递归恢复 {len(rows)} 篇文档")
    db.commit()
    return document


# --------------------------------------------------------------------------
# 树/列表/版本
# --------------------------------------------------------------------------


def list_module_children(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    module: str,
    parent_id: str | None,
    cursor: str | None,
    limit: int,
) -> dict:
    _require_module(module)
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    filters = {"project_id": str(project_id), "module": module, "parent_id": parent_id}
    offset = decode_cursor(filters, cursor)
    rows = db.scalars(
        select(Document).where(
            Document.project_id == project_id,
            Document.doc_type == "wiki",
            Document.parent_id == parent_id,
            Document.deleted_at.is_(None),
        )
    ).all()
    cache = _UserCache(db)
    for row in rows:
        cache.get(row.created_by)
    nodes = [
        _document_dict(db, row, user_cache=cache)
        for row in sorted(rows, key=lambda row: row.title.casefold())
    ]
    page = nodes[offset:offset + limit]
    return page_result(page, offset, limit, filters)


def list_deleted_nodes(db: Session, user: User, project_id: uuid.UUID, module: str, cursor: str | None, limit: int) -> dict:
    _require_module(module)
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    filters = {"project_id": str(project_id), "module": module, "deleted": True}
    offset = decode_cursor(filters, cursor)
    documents = db.scalars(
        select(Document).where(
            Document.project_id == project_id,
            Document.doc_type == "wiki",
            Document.deleted_at.is_not(None),
        )
    ).all()
    nodes: list[dict] = [_document_dict(db, row) for row in documents]
    nodes.sort(key=lambda item: item["title"].casefold())
    page = nodes[offset:offset + limit]
    return page_result(page, offset, limit, filters)


def ancestor_path(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    module: str,
    node_kind: str,
    node_id: str,
) -> dict:
    _require_module(module)
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    if node_kind != "document":
        raise invalid_request("节点类型无效(wiki 单模块,仅 document)")
    node = _visible_document(db, user, node_id, project_id=project_id)
    if node.project_id != project_id or node.doc_type != "wiki":
        raise not_found("文档不存在")
    chain: list[Document] = []
    current: Document | None = node
    while current is not None:
        chain.append(current)
        current = (
            _get_document_raw(db, project_id, current.parent_id) if current.parent_id else None
        )
    return {"items": [_document_dict(db, item) for item in reversed(chain)]}


def list_versions(
    db: Session, user: User, document_id: str, module: str | None = None,
    project_id: uuid.UUID | None = None,
) -> list[dict]:
    document = get_document(db, user, document_id, module, project_id=project_id)
    versions = db.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.project_id == document.project_id,
            DocumentVersion.document_id == document.code,
        )
        .order_by(DocumentVersion.version_no.desc())
    ).all()
    cache = _UserCache(db)
    for version in versions:
        cache.get(version.created_by)
    return [_version_dict(version, cache) for version in versions]


def rollback_document(
    db: Session, actor: User, document_id: str, version_no: int, module: str | None = None,
    project_id: uuid.UUID | None = None,
) -> tuple[Document, dict | None]:
    document = _editable_document(db, actor, document_id, project_id=project_id)
    if module is not None and document.doc_type != module:
        raise not_found("文档不存在")
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.project_id == document.project_id,
            DocumentVersion.document_id == document.code,
            DocumentVersion.version_no == version_no,
        )
    )
    if version is None:
        raise not_found("文档版本不存在")
    _assert_document_title_unique(
        db, document.project_id, version.title, document.parent_id, {document.code}
    )
    document.title = version.title
    document.content = version.content
    document.doc_metadata = copy.deepcopy(version.doc_metadata or {})
    warnings = sync_doc_links(db, document)
    created = _create_version(db, document, actor.id)
    record_activity(db, document.project_id, actor.id, "document", document.code, "rollback", f"回滚至版本 {version_no}(生成版本 {created.version_no})")
    db.commit()
    return document, _link_warning(warnings)


# --------------------------------------------------------------------------
# INDEX 后端投影(REQ-59 ⑤:零维护,kind 分节+未分类兜底+lint 信号)
# --------------------------------------------------------------------------


def _index_summary(document: Document) -> str:
    metadata = document.doc_metadata or {}
    summary = metadata.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    _frontmatter, body = split_frontmatter(document.content)
    flattened = " ".join(body.split())
    return flattened[:INDEX_SUMMARY_FALLBACK_LENGTH]


def _index_row(document: Document, cache: _UserCache) -> dict:
    metadata = document.doc_metadata or {}
    raw_kind = metadata.get("doc_kind")
    kind = raw_kind if isinstance(raw_kind, str) and raw_kind.strip() else None
    summary = metadata.get("summary")
    has_summary = isinstance(summary, str) and bool(summary.strip())
    return {
        "id": document.code,
        "title": document.title,
        "doc_kind": kind,
        "summary": _index_summary(document),
        "missing_summary": not has_summary,
        "updated_at": document.updated_at.isoformat(),
        "author": cache.author(document.created_by),
    }


def project_index(db: Session, user: User, project_id: uuid.UUID) -> dict:
    """项目知识 INDEX:从 frontmatter 投影,不存页、零维护(每项目自动生成、永不失真)。"""
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    documents = db.scalars(
        select(Document).where(
            Document.project_id == project_id,
            Document.doc_type == "wiki",
            Document.deleted_at.is_(None),
        )
    ).all()
    cache = _UserCache(db)
    for document in documents:
        cache.get(document.created_by)
    rows = sorted(
        (_index_row(document, cache) for document in documents),
        key=lambda row: row["updated_at"],
        reverse=True,
    )
    by_kind: dict[str, list[dict]] = {}
    for row in rows:
        by_kind.setdefault(row["doc_kind"] or "", []).append(row)
    sections = []
    for kind in DOC_KINDS:
        if kind in by_kind:
            sections.append({"kind": kind, "label": DOC_KIND_LABELS[kind], "items": by_kind.pop(kind)})
    for kind in sorted(k for k in by_kind if k):
        sections.append({"kind": kind, "label": kind, "items": by_kind.pop(kind)})
    if "" in by_kind:
        sections.append({"kind": None, "label": UNCATEGORIZED_LABEL, "items": by_kind.pop("")})
    broken = db.scalars(
        select(DocLink).where(DocLink.project_id == project_id, DocLink.to_code.is_(None))
    ).all()
    title_map = {document.code: document.title for document in documents}
    lint = {
        "missing_kind": [
            {"id": row["id"], "title": row["title"]} for row in rows if not row["doc_kind"]
        ],
        "missing_summary": [
            {"id": row["id"], "title": row["title"]} for row in rows if row["missing_summary"]
        ],
        "broken_links": [
            {
                "from": link.from_code,
                "from_title": title_map.get(link.from_code),
                "raw_text": link.raw_text,
            }
            for link in broken
            if link.from_code in title_map
        ],
    }
    return {
        "project_id": str(project_id),
        "total": len(rows),
        "sections": sections,
        "lint": lint,
    }


# --------------------------------------------------------------------------
# 引用(既有 ref API 的双向聚合,保留)
# --------------------------------------------------------------------------


def _reverse_references(db: Session, document: Document) -> dict:
    refs = db.scalars(
        select(Reference).where(
            Reference.deleted_at.is_(None),
            Reference.project_id == document.project_id,
            or_(
                (Reference.to_type == "document") & (Reference.to_id == document.code),
                (Reference.from_type == "document") & (Reference.from_id == document.code),
            ),
        )
    ).all()
    items = [_ref_dict(db, ref) for ref in refs]
    return {"count": len(items), "items": items}


def document_references(
    db: Session, user: User, document_id: str, module: str,
    project_id: uuid.UUID | None = None,
) -> dict:
    document = get_document(db, user, document_id, module, project_id=project_id)
    return _reverse_references(db, document)
