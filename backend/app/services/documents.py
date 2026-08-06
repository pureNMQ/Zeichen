"""文档工作台的共享领域服务。

Wiki 是文档节点树；词典/API 的节点由目录树承载。HTTP 与 MCP 都只能经过这里，
以获得一致的模块隔离、层级、恢复原子性与权限语义。
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found
from ..models import Document, DocumentDirectory, DocumentVersion, Reference, User
from .pagination import decode_cursor, page_result
from .permissions import get_accessible_project, require_project_role
from .polymorphic import record_activity

DOC_TYPES = ("wiki", "glossary")
DIRECTORY_MODULES = ("glossary",)
API_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
FIELD_TYPES = {"string", "number", "integer", "boolean", "array", "object"}
_UNSET = object()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _document_dict(db: Session, document: Document, warning: dict | None = None) -> dict:
    result = {
        "id": str(document.id),
        "node_kind": "document",
        "title": document.title,
        "doc_type": document.doc_type,
        "content": document.content,
        "metadata": copy.deepcopy(document.doc_metadata or {}),
        "project_id": str(document.project_id),
        "parent_id": str(document.parent_id) if document.parent_id else None,
        "directory_id": str(document.directory_id) if document.directory_id else None,
        "created_by": str(document.created_by) if document.created_by else None,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
        "deleted_at": document.deleted_at.isoformat() if document.deleted_at else None,
        "has_children": _document_has_children(db, document),
    }
    if warning is not None:
        result["reference_warning"] = warning
    return result


def _library_symbol_dict(symbol: LibrarySymbol) -> dict:
    return {
        "id": str(symbol.id),
        "document_id": str(symbol.document_id),
        "owner_symbol_id": str(symbol.owner_symbol_id) if symbol.owner_symbol_id else None,
        "owner_symbol": {"symbol": symbol.owner.symbol, "kind": symbol.owner.kind} if symbol.owner else None,
        "language": symbol.language,
        "package": symbol.package,
        "namespace": symbol.namespace,
        "symbol": symbol.symbol,
        "kind": symbol.kind,
        "visibility": symbol.visibility,
        "canonical_signature": symbol.canonical_signature,
        "return_type": symbol.return_type,
        "return_description": symbol.return_description,
        "since_version": symbol.since_version,
        "deprecated": symbol.deprecated,
        "parameters": [
            {
                "name": parameter.name,
                "type": parameter.type_name,
                "required": parameter.required,
                "default_value": parameter.default_value,
                "description": parameter.description,
            }
            for parameter in symbol.parameters
        ],
        "exceptions": [
            {"type": exception.type_name, "description": exception.description}
            for exception in symbol.exceptions
        ],
    }


def _library_symbol_members(db: Session, symbol: LibrarySymbol) -> list[dict]:
    members = db.scalars(
        select(LibrarySymbol)
        .join(Document)
        .where(
            LibrarySymbol.owner_symbol_id == symbol.id,
            Document.deleted_at.is_(None),
        )
        .order_by(LibrarySymbol.kind, LibrarySymbol.symbol, LibrarySymbol.canonical_signature)
    ).all()
    return [{
        "document_id": str(member.document_id),
        "symbol": member.symbol,
        "kind": member.kind,
        "summary": next((line.strip() for line in (member.document.content or "").splitlines() if line.strip()), ""),
    } for member in members]


def _library_symbol_list_item(symbol: LibrarySymbol) -> dict:
    """A compact, selectable symbol record for the API-document editor."""
    return {
        "id": str(symbol.id),
        "document_id": str(symbol.document_id),
        "language": symbol.language,
        "symbol": symbol.symbol,
        "kind": symbol.kind,
        "package": symbol.package,
        "namespace": symbol.namespace,
        "canonical_signature": symbol.canonical_signature,
    }


def _code_tree_member_group(symbol: LibrarySymbol) -> tuple[str, str]:
    groups = {
        "constructor": ("constructors", "构造函数"),
        "field": ("fields", "字段"),
        "constant": ("fields", "字段"),
        "property": ("properties", "属性"),
        "method": ("methods", "方法"),
        "enum_value": ("enum_values", "枚举值"),
    }
    return groups.get(symbol.kind, ("members", "成员"))


def list_library_symbols(db: Session, user: User, project_id: uuid.UUID) -> dict:
    get_accessible_project(db, user.id, project_id)
    symbols = db.scalars(
        select(LibrarySymbol)
        .join(Document)
        .where(Document.project_id == project_id, Document.doc_type == "api", Document.deleted_at.is_(None))
        .order_by(LibrarySymbol.package, LibrarySymbol.namespace, LibrarySymbol.symbol, LibrarySymbol.canonical_signature)
    ).all()
    return {"items": [_library_symbol_list_item(symbol) for symbol in symbols]}


def list_api_code_tree(db: Session, user: User, project_id: uuid.UUID) -> dict:
    """Return API documents in their code ownership hierarchy, not directory order."""
    get_accessible_project(db, user.id, project_id)
    symbols = db.scalars(
        select(LibrarySymbol)
        .join(Document)
        .where(Document.project_id == project_id, Document.doc_type == "api", Document.deleted_at.is_(None))
        .order_by(LibrarySymbol.package, LibrarySymbol.namespace, LibrarySymbol.symbol, LibrarySymbol.canonical_signature)
    ).all()
    legacy_documents = db.scalars(
        select(Document)
        .outerjoin(LibrarySymbol)
        .where(
            Document.project_id == project_id,
            Document.doc_type == "api",
            Document.deleted_at.is_(None),
            LibrarySymbol.id.is_(None),
        )
        .order_by(Document.title)
    ).all()
    by_id = {symbol.id: symbol for symbol in symbols}
    children: dict[uuid.UUID, list[LibrarySymbol]] = {}
    roots: list[LibrarySymbol] = []
    for symbol in symbols:
        if symbol.owner_symbol_id in by_id:
            children.setdefault(symbol.owner_symbol_id, []).append(symbol)
        else:
            roots.append(symbol)

    def symbol_node(symbol: LibrarySymbol) -> dict:
        grouped: dict[tuple[str, str], list[dict]] = {}
        for child in children.get(symbol.id, []):
            grouped.setdefault(_code_tree_member_group(child), []).append(symbol_node(child))
        member_nodes = [
            {
                "node_kind": "member_group",
                "id": f"group:{symbol.id}:{key}",
                "title": label,
                "children": entries,
            }
            for (key, label), entries in grouped.items()
        ]
        return {
            "node_kind": "symbol",
            "id": str(symbol.id),
            "title": symbol.symbol,
            "symbol_kind": symbol.kind,
            "document": _document_dict(db, symbol.document),
            "children": member_nodes,
        }

    packages: dict[tuple[str, str], dict[str, list[LibrarySymbol]]] = {}
    for symbol in roots:
        packages.setdefault((symbol.language, symbol.package), {}).setdefault(symbol.namespace or "（全局命名空间）", []).append(symbol)
    items = []
    for (language, package), namespaces in packages.items():
        namespace_nodes: dict[str, dict] = {}
        for namespace, namespace_symbols in namespaces.items():
            if namespace == "（全局命名空间）":
                namespace_nodes[namespace] = {
                    "node_kind": "namespace", "id": f"namespace:{language}:{package}:{namespace}",
                    "title": namespace, "language": language, "package": package, "namespace": "",
                    "children": [symbol_node(symbol) for symbol in namespace_symbols],
                }
                continue
            parts = namespace.split(".")
            for index in range(1, len(parts) + 1):
                path = ".".join(parts[:index])
                namespace_nodes.setdefault(path, {
                    "node_kind": "namespace", "id": f"namespace:{language}:{package}:{path}",
                    "title": path, "language": language, "package": package, "namespace": path,
                    "children": [],
                })
            namespace_nodes[namespace]["children"].extend(symbol_node(symbol) for symbol in namespace_symbols)
        roots: list[dict] = []
        for namespace, node in namespace_nodes.items():
            parent_name = namespace.rsplit(".", 1)[0] if "." in namespace else None
            if parent_name and parent_name in namespace_nodes:
                namespace_nodes[parent_name]["children"].append(node)
            else:
                roots.append(node)
        items.append({
            "node_kind": "package",
            "id": f"package:{language}:{package}",
            "title": package,
            "language": language,
            "package": package,
            "children": roots,
        })
    if legacy_documents:
        items.append({
            "node_kind": "package",
            "id": "package:legacy",
            "title": "未结构化 API",
            "children": [{
                "node_kind": "namespace",
                "id": "namespace:legacy",
                "title": "待补充代码结构",
                "children": [{
                    "node_kind": "symbol",
                    "id": f"legacy:{document.id}",
                    "title": document.title,
                    "document": _document_dict(db, document),
                    "children": [],
                } for document in legacy_documents],
            }],
        })
    return {"items": items}


def _directory_dict(db: Session, directory: DocumentDirectory) -> dict:
    return {
        "id": str(directory.id),
        "node_kind": "directory",
        "name": directory.name,
        "title": directory.name,
        "module_type": directory.module_type,
        "project_id": str(directory.project_id),
        "parent_id": str(directory.parent_id) if directory.parent_id else None,
        "created_by": str(directory.created_by) if directory.created_by else None,
        "created_at": directory.created_at.isoformat(),
        "updated_at": directory.updated_at.isoformat(),
        "deleted_at": directory.deleted_at.isoformat() if directory.deleted_at else None,
        "has_children": _directory_has_children(db, directory),
    }


def _version_dict(version: DocumentVersion) -> dict:
    return {
        "id": str(version.id),
        "version_no": version.version_no,
        "title": version.title,
        "content": version.content,
        "metadata": copy.deepcopy(version.doc_metadata or {}),
        "created_by": str(version.created_by) if version.created_by else None,
        "created_at": version.created_at.isoformat(),
    }


def _document_has_children(db: Session, document: Document) -> bool:
    if document.doc_type != "wiki":
        return False
    return db.scalar(
        select(Document.id).where(
            Document.parent_id == document.id,
            Document.doc_type == "wiki",
            Document.deleted_at.is_(None),
        ).limit(1)
    ) is not None


def _directory_has_children(db: Session, directory: DocumentDirectory) -> bool:
    return (
        db.scalar(
            select(DocumentDirectory.id).where(
                DocumentDirectory.parent_id == directory.id,
                DocumentDirectory.deleted_at.is_(None),
            ).limit(1)
        ) is not None
        or db.scalar(
            select(Document.id).where(
                Document.directory_id == directory.id,
                Document.deleted_at.is_(None),
            ).limit(1)
        ) is not None
    )


def _require_module(module: str) -> None:
    if module not in DOC_TYPES:
        raise invalid_request("不支持的文档模块")


def _get_document_raw(db: Session, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise not_found("文档不存在")
    return document


def _get_directory_raw(db: Session, directory_id: uuid.UUID) -> DocumentDirectory:
    directory = db.get(DocumentDirectory, directory_id)
    if directory is None:
        raise not_found("目录不存在")
    return directory


def _visible_document(db: Session, user: User, document_id: uuid.UUID, include_deleted: bool = False) -> Document:
    document = _get_document_raw(db, document_id)
    if document.deleted_at is not None and not include_deleted:
        raise not_found("文档不存在")
    get_accessible_project(db, user.id, document.project_id, min_level="viewer")
    return document


def _editable_document(db: Session, user: User, document_id: uuid.UUID, include_deleted: bool = False) -> Document:
    document = _visible_document(db, user, document_id, include_deleted)
    require_project_role(db, user.id, document.project_id, min_level="editor")
    return document


def _editable_directory(db: Session, user: User, directory_id: uuid.UUID, include_deleted: bool = False) -> DocumentDirectory:
    directory = _get_directory_raw(db, directory_id)
    if directory.deleted_at is not None and not include_deleted:
        raise not_found("目录不存在")
    require_project_role(db, user.id, directory.project_id, min_level="editor")
    return directory


def get_document(db: Session, user: User, document_id: uuid.UUID, module: str | None = None) -> Document:
    document = _visible_document(db, user, document_id)
    if module is not None and document.doc_type != module:
        raise not_found("文档不存在")
    return document


def get_directory(db: Session, user: User, directory_id: uuid.UUID, module: str | None = None) -> DocumentDirectory:
    directory = _get_directory_raw(db, directory_id)
    if directory.deleted_at is not None:
        raise not_found("目录不存在")
    get_accessible_project(db, user.id, directory.project_id, min_level="viewer")
    if module is not None and directory.module_type != module:
        raise not_found("目录不存在")
    return directory


def _validate_location(
    db: Session,
    project_id: uuid.UUID,
    doc_type: str,
    parent_id: uuid.UUID | None,
    directory_id: uuid.UUID | None,
    document_id: uuid.UUID | None = None,
) -> None:
    if doc_type == "wiki":
        if directory_id is not None:
            raise invalid_request("Wiki 不能归属目录")
        if parent_id is None:
            return
        parent = _get_document_raw(db, parent_id)
        if parent.id == document_id:
            raise invalid_request("不能将 Wiki 移动到自身")
        if parent.deleted_at is not None or parent.project_id != project_id or parent.doc_type != "wiki":
            raise invalid_request("父 Wiki 必须属于同项目且未删除")
        if document_id is not None and parent.id in _wiki_subtree_ids(db, document_id):
            raise invalid_request("不能将 Wiki 移动到其后代")
        return

    if parent_id is not None:
        raise invalid_request("仅 Wiki 支持父文档")
    if directory_id is None:
        return
    directory = _get_directory_raw(db, directory_id)
    if (
        directory.deleted_at is not None
        or directory.project_id != project_id
        or directory.module_type != doc_type
    ):
        raise invalid_request("目录必须属于同项目、同模块且未删除")


def _assert_document_title_unique(
    db: Session,
    project_id: uuid.UUID,
    doc_type: str,
    title: str,
    parent_id: uuid.UUID | None,
    directory_id: uuid.UUID | None,
    exclude_ids: set[uuid.UUID] | None = None,
) -> None:
    exclude_ids = exclude_ids or set()
    stmt = select(Document).where(
        Document.project_id == project_id,
        Document.doc_type == doc_type,
        Document.deleted_at.is_(None),
        Document.title == title,
    )
    if doc_type == "wiki":
        stmt = stmt.where(Document.parent_id == parent_id)
    elif doc_type == "api":
        stmt = stmt.where(Document.directory_id == directory_id)
    existing = [row for row in db.scalars(stmt).all() if row.id not in exclude_ids]
    if existing:
        scope = "同级 Wiki" if doc_type == "wiki" else "同目录条目" if doc_type == "api" else "同项目词条"
        raise conflict(f"{scope}标题已存在")


def _validate_api_metadata(
    db: Session,
    project_id: uuid.UUID,
    metadata: dict,
    exclude_ids: set[uuid.UUID] | None = None,
) -> dict:
    if not isinstance(metadata, dict):
        raise invalid_request("API metadata 必须是对象")
    endpoint = metadata.get("endpoint")
    if not isinstance(endpoint, dict):
        raise invalid_request("API 定义须包含 endpoint.method 和 endpoint.path")
    method = endpoint.get("method")
    path = endpoint.get("path")
    if not isinstance(method, str) or method.upper() not in API_METHODS:
        raise invalid_request("API endpoint.method 无效")
    if not isinstance(path, str) or not path.startswith("/") or " " in path:
        raise invalid_request("API endpoint.path 必须以 / 开头且不含空格")
    schema = metadata.get("schema", {})
    fields = schema.get("fields", []) if isinstance(schema, dict) else None
    if not isinstance(fields, list):
        raise invalid_request("API schema.fields 必须是数组")
    names: set[str] = set()
    for field in fields:
        if not isinstance(field, dict) or not isinstance(field.get("name"), str) or not field["name"].strip():
            raise invalid_request("API 字段须包含非空 name")
        name = field["name"].strip()
        if name in names:
            raise invalid_request(f"API 字段重复: {name}")
        names.add(name)
        if field.get("type") not in FIELD_TYPES:
            raise invalid_request("API 字段 type 必须为 string/number/integer/boolean/array/object")
    exclude_ids = exclude_ids or set()
    candidates = db.scalars(
        select(Document).where(
            Document.project_id == project_id,
            Document.doc_type == "api",
            Document.deleted_at.is_(None),
        )
    ).all()
    for candidate in candidates:
        if candidate.id in exclude_ids:
            continue
        existing = (candidate.doc_metadata or {}).get("endpoint", {})
        if existing.get("method", "").upper() == method.upper() and existing.get("path") == path:
            raise conflict(f"API 端点已存在: {method.upper()} {path}")
    return {**copy.deepcopy(metadata), "endpoint": {**endpoint, "method": method.upper(), "path": path}}


def _clean_optional_string(value: object, field: str, max_length: int | None = None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid_request(f"程序库符号 {field} 必须是字符串")
    value = value.strip()
    if not value:
        return None
    if max_length is not None and len(value) > max_length:
        raise invalid_request(f"程序库符号 {field} 过长")
    return value


def _validate_library_symbol(
    db: Session,
    document: Document,
    payload: object,
    exclude_symbol_id: uuid.UUID | None = None,
) -> dict:
    if not isinstance(payload, dict):
        raise invalid_request("程序库符号必须是对象")
    required = {"language": 64, "package": 256, "symbol": 256, "canonical_signature": None}
    cleaned: dict[str, object] = {}
    for field, max_length in required.items():
        value = _clean_optional_string(payload.get(field), field, max_length)
        cleaned[field] = value or ""
    kind = _clean_optional_string(payload.get("kind"), "kind", 32) or "class"
    if kind not in LIBRARY_SYMBOL_KINDS:
        raise invalid_request("程序库符号 kind 无效")
    cleaned["kind"] = kind
    for field, max_length in (("namespace", 256), ("visibility", 32), ("return_type", 512), ("return_description", None), ("since_version", 64)):
        cleaned[field] = _clean_optional_string(payload.get(field), field, max_length)
    deprecated = payload.get("deprecated", False)
    if not isinstance(deprecated, bool):
        raise invalid_request("程序库符号 deprecated 必须是布尔值")
    cleaned["deprecated"] = deprecated

    owner_id = payload.get("owner_symbol_id")
    if owner_id is not None:
        try:
            owner_uuid = uuid.UUID(str(owner_id))
        except (TypeError, ValueError):
            raise invalid_request("程序库符号 owner_symbol_id 无效") from None
        owner = db.get(LibrarySymbol, owner_uuid)
        if owner is None or owner.document.project_id != document.project_id:
            raise invalid_request("所属符号必须属于同一项目")
        if owner.document.deleted_at is not None:
            raise invalid_request("所属符号的文档已删除")
        if owner.document_id == document.id:
            raise invalid_request("符号不能归属自身")
        existing_symbol_id = document.library_symbol.id if document.library_symbol is not None else None
        ancestor = owner
        seen_owners: set[uuid.UUID] = set()
        while ancestor.owner_symbol_id is not None:
            if ancestor.id in seen_owners or ancestor.id == existing_symbol_id:
                raise invalid_request("所属符号不能形成循环")
            seen_owners.add(ancestor.id)
            ancestor = db.get(LibrarySymbol, ancestor.owner_symbol_id)
            if ancestor is None:
                break
        if ancestor is not None and ancestor.id == existing_symbol_id:
            raise invalid_request("所属符号不能形成循环")
        cleaned["language"] = owner.language
        cleaned["package"] = owner.package
        cleaned["namespace"] = owner.namespace
        if kind == "constructor":
            cleaned["symbol"] = owner.symbol
            cleaned["return_type"] = None
            cleaned["return_description"] = None
        if kind == "enum_value" and owner.kind != "enum":
            raise invalid_request("枚举值只能归属于枚举")
        if kind in TYPE_MEMBER_KINDS and owner.kind not in TYPE_SYMBOL_KINDS:
            raise invalid_request("构造函数、字段、属性和方法只能归属于类、结构体或接口")
        if kind not in TYPE_MEMBER_KINDS | {"enum_value"}:
            raise invalid_request("只有成员或枚举值可以设置所属符号")
        cleaned["owner_symbol_id"] = owner_uuid
    else:
        cleaned["owner_symbol_id"] = None

    parameters = payload.get("parameters", [])
    if not isinstance(parameters, list):
        raise invalid_request("程序库符号 parameters 必须是数组")
    names: set[str] = set()
    cleaned_parameters: list[dict] = []
    for parameter in parameters:
        if not isinstance(parameter, dict):
            raise invalid_request("程序库参数必须是对象")
        name = _clean_optional_string(parameter.get("name"), "参数 name", 128)
        type_name = _clean_optional_string(parameter.get("type"), "参数 type", 512)
        if name is None and type_name is None:
            continue
        if name and name in names:
            raise invalid_request(f"程序库参数重复: {name}")
        if name:
            names.add(name)
        parameter_required = parameter.get("required", False)
        if not isinstance(parameter_required, bool):
            raise invalid_request("程序库参数 required 必须是布尔值")
        cleaned_parameters.append({
            "name": name or "", "type": type_name or "", "required": parameter_required,
            "default_value": _clean_optional_string(parameter.get("default_value"), "参数 default_value"),
            "description": _clean_optional_string(parameter.get("description"), "参数 description"),
        })
    cleaned["parameters"] = cleaned_parameters

    exceptions = payload.get("exceptions", [])
    if not isinstance(exceptions, list):
        raise invalid_request("程序库符号 exceptions 必须是数组")
    cleaned_exceptions: list[dict] = []
    for exception in exceptions:
        if not isinstance(exception, dict):
            raise invalid_request("程序库异常必须是对象")
        type_name = _clean_optional_string(exception.get("type"), "异常 type", 512)
        if type_name is None:
            continue
        cleaned_exceptions.append({
            "type": type_name,
            "description": _clean_optional_string(exception.get("description"), "异常 description"),
        })
    cleaned["exceptions"] = cleaned_exceptions

    candidates = db.scalars(
        select(LibrarySymbol).join(Document).where(
            Document.project_id == document.project_id,
            LibrarySymbol.language == cleaned["language"],
            LibrarySymbol.package == cleaned["package"],
            LibrarySymbol.namespace == cleaned["namespace"],
            LibrarySymbol.owner_symbol_id == cleaned["owner_symbol_id"],
            LibrarySymbol.symbol == cleaned["symbol"],
            LibrarySymbol.canonical_signature == cleaned["canonical_signature"],
        )
    ).all()
    if any(candidate.id != exclude_symbol_id for candidate in candidates):
        raise conflict("程序库符号的规范签名已存在")
    return cleaned


def _save_library_symbol(db: Session, document: Document, payload: object) -> LibrarySymbol:
    existing = document.library_symbol
    values = _validate_library_symbol(db, document, payload, existing.id if existing else None)
    if existing is None:
        existing = LibrarySymbol(document_id=document.id)
        db.add(existing)
        document.library_symbol = existing
    for field in (
        "owner_symbol_id", "language", "package", "namespace", "symbol", "kind", "visibility",
        "canonical_signature", "return_type", "return_description", "since_version", "deprecated",
    ):
        setattr(existing, field, values[field])
    existing.parameters.clear()
    existing.exceptions.clear()
    # 先提交 orphan 删除，避免数据库在同一 position 上先插入新行而触发唯一约束。
    db.flush()
    for position, parameter in enumerate(values["parameters"]):
        existing.parameters.append(LibrarySymbolParameter(
            position=position, name=parameter["name"], type_name=parameter["type"],
            required=parameter["required"], default_value=parameter["default_value"], description=parameter["description"],
        ))
    for position, exception in enumerate(values["exceptions"]):
        existing.exceptions.append(LibrarySymbolException(
            position=position, type_name=exception["type"], description=exception["description"],
        ))
    db.flush()
    return existing


def _create_version(db: Session, document: Document, actor_id: uuid.UUID) -> DocumentVersion:
    next_no = (
        db.scalar(
            select(DocumentVersion.version_no)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_no.desc())
            .limit(1)
        )
        or 0
    ) + 1
    version = DocumentVersion(
        document_id=document.id,
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
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version_no.desc())
        .offset(20)
    ).all()
    if old_ids:
        db.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(old_ids)))
    return version


def create_document(
    db: Session,
    actor: User,
    project_id: uuid.UUID,
    title: str,
    doc_type: str,
    content: str | None,
    metadata: dict | None,
    parent_id: uuid.UUID | None = None,
    directory_id: uuid.UUID | None = None,
) -> Document:
    _require_module(doc_type)
    require_project_role(db, actor.id, project_id, min_level="editor")
    title = title.strip()
    if not title:
        raise invalid_request("标题不能为空")
    _validate_location(db, project_id, doc_type, parent_id, directory_id)
    _assert_document_title_unique(db, project_id, doc_type, title, parent_id, directory_id)
    doc_metadata = copy.deepcopy(metadata or {})
    document = Document(
        project_id=project_id,
        title=title,
        doc_type=doc_type,
        content=content or "",
        doc_metadata=doc_metadata,
        parent_id=parent_id,
        directory_id=directory_id,
        created_by=actor.id,
    )
    db.add(document)
    db.flush()
    _create_version(db, document, actor.id)
    record_activity(db, project_id, actor.id, "document", document.id, "create", f"创建 {doc_type} 文档")
    db.commit()
    return document


def update_document(
    db: Session,
    actor: User,
    document_id: uuid.UUID,
    title: str | None = None,
    content: str | None = None,
    metadata: object = _UNSET,
) -> tuple[Document, dict | None]:
    document = _editable_document(db, actor, document_id)
    if title is not None:
        title = title.strip()
        if not title:
            raise invalid_request("标题不能为空")
        _assert_document_title_unique(
            db, document.project_id, document.doc_type, title, document.parent_id, document.directory_id, {document.id}
        )
        document.title = title
    if content is not None:
        document.content = content
    warning = None
    if metadata is not _UNSET:
        if not isinstance(metadata, dict):
            raise invalid_request("metadata 必须是对象")
        document.doc_metadata = copy.deepcopy(metadata)
    _create_version(db, document, actor.id)
    record_activity(db, document.project_id, actor.id, "document", document.id, "save", "保存文档版本")
    db.commit()
    return document, warning


def move_document(
    db: Session,
    actor: User,
    document_id: uuid.UUID,
    parent_id: uuid.UUID | None = None,
    directory_id: uuid.UUID | None = None,
) -> Document:
    document = _editable_document(db, actor, document_id)
    _validate_location(db, document.project_id, document.doc_type, parent_id, directory_id, document.id)
    _assert_document_title_unique(
        db, document.project_id, document.doc_type, document.title, parent_id, directory_id, {document.id}
    )
    document.parent_id = parent_id
    document.directory_id = directory_id
    record_activity(db, document.project_id, actor.id, "document", document.id, "move", "调整文档归属")
    db.commit()
    return document


def create_directory(
    db: Session,
    actor: User,
    project_id: uuid.UUID,
    module: str,
    name: str,
    parent_id: uuid.UUID | None = None,
) -> DocumentDirectory:
    if module not in DIRECTORY_MODULES:
        raise invalid_request("仅词典和 API 支持目录")
    require_project_role(db, actor.id, project_id, min_level="editor")
    name = name.strip()
    if not name:
        raise invalid_request("目录名称不能为空")
    _validate_directory_parent(db, project_id, module, parent_id)
    _assert_directory_name_unique(db, project_id, module, name, parent_id)
    directory = DocumentDirectory(
        project_id=project_id, module_type=module, name=name, parent_id=parent_id, created_by=actor.id
    )
    db.add(directory)
    db.flush()
    record_activity(db, project_id, actor.id, "project", project_id, "directory_create", f"创建 {module} 目录")
    db.commit()
    return directory


def _validate_directory_parent(
    db: Session,
    project_id: uuid.UUID,
    module: str,
    parent_id: uuid.UUID | None,
    directory_id: uuid.UUID | None = None,
) -> None:
    if parent_id is None:
        return
    parent = _get_directory_raw(db, parent_id)
    if parent.id == directory_id:
        raise invalid_request("不能将目录移动到自身")
    if parent.deleted_at is not None or parent.project_id != project_id or parent.module_type != module:
        raise invalid_request("父目录必须属于同项目、同模块且未删除")
    if directory_id is not None and parent.id in _directory_subtree_ids(db, directory_id):
        raise invalid_request("不能将目录移动到其后代")


def _assert_directory_name_unique(
    db: Session,
    project_id: uuid.UUID,
    module: str,
    name: str,
    parent_id: uuid.UUID | None,
    exclude_ids: set[uuid.UUID] | None = None,
) -> None:
    exclude_ids = exclude_ids or set()
    rows = db.scalars(
        select(DocumentDirectory).where(
            DocumentDirectory.project_id == project_id,
            DocumentDirectory.module_type == module,
            DocumentDirectory.parent_id == parent_id,
            DocumentDirectory.name == name,
            DocumentDirectory.deleted_at.is_(None),
        )
    ).all()
    if any(row.id not in exclude_ids for row in rows):
        raise conflict("同级目录名称已存在")


def rename_directory(db: Session, actor: User, directory_id: uuid.UUID, name: str) -> DocumentDirectory:
    directory = _editable_directory(db, actor, directory_id)
    name = name.strip()
    if not name:
        raise invalid_request("目录名称不能为空")
    _assert_directory_name_unique(
        db, directory.project_id, directory.module_type, name, directory.parent_id, {directory.id}
    )
    directory.name = name
    record_activity(db, directory.project_id, actor.id, "project", directory.project_id, "directory_rename", "重命名目录")
    db.commit()
    return directory


def move_directory(db: Session, actor: User, directory_id: uuid.UUID, parent_id: uuid.UUID | None) -> DocumentDirectory:
    directory = _editable_directory(db, actor, directory_id)
    _validate_directory_parent(db, directory.project_id, directory.module_type, parent_id, directory.id)
    _assert_directory_name_unique(
        db, directory.project_id, directory.module_type, directory.name, parent_id, {directory.id}
    )
    directory.parent_id = parent_id
    record_activity(db, directory.project_id, actor.id, "project", directory.project_id, "directory_move", "调整目录归属")
    db.commit()
    return directory


def _wiki_subtree_ids(db: Session, root_id: uuid.UUID) -> set[uuid.UUID]:
    found: set[uuid.UUID] = set()
    pending = [root_id]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(
            db.scalars(select(Document.id).where(Document.parent_id == current, Document.doc_type == "wiki")).all()
        )
    return found


def _directory_subtree_ids(db: Session, root_id: uuid.UUID) -> set[uuid.UUID]:
    found: set[uuid.UUID] = set()
    pending = [root_id]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(db.scalars(select(DocumentDirectory.id).where(DocumentDirectory.parent_id == current)).all())
    return found


def _directory_subtree_documents(db: Session, directory_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not directory_ids:
        return set()
    return set(db.scalars(select(Document.id).where(Document.directory_id.in_(directory_ids))).all())


def delete_impact_document(db: Session, user: User, document_id: uuid.UUID) -> dict:
    document = _visible_document(db, user, document_id)
    ids = _wiki_subtree_ids(db, document.id) if document.doc_type == "wiki" else {document.id}
    return {"documents": len(ids), "directories": 0}


def delete_impact_directory(db: Session, user: User, directory_id: uuid.UUID) -> dict:
    directory = get_directory(db, user, directory_id)
    directory_ids = _directory_subtree_ids(db, directory.id)
    return {"documents": len(_directory_subtree_documents(db, directory_ids)), "directories": len(directory_ids)}


def delete_document(db: Session, actor: User, document_id: uuid.UUID) -> None:
    document = _editable_document(db, actor, document_id)
    ids = _wiki_subtree_ids(db, document.id) if document.doc_type == "wiki" else {document.id}
    rows = db.scalars(select(Document).where(Document.id.in_(ids), Document.deleted_at.is_(None))).all()
    timestamp = _now()
    for row in rows:
        row.deleted_at = timestamp
    record_activity(db, document.project_id, actor.id, "document", document.id, "delete", f"递归删除 {len(rows)} 篇文档")
    db.commit()


def delete_directory(db: Session, actor: User, directory_id: uuid.UUID) -> None:
    directory = _editable_directory(db, actor, directory_id)
    directory_ids = _directory_subtree_ids(db, directory.id)
    document_ids = _directory_subtree_documents(db, directory_ids)
    timestamp = _now()
    for row in db.scalars(select(Document).where(Document.id.in_(document_ids), Document.deleted_at.is_(None))).all():
        row.deleted_at = timestamp
    for row in db.scalars(select(DocumentDirectory).where(DocumentDirectory.id.in_(directory_ids), DocumentDirectory.deleted_at.is_(None))).all():
        row.deleted_at = timestamp
    record_activity(db, directory.project_id, actor.id, "project", directory.project_id, "directory_delete", "递归删除目录")
    db.commit()


def _validate_restore_documents(db: Session, documents: list[Document], directory_ids: set[uuid.UUID] | None = None) -> None:
    ids = {document.id for document in documents}
    directory_ids = directory_ids or set()
    for document in documents:
        if document.doc_type == "wiki" and document.parent_id and document.parent_id not in ids:
            parent = _get_document_raw(db, document.parent_id)
            if parent.deleted_at is not None:
                raise conflict("恢复失败：父 Wiki 已删除")
        if document.doc_type in DIRECTORY_MODULES and document.directory_id and document.directory_id not in directory_ids:
            directory = _get_directory_raw(db, document.directory_id)
            if directory.deleted_at is not None:
                raise conflict("恢复失败：所属目录已删除")
        _assert_document_title_unique(
            db,
            document.project_id,
            document.doc_type,
            document.title,
            document.parent_id,
            document.directory_id,
            ids,
        )


def _validate_restore_directories(db: Session, directories: list[DocumentDirectory]) -> None:
    ids = {directory.id for directory in directories}
    for directory in directories:
        if directory.parent_id and directory.parent_id not in ids:
            parent = _get_directory_raw(db, directory.parent_id)
            if parent.deleted_at is not None:
                raise conflict("恢复失败：父目录已删除")
        _assert_directory_name_unique(
            db,
            directory.project_id,
            directory.module_type,
            directory.name,
            directory.parent_id,
            ids,
        )


def restore_document(db: Session, actor: User, document_id: uuid.UUID) -> Document:
    document = _editable_document(db, actor, document_id, include_deleted=True)
    if document.deleted_at is None:
        raise not_found("已删除的文档不存在")
    ids = _wiki_subtree_ids(db, document.id) if document.doc_type == "wiki" else {document.id}
    rows = db.scalars(select(Document).where(Document.id.in_(ids))).all()
    _validate_restore_documents(db, rows)
    for row in rows:
        row.deleted_at = None
    record_activity(db, document.project_id, actor.id, "document", document.id, "restore", f"递归恢复 {len(rows)} 篇文档")
    db.commit()
    return document


def restore_directory(db: Session, actor: User, directory_id: uuid.UUID) -> DocumentDirectory:
    directory = _editable_directory(db, actor, directory_id, include_deleted=True)
    if directory.deleted_at is None:
        raise not_found("已删除的目录不存在")
    directory_ids = _directory_subtree_ids(db, directory.id)
    directories = db.scalars(select(DocumentDirectory).where(DocumentDirectory.id.in_(directory_ids))).all()
    documents = db.scalars(select(Document).where(Document.directory_id.in_(directory_ids))).all()
    _validate_restore_directories(db, directories)
    _validate_restore_documents(db, documents, directory_ids)
    for row in directories:
        row.deleted_at = None
    for row in documents:
        row.deleted_at = None
    record_activity(db, directory.project_id, actor.id, "project", directory.project_id, "directory_restore", "递归恢复目录")
    db.commit()
    return directory


def list_module_children(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    module: str,
    parent_id: uuid.UUID | None,
    cursor: str | None,
    limit: int,
) -> dict:
    _require_module(module)
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    filters = {"project_id": str(project_id), "module": module, "parent_id": str(parent_id) if parent_id else None}
    offset = decode_cursor(filters, cursor)
    if module == "wiki":
        rows = db.scalars(
            select(Document).where(
                Document.project_id == project_id,
                Document.doc_type == "wiki",
                Document.parent_id == parent_id,
                Document.deleted_at.is_(None),
            )
        ).all()
        nodes = [_document_dict(db, row) for row in sorted(rows, key=lambda row: row.title.casefold())]
    else:
        directories = db.scalars(
            select(DocumentDirectory).where(
                DocumentDirectory.project_id == project_id,
                DocumentDirectory.module_type == module,
                DocumentDirectory.parent_id == parent_id,
                DocumentDirectory.deleted_at.is_(None),
            )
        ).all()
        documents = db.scalars(
            select(Document).where(
                Document.project_id == project_id,
                Document.doc_type == module,
                Document.directory_id == parent_id,
                Document.deleted_at.is_(None),
            )
        ).all()
        nodes = [_directory_dict(db, row) for row in sorted(directories, key=lambda row: row.name.casefold())]
        nodes += [_document_dict(db, row) for row in sorted(documents, key=lambda row: row.title.casefold())]
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
            Document.doc_type == module,
            Document.deleted_at.is_not(None),
        )
    ).all()
    nodes: list[dict] = [_document_dict(db, row) for row in documents]
    if module in DIRECTORY_MODULES:
        directories = db.scalars(
            select(DocumentDirectory).where(
                DocumentDirectory.project_id == project_id,
                DocumentDirectory.module_type == module,
                DocumentDirectory.deleted_at.is_not(None),
            )
        ).all()
        nodes += [_directory_dict(db, row) for row in directories]
    nodes.sort(key=lambda item: (item["node_kind"] != "directory", item["title"].casefold()))
    page = nodes[offset:offset + limit]
    return page_result(page, offset, limit, filters)


def ancestor_path(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    module: str,
    node_kind: str,
    node_id: uuid.UUID,
) -> dict:
    _require_module(module)
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    if node_kind == "document":
        node = _visible_document(db, user, node_id)
        if node.project_id != project_id or node.doc_type != module:
            raise not_found("文档不存在")
        if module == "wiki":
            chain: list[Document] = []
            current: Document | None = node
            while current is not None:
                chain.append(current)
                current = _get_document_raw(db, current.parent_id) if current.parent_id else None
            return {"items": [_document_dict(db, item) for item in reversed(chain)]}
        if node.directory_id is None:
            return {"items": [_document_dict(db, node)]}
        directory = get_directory(db, user, node.directory_id, module)
        chain_dirs = _directory_ancestors(db, directory)
        return {"items": [_directory_dict(db, item) for item in chain_dirs] + [_document_dict(db, node)]}
    if node_kind == "directory" and module in DIRECTORY_MODULES:
        directory = get_directory(db, user, node_id, module)
        if directory.project_id != project_id:
            raise not_found("目录不存在")
        return {"items": [_directory_dict(db, item) for item in _directory_ancestors(db, directory)]}
    raise invalid_request("节点类型无效")


def _directory_ancestors(db: Session, node: DocumentDirectory) -> list[DocumentDirectory]:
    chain: list[DocumentDirectory] = []
    current: DocumentDirectory | None = node
    while current is not None:
        chain.append(current)
        current = _get_directory_raw(db, current.parent_id) if current.parent_id else None
    return list(reversed(chain))


def list_versions(db: Session, user: User, document_id: uuid.UUID, module: str | None = None) -> list[dict]:
    document = get_document(db, user, document_id, module)
    versions = db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
        .order_by(DocumentVersion.version_no.desc())
    ).all()
    return [_version_dict(version) for version in versions]


def rollback_document(db: Session, actor: User, document_id: uuid.UUID, version_no: int, module: str | None = None) -> Document:
    document = _editable_document(db, actor, document_id)
    if module is not None and document.doc_type != module:
        raise not_found("文档不存在")
    version = db.scalar(
        select(DocumentVersion).where(DocumentVersion.document_id == document.id, DocumentVersion.version_no == version_no)
    )
    if version is None:
        raise not_found("文档版本不存在")
    _assert_document_title_unique(
        db, document.project_id, document.doc_type, version.title, document.parent_id, document.directory_id, {document.id}
    )
    document.title = version.title
    document.content = version.content
    document.doc_metadata = copy.deepcopy(version.doc_metadata or {})
    created = _create_version(db, document, actor.id)
    record_activity(db, document.project_id, actor.id, "document", document.id, "rollback", f"回滚至版本 {version_no}（生成版本 {created.version_no}）")
    db.commit()
    return document


def get_glossary_term(db: Session, user: User, project_id: uuid.UUID, title: str) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.project_id == project_id,
            Document.doc_type == "glossary",
            Document.title == title,
            Document.deleted_at.is_(None),
        )
    )
    if document is None:
        raise not_found("词条不存在")
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    return document


def _reverse_references(db: Session, document: Document) -> dict:
    refs = db.scalars(
        select(Reference).where(
            Reference.deleted_at.is_(None),
            or_(
                (Reference.to_type == "document") & (Reference.to_id == document.id),
                (Reference.from_type == "document") & (Reference.from_id == document.id),
            ),
        )
    ).all()
    items = [
        {
            "id": str(ref.id),
            "from_type": ref.from_type,
            "from_id": str(ref.from_id),
            "to_type": ref.to_type,
            "to_id": str(ref.to_id),
            "type": ref.type,
        }
        for ref in refs
    ]
    return {"count": len(items), "items": items}


def document_references(db: Session, user: User, document_id: uuid.UUID, module: str) -> dict:
    document = get_document(db, user, document_id, module)
    return _reverse_references(db, document)
