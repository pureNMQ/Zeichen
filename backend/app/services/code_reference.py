"""Domain service for the code API reference.

The service accepts only kind-specific declaration payloads.  It deliberately
does not share the generic document service or document metadata.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found
from ..models import CodeLibrary, CodeSymbol, CodeSymbolVersion, EnumMember, User
from ..models.code_reference import CODE_SYMBOL_KINDS
from .permissions import get_accessible_project, require_project_role
from .polymorphic import record_activity

TYPE_KINDS = {"class", "struct", "interface", "enum"}
ROOT_KINDS = TYPE_KINDS | {"function"}
CALLABLE_KINDS = {"function", "constructor", "method"}
VALUE_KINDS = {"field", "property", "constant"}
MEMBER_KINDS = {"constructor", "method", "field", "property", "constant"}
ACCESSIBILITIES = {"public", "protected", "internal", "private"}
PASSING_KINDS = {"value", "ref", "out", "in"}
PROPERTY_ACCESSORS = {"get", "set", "init"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: object, field: str, max_length: int | None = None, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise invalid_request(f"{field} 不能为空")
        return None
    if not isinstance(value, str):
        raise invalid_request(f"{field} 必须是字符串")
    value = value.strip()
    if not value:
        if required:
            raise invalid_request(f"{field} 不能为空")
        return None
    if max_length is not None and len(value) > max_length:
        raise invalid_request(f"{field} 过长")
    return value


def _string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise invalid_request(f"{field} 必须是非空字符串数组")
    return [item.strip() for item in value]


def _type_parameters(value: object) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise invalid_request("type_parameters 必须是数组")
    result = []
    names: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise invalid_request("泛型参数必须是对象")
        name = _clean(item.get("name"), "泛型参数 name", 128, required=True)
        if name in names:
            raise invalid_request(f"泛型参数重复: {name}")
        names.add(name)
        result.append({"name": name, "constraints": _string_list(item.get("constraints"), "泛型参数 constraints")})
    return result


def _parameters(value: object) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise invalid_request("parameters 必须是数组")
    result = []
    names: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise invalid_request("参数必须是对象")
        name = _clean(item.get("name"), "参数 name", 128, required=True)
        type_name = _clean(item.get("type"), "参数 type", 512, required=True)
        if name in names:
            raise invalid_request(f"参数重复: {name}")
        names.add(name)
        passing = item.get("passing", "value")
        if passing not in PASSING_KINDS:
            raise invalid_request("参数 passing 必须是 value/ref/out/in")
        result.append({
            "name": name, "type": type_name, "passing": passing,
            "default_value": _clean(item.get("default_value"), "参数 default_value"),
            "summary": _clean(item.get("summary"), "参数 summary", 512),
        })
    return result


def _exceptions(value: object) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise invalid_request("exceptions 必须是数组")
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise invalid_request("异常必须是对象")
        result.append({
            "type": _clean(item.get("type"), "异常 type", 512, required=True),
            "condition": _clean(item.get("condition"), "异常 condition", 512, required=True),
        })
    return result


def _enum_members(value: object) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise invalid_request("枚举 members 必须是数组")
    result = []
    names: set[str] = set()
    for position, item in enumerate(value):
        if not isinstance(item, dict):
            raise invalid_request("枚举项必须是对象")
        name = _clean(item.get("name"), "枚举项 name", 256, required=True)
        if name in names:
            raise invalid_request(f"枚举项重复: {name}")
        names.add(name)
        supplied_position = item.get("position", position)
        if supplied_position != position:
            raise invalid_request("枚举项 position 必须从 0 起连续排列")
        result.append({
            "position": position,
            "name": name,
            "assigned_value": _clean(item.get("assigned_value"), "枚举项 assigned_value", 256),
            "summary": _clean(item.get("summary"), "枚举项 summary", 512),
        })
    return result


def _validate_definition(kind: str, payload: object) -> tuple[dict, list[dict]]:
    if not isinstance(payload, dict):
        raise invalid_request("definition 必须是对象")
    if kind in {"class", "struct", "interface"}:
        definition = {
            "type_parameters": _type_parameters(payload.get("type_parameters")),
            "base_type": _clean(payload.get("base_type"), "base_type", 512),
            "interfaces": _string_list(payload.get("interfaces"), "interfaces"),
            "modifiers": _string_list(payload.get("modifiers"), "modifiers"),
        }
        if kind == "interface" and definition["base_type"] is not None:
            raise invalid_request("接口不能设置 base_type")
        return definition, []
    if kind == "enum":
        flags = payload.get("is_flags", False)
        if not isinstance(flags, bool):
            raise invalid_request("is_flags 必须是布尔值")
        return {
            "underlying_type": _clean(payload.get("underlying_type"), "underlying_type", 128),
            "is_flags": flags,
        }, _enum_members(payload.get("members"))
    if kind in CALLABLE_KINDS:
        definition = {
            "parameters": _parameters(payload.get("parameters")),
            "exceptions": _exceptions(payload.get("exceptions")),
            "type_parameters": _type_parameters(payload.get("type_parameters")),
            "modifiers": _string_list(payload.get("modifiers"), "modifiers"),
        }
        if kind == "constructor":
            definition["initializer"] = _clean(payload.get("initializer"), "initializer", 512)
        else:
            returns = payload.get("returns")
            if not isinstance(returns, dict):
                raise invalid_request("函数和方法必须定义 returns")
            definition["returns"] = {
                "type": _clean(returns.get("type"), "returns.type", 512, required=True),
                "summary": _clean(returns.get("summary"), "returns.summary", 512),
            }
        return definition, []
    if kind == "field":
        return {
            "value_type": _clean(payload.get("value_type"), "value_type", 512, required=True),
            "default_value": _clean(payload.get("default_value"), "default_value"),
            "modifiers": _string_list(payload.get("modifiers"), "modifiers"),
        }, []
    if kind == "property":
        accessors = _string_list(payload.get("accessors"), "accessors")
        if not accessors or any(accessor not in PROPERTY_ACCESSORS for accessor in accessors):
            raise invalid_request("属性必须至少定义一个 get/set/init 访问器")
        return {
            "value_type": _clean(payload.get("value_type"), "value_type", 512, required=True),
            "accessors": accessors,
            "modifiers": _string_list(payload.get("modifiers"), "modifiers"),
        }, []
    if kind == "constant":
        return {
            "value_type": _clean(payload.get("value_type"), "value_type", 512, required=True),
            "value": _clean(payload.get("value"), "value", required=True),
        }, []
    raise invalid_request("不支持的代码符号类型")


def _signature(symbol: CodeSymbol, definition: dict | None = None) -> str:
    definition = definition if definition is not None else symbol.definition
    generic = ""
    if symbol.kind in TYPE_KINDS | {"function", "method"}:
        params = definition.get("type_parameters", [])
        generic = f"<{', '.join(item['name'] for item in params)}>" if params else ""
    if symbol.kind in {"class", "struct", "interface", "enum"}:
        return f"{symbol.kind} {symbol.name}{generic}"
    if symbol.kind in {"function", "method", "constructor"}:
        parameters = ", ".join(f"{item.get('passing', 'value')} {item['type']} {item['name']}".replace("value ", "") for item in definition["parameters"])
        call = f"{symbol.name}{generic}({parameters})"
        return call if symbol.kind == "constructor" else f"{definition['returns']['type']} {call}"
    if symbol.kind == "property":
        return f"{definition['value_type']} {symbol.name} {{ {'; '.join(definition['accessors'])}; }}"
    if symbol.kind == "constant":
        return f"const {definition['value_type']} {symbol.name} = {definition['value']}"
    return f"{definition['value_type']} {symbol.name}"


def _library_dict(library: CodeLibrary) -> dict:
    return {
        "id": str(library.id), "project_id": str(library.project_id), "name": library.name,
        "language": library.language, "package": library.package, "version": library.version,
        "created_at": library.created_at.isoformat(), "updated_at": library.updated_at.isoformat(),
        "deleted_at": library.deleted_at.isoformat() if library.deleted_at else None,
    }


def _enum_dict(symbol: CodeSymbol) -> list[dict]:
    return [{"position": item.position, "name": item.name, "assigned_value": item.assigned_value, "summary": item.summary} for item in symbol.enum_members]


def _symbol_dict(symbol: CodeSymbol, *, include_remarks: bool = True, include_members: bool = False) -> dict:
    definition = copy.deepcopy(symbol.definition)
    if symbol.kind == "enum":
        definition["members"] = _enum_dict(symbol)
    result = {
        "id": str(symbol.id), "library_id": str(symbol.library_id), "owner_symbol_id": str(symbol.owner_symbol_id) if symbol.owner_symbol_id else None,
        "kind": symbol.kind, "name": symbol.name, "qualified_name": _qualified_name(symbol),
        "namespace": symbol.namespace, "summary": symbol.summary, "accessibility": symbol.accessibility,
        "source_declaration": symbol.source_declaration, "since_version": symbol.since_version,
        "deprecated": symbol.deprecated, "definition": definition, "signature": _signature(symbol),
        "revision": symbol.revision, "created_at": symbol.created_at.isoformat(), "updated_at": symbol.updated_at.isoformat(),
        "deleted_at": symbol.deleted_at.isoformat() if symbol.deleted_at else None,
    }
    if include_remarks:
        result["remarks"] = symbol.remarks
    if include_members and symbol.kind in TYPE_KINDS - {"enum"}:
        result["members"] = [_symbol_preview(child) for child in symbol.children if child.deleted_at is None]
    return result


def _symbol_preview(symbol: CodeSymbol) -> dict:
    return {
        "id": str(symbol.id), "kind": symbol.kind, "name": symbol.name, "qualified_name": _qualified_name(symbol),
        "summary": symbol.summary, "signature": _signature(symbol), "deprecated": symbol.deprecated,
    }


def _qualified_name(symbol: CodeSymbol) -> str:
    if symbol.owner is not None:
        return f"{_qualified_name(symbol.owner)}.{symbol.name}"
    return ".".join(part for part in (symbol.library.package, symbol.namespace, symbol.name) if part)


def _visible_library(db: Session, user: User, library_id: uuid.UUID, *, editable: bool = False) -> CodeLibrary:
    library = db.get(CodeLibrary, library_id)
    if library is None or library.deleted_at is not None:
        raise not_found("程序库不存在")
    if editable:
        require_project_role(db, user.id, library.project_id, min_level="editor")
    else:
        get_accessible_project(db, user.id, library.project_id, min_level="viewer")
    return library


def _visible_symbol(db: Session, user: User, symbol_id: uuid.UUID, *, editable: bool = False, include_deleted: bool = False) -> CodeSymbol:
    symbol = db.get(CodeSymbol, symbol_id)
    if symbol is None or (symbol.deleted_at is not None and not include_deleted):
        raise not_found("代码符号不存在")
    _visible_library(db, user, symbol.library_id, editable=editable)
    return symbol


def create_library(db: Session, actor: User, project_id: uuid.UUID, name: str, language: str, package: str, version: str | None = None) -> CodeLibrary:
    require_project_role(db, actor.id, project_id, min_level="editor")
    name = _clean(name, "程序库名称", 128, required=True)
    language = _clean(language, "语言", 32, required=True)
    package = _clean(package, "包或模块", 256, required=True)
    existing = db.scalar(select(CodeLibrary).where(CodeLibrary.project_id == project_id, CodeLibrary.package == package, CodeLibrary.deleted_at.is_(None)))
    if existing is not None:
        raise conflict("同一项目中程序库包或模块已存在")
    library = CodeLibrary(project_id=project_id, name=name, language=language, package=package, version=_clean(version, "版本", 64), created_by=actor.id)
    db.add(library)
    db.flush()
    record_activity(db, project_id, actor.id, "project", project_id, "code_library_create", f"创建程序库 {name}")
    db.commit()
    return library


def list_libraries(db: Session, user: User, project_id: uuid.UUID) -> list[dict]:
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    libraries = db.scalars(select(CodeLibrary).where(CodeLibrary.project_id == project_id, CodeLibrary.deleted_at.is_(None)).order_by(CodeLibrary.name)).all()
    return [_library_dict(library) for library in libraries]


def _validate_scope(db: Session, library: CodeLibrary, kind: str, owner_id: uuid.UUID | None, namespace: str | None) -> tuple[CodeSymbol | None, str | None]:
    if kind not in CODE_SYMBOL_KINDS:
        raise invalid_request("不支持的代码符号类型")
    namespace = _clean(namespace, "命名空间", 256)
    if owner_id is None:
        if kind not in ROOT_KINDS:
            raise invalid_request("成员符号必须指定 owner_symbol_id")
        if namespace is None:
            raise invalid_request("顶级符号必须指定命名空间")
        return None, namespace
    owner = db.get(CodeSymbol, owner_id)
    if owner is None or owner.deleted_at is not None or owner.library_id != library.id:
        raise invalid_request("所属类型必须属于同一未删除程序库")
    if kind not in MEMBER_KINDS:
        raise invalid_request("只有成员符号可以指定 owner_symbol_id")
    if kind == "constructor" and owner.kind not in {"class", "struct"}:
        raise invalid_request("构造函数只能归属于类或结构体")
    if kind == "method" and owner.kind not in {"class", "struct", "interface"}:
        raise invalid_request("方法只能归属于类、结构体或接口")
    if kind == "field" and owner.kind not in {"class", "struct"}:
        raise invalid_request("字段只能归属于类或结构体")
    if kind in {"property", "constant"} and owner.kind not in {"class", "struct", "interface"}:
        raise invalid_request("属性和常量只能归属于类、结构体或接口")
    if namespace is not None:
        raise invalid_request("成员符号从所属类型继承命名空间，不能单独指定")
    return owner, owner.namespace


def _assert_unique(db: Session, symbol: CodeSymbol, *, exclude_id: uuid.UUID | None = None) -> None:
    rows = db.scalars(select(CodeSymbol).where(
        CodeSymbol.library_id == symbol.library_id, CodeSymbol.owner_symbol_id == symbol.owner_symbol_id,
        CodeSymbol.namespace == symbol.namespace, CodeSymbol.kind == symbol.kind, CodeSymbol.name == symbol.name,
        CodeSymbol.deleted_at.is_(None),
    )).all()
    signature = _signature(symbol)
    if any(row.id != exclude_id and _signature(row) == signature for row in rows):
        raise conflict("同一作用域中已存在相同代码符号签名")


def _save_enum_members(db: Session, symbol: CodeSymbol, members: list[dict]) -> None:
    symbol.enum_members.clear()
    db.flush()
    symbol.enum_members.extend(EnumMember(position=item["position"], name=item["name"], assigned_value=item["assigned_value"], summary=item["summary"]) for item in members)
    db.flush()


def _snapshot(db: Session, symbol: CodeSymbol, actor_id: uuid.UUID) -> None:
    snapshot = _symbol_dict(symbol, include_remarks=True, include_members=False)
    db.add(CodeSymbolVersion(symbol_id=symbol.id, revision=symbol.revision, snapshot=snapshot, created_by=actor_id))
    db.flush()


def create_symbol(db: Session, actor: User, library_id: uuid.UUID, payload: dict) -> CodeSymbol:
    library = _visible_library(db, actor, library_id, editable=True)
    kind = _clean(payload.get("kind"), "kind", 32, required=True)
    owner_raw = payload.get("owner_symbol_id")
    try:
        owner_id = uuid.UUID(str(owner_raw)) if owner_raw is not None else None
    except ValueError:
        raise invalid_request("owner_symbol_id 无效") from None
    owner, namespace = _validate_scope(db, library, kind, owner_id, payload.get("namespace"))
    definition, enum_members = _validate_definition(kind, payload.get("definition"))
    accessibility = payload.get("accessibility", "public")
    if accessibility not in ACCESSIBILITIES:
        raise invalid_request("accessibility 无效")
    symbol = CodeSymbol(
        library_id=library.id, owner_symbol_id=owner.id if owner else None, namespace=namespace, kind=kind,
        name=_clean(payload.get("name"), "名称", 256, required=True),
        summary=_clean(payload.get("summary"), "摘要", 512, required=True),
        remarks=_clean(payload.get("remarks"), "完整说明") or "", accessibility=accessibility,
        source_declaration=_clean(payload.get("source_declaration"), "源码声明"),
        since_version=_clean(payload.get("since_version"), "since_version", 64),
        deprecated=payload.get("deprecated", False), definition=definition, created_by=actor.id,
    )
    if not isinstance(symbol.deprecated, bool):
        raise invalid_request("deprecated 必须是布尔值")
    db.add(symbol)
    db.flush()
    _assert_unique(db, symbol, exclude_id=symbol.id)
    if kind == "enum":
        _save_enum_members(db, symbol, enum_members)
    _snapshot(db, symbol, actor.id)
    record_activity(db, library.project_id, actor.id, "code_symbol", symbol.id, "create", f"创建代码符号 {symbol.name}")
    db.commit()
    return symbol


def update_symbol(db: Session, actor: User, symbol_id: uuid.UUID, expected_revision: int, patch: dict) -> CodeSymbol:
    symbol = _visible_symbol(db, actor, symbol_id, editable=True)
    if expected_revision != symbol.revision:
        raise conflict("代码符号已被更新，请重新读取后再提交")
    if "kind" in patch or "owner_symbol_id" in patch or "library_id" in patch or "namespace" in patch:
        raise invalid_request("kind、归属和命名空间创建后不可直接修改")
    for field, max_length in (("name", 256), ("summary", 512), ("remarks", None), ("source_declaration", None), ("since_version", 64)):
        if field in patch:
            setattr(symbol, field, _clean(patch[field], field, max_length, required=field in {"name", "summary"}) or "")
    if "accessibility" in patch:
        if patch["accessibility"] not in ACCESSIBILITIES:
            raise invalid_request("accessibility 无效")
        symbol.accessibility = patch["accessibility"]
    if "deprecated" in patch:
        if not isinstance(patch["deprecated"], bool):
            raise invalid_request("deprecated 必须是布尔值")
        symbol.deprecated = patch["deprecated"]
    enum_members: list[dict] | None = None
    if "definition" in patch:
        definition, enum_members = _validate_definition(symbol.kind, patch["definition"])
        symbol.definition = definition
    _assert_unique(db, symbol, exclude_id=symbol.id)
    if enum_members is not None:
        _save_enum_members(db, symbol, enum_members)
    symbol.revision += 1
    _snapshot(db, symbol, actor.id)
    record_activity(db, symbol.library.project_id, actor.id, "code_symbol", symbol.id, "save", f"更新代码符号 {symbol.name}")
    db.commit()
    return symbol


def get_symbol(db: Session, user: User, symbol_id: uuid.UUID) -> dict:
    return _symbol_dict(_visible_symbol(db, user, symbol_id), include_members=True)


def list_members(db: Session, user: User, symbol_id: uuid.UUID) -> list[dict]:
    symbol = _visible_symbol(db, user, symbol_id)
    if symbol.kind not in TYPE_KINDS - {"enum"}:
        raise invalid_request("只有非枚举类型拥有独立成员符号")
    rows = db.scalars(select(CodeSymbol).where(CodeSymbol.owner_symbol_id == symbol.id, CodeSymbol.deleted_at.is_(None)).order_by(CodeSymbol.kind, CodeSymbol.name)).all()
    return [_symbol_preview(row) for row in rows]


def list_versions(db: Session, user: User, symbol_id: uuid.UUID) -> list[dict]:
    symbol = _visible_symbol(db, user, symbol_id)
    versions = db.scalars(select(CodeSymbolVersion).where(CodeSymbolVersion.symbol_id == symbol.id).order_by(CodeSymbolVersion.revision.desc())).all()
    return [{"revision": row.revision, "snapshot": copy.deepcopy(row.snapshot)} for row in versions]


def rollback_symbol(db: Session, actor: User, symbol_id: uuid.UUID, revision: int, expected_revision: int) -> CodeSymbol:
    symbol = _visible_symbol(db, actor, symbol_id, editable=True)
    if expected_revision != symbol.revision:
        raise conflict("代码符号已被更新，请重新读取后再提交")
    version = db.scalar(select(CodeSymbolVersion).where(CodeSymbolVersion.symbol_id == symbol.id, CodeSymbolVersion.revision == revision))
    if version is None:
        raise not_found("代码符号版本不存在")
    snapshot = version.snapshot
    patch = {key: snapshot[key] for key in ("name", "summary", "remarks", "accessibility", "source_declaration", "since_version", "deprecated", "definition") if key in snapshot}
    return update_symbol(db, actor, symbol.id, expected_revision, patch)


def _subtree_ids(db: Session, symbol_id: uuid.UUID) -> set[uuid.UUID]:
    found: set[uuid.UUID] = set()
    pending = [symbol_id]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(db.scalars(select(CodeSymbol.id).where(CodeSymbol.owner_symbol_id == current)).all())
    return found


def delete_symbol(db: Session, actor: User, symbol_id: uuid.UUID) -> None:
    symbol = _visible_symbol(db, actor, symbol_id, editable=True)
    rows = db.scalars(select(CodeSymbol).where(CodeSymbol.id.in_(_subtree_ids(db, symbol.id)), CodeSymbol.deleted_at.is_(None))).all()
    for row in rows:
        row.deleted_at = _now()
    record_activity(db, symbol.library.project_id, actor.id, "code_symbol", symbol.id, "delete", f"删除代码符号 {symbol.name}")
    db.commit()


def restore_symbol(db: Session, actor: User, symbol_id: uuid.UUID) -> CodeSymbol:
    symbol = _visible_symbol(db, actor, symbol_id, editable=True, include_deleted=True)
    if symbol.deleted_at is None:
        raise invalid_request("代码符号尚未删除")
    rows = db.scalars(select(CodeSymbol).where(CodeSymbol.id.in_(_subtree_ids(db, symbol.id)))).all()
    if symbol.owner_symbol_id and symbol.owner_symbol_id not in {row.id for row in rows}:
        owner = db.get(CodeSymbol, symbol.owner_symbol_id)
        if owner is None or owner.deleted_at is not None:
            raise conflict("无法恢复：所属类型已删除")
    for row in rows:
        row.deleted_at = None
    record_activity(db, symbol.library.project_id, actor.id, "code_symbol", symbol.id, "restore", f"恢复代码符号 {symbol.name}")
    db.commit()
    return symbol


def search_symbols(db: Session, user: User, project_id: uuid.UUID, query: str | None = None, library_id: uuid.UUID | None = None, kind: str | None = None) -> list[dict]:
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    stmt = select(CodeSymbol).join(CodeLibrary).where(CodeLibrary.project_id == project_id, CodeLibrary.deleted_at.is_(None), CodeSymbol.deleted_at.is_(None))
    if library_id:
        stmt = stmt.where(CodeSymbol.library_id == library_id)
    if kind:
        stmt = stmt.where(CodeSymbol.kind == kind)
    rows = db.scalars(stmt.order_by(CodeSymbol.name)).all()
    if query:
        needle = query.casefold()
        rows = [row for row in rows if needle in _qualified_name(row).casefold() or needle in row.summary.casefold()]
    return [_symbol_preview(row) for row in rows]


def code_tree(db: Session, user: User, project_id: uuid.UUID) -> dict:
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    libraries = db.scalars(select(CodeLibrary).where(CodeLibrary.project_id == project_id, CodeLibrary.deleted_at.is_(None)).order_by(CodeLibrary.name)).all()
    items = []
    group_labels = {"constructor": "构造函数", "field": "字段", "property": "属性", "method": "方法", "constant": "常量"}
    for library in libraries:
        symbols = db.scalars(select(CodeSymbol).where(CodeSymbol.library_id == library.id, CodeSymbol.deleted_at.is_(None)).order_by(CodeSymbol.name)).all()
        children: dict[uuid.UUID, list[CodeSymbol]] = {}
        roots: list[CodeSymbol] = []
        for symbol in symbols:
            (children.setdefault(symbol.owner_symbol_id, []).append(symbol) if symbol.owner_symbol_id else roots.append(symbol))

        def symbol_node(symbol: CodeSymbol) -> dict:
            groups: dict[str, list[dict]] = {}
            for child in children.get(symbol.id, []):
                groups.setdefault(group_labels[child.kind], []).append(symbol_node(child))
            return {"node_kind": "symbol", "id": str(symbol.id), "title": symbol.name, "symbol_kind": symbol.kind, "summary": symbol.summary, "signature": _signature(symbol), "children": [{"node_kind": "member_group", "id": f"group:{symbol.id}:{label}", "title": label, "children": values} for label, values in groups.items()]}

        namespace_nodes: dict[str, dict] = {}
        for symbol in roots:
            namespace = symbol.namespace or "（全局命名空间）"
            namespace_nodes.setdefault(namespace, {"node_kind": "namespace", "id": f"namespace:{library.id}:{namespace}", "title": namespace, "children": []})["children"].append(symbol_node(symbol))
        items.append({"node_kind": "library", "id": str(library.id), "title": library.name, "language": library.language, "package": library.package, "children": list(namespace_nodes.values())})
    return {"items": items}
