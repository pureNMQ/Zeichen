"""代码引用服务补边测试(规格书 §4 docs.code:校验器、作用域、版本、恢复、搜索、树)。"""

import copy
import uuid

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.services import code_reference as svc
from app.tests.conftest import make_user


def make_library(db: Session, world: dict, package="Acme.Core", **kw) -> dict:
    lib = svc.create_library(db, world["admin"], world["project"].id, "sdk", "csharp", package, **kw)
    return {"id": lib.id, "node": lib}


def make_symbol(db: Session, world: dict, library_id, kind="class", name="Thing", namespace="Acme.Core", summary="摘要", **kw) -> dict:
    payload = {"kind": kind, "name": name, "namespace": namespace, "summary": summary, "definition": kw.get("definition", {})}
    payload.update(kw.get("extra", {}))
    symbol = svc.create_symbol(db, world["admin"], library_id, payload)
    return {"id": symbol.id, "node": symbol}


class TestValidators:
    def test_clean_guards(self):
        with pytest.raises(AppError) as e:
            svc._clean(None, "name", 128, required=True)
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._clean(123, "name", 128)
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._clean("   ", "name", 128, required=True)
        assert e.value.code == "invalid_request"
        assert svc._clean("   ", "name") is None
        with pytest.raises(AppError) as e:
            svc._clean("x" * 200, "name", 128)
        assert e.value.code == "invalid_request"

    def test_reject_unknown_fields(self):
        with pytest.raises(AppError) as e:
            svc._reject_unknown_fields({"bogus": 1}, {"ok"})
        assert "bogus" in e.value.message

    def test_string_list_guards(self):
        with pytest.raises(AppError) as e:
            svc._string_list("nope", "interfaces")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._string_list(["", "x"], "interfaces")
        assert e.value.code == "invalid_request"
        assert svc._string_list(None, "interfaces") == []

    def test_type_parameters_guards(self):
        with pytest.raises(AppError) as e:
            svc._type_parameters("nope")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._type_parameters([{"constraints": ["x"]}])
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._type_parameters([{"name": "T"}, {"name": "T"}])
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._type_parameters([{"name": "T", "constraints": "nope"}])
        assert e.value.code == "invalid_request"

    def test_parameters_guards(self):
        with pytest.raises(AppError) as e:
            svc._parameters("nope")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._parameters(["x"])
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._parameters([{"type": "int"}])
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._parameters([{"name": "a", "type": "int"}, {"name": "a", "type": "int"}])
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._parameters([{"name": "a", "type": "int", "passing": "sideways"}])
        assert e.value.code == "invalid_request"

    def test_exceptions_guards(self):
        with pytest.raises(AppError) as e:
            svc._exceptions("nope")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._exceptions(["x"])
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._exceptions([{"type": "E"}])
        assert e.value.code == "invalid_request"

    def test_enum_members_guards(self):
        with pytest.raises(AppError) as e:
            svc._enum_members("nope")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._enum_members([1])
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._enum_members([{}])
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._enum_members([{"name": "A"}, {"name": "A"}])
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._enum_members([{"name": "A", "position": 2}])
        assert e.value.code == "invalid_request"

    def test_definition_guards(self):
        with pytest.raises(AppError) as e:
            svc._validate_definition("class", "nope")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._validate_definition("interface", {"base_type": "IBase"})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._validate_definition("enum", {"is_flags": "yes"})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._validate_definition("function", {"parameters": []})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._validate_definition("property", {"value_type": "int", "accessors": ["fly"]})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc._validate_definition("weird", {})
        assert e.value.code == "invalid_request"

    def test_definition_happy_paths(self):
        field_def, _ = svc._validate_definition("field", {"value_type": "int"})
        assert field_def["value_type"] == "int"
        constant_def, _ = svc._validate_definition("constant", {"value_type": "string", "value": "x"})
        assert constant_def["value"] == "x"
        property_def, _ = svc._validate_definition("property", {"value_type": "int", "accessors": ["get"]})
        assert property_def["accessors"] == ["get"]
        ctor_def, _ = svc._validate_definition("constructor", {"initializer": "base(0)"})
        assert ctor_def["initializer"] == "base(0)"


class TestLibraryEdges:
    def test_duplicate_package_conflict(self, db: Session, world: dict):
        make_library(db, world, package="Dupe.Core")
        with pytest.raises(AppError) as e:
            make_library(db, world, package="Dupe.Core")
        assert e.value.code == "conflict"


class TestSymbolEdges:
    def test_scope_guards(self, db: Session, world: dict):
        lib = make_library(db, world)["id"]
        with pytest.raises(AppError) as e:
            svc.create_symbol(db, world["admin"], lib, {"kind": "weird", "name": "X", "summary": "s"})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.create_symbol(db, world["admin"], lib, {"kind": "method", "name": "M", "summary": "s"})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.create_symbol(db, world["admin"], lib, {"kind": "class", "name": "X", "summary": "s"})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.create_symbol(db, world["admin"], lib, {"kind": "class", "name": "X", "summary": "s", "namespace": "Ns", "owner_symbol_id": str(uuid.uuid4())})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.create_symbol(db, world["admin"], lib, {"kind": "class", "name": "X", "summary": "s", "namespace": "Ns", "owner_symbol_id": "not-a-uuid"})
        assert e.value.code == "invalid_request"

    def test_member_owner_rules(self, db: Session, world: dict):
        lib = make_library(db, world)["id"]
        enum = make_symbol(db, world, lib, kind="enum", name="Mode", definition={"members": [{"name": "On"}]})["id"]
        with pytest.raises(AppError) as e:
            svc.create_symbol(db, world["admin"], lib, {"kind": "method", "name": "M", "summary": "s", "owner_symbol_id": enum})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.create_symbol(db, world["admin"], lib, {"kind": "field", "name": "F", "summary": "s", "owner_symbol_id": enum})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.create_symbol(db, world["admin"], lib, {"kind": "constructor", "name": "C", "summary": "s", "owner_symbol_id": enum})
        assert e.value.code == "invalid_request"

    def test_owner_namespace_inherited(self, db: Session, world: dict):
        lib = make_library(db, world)["id"]
        klass = make_symbol(db, world, lib, kind="class", name="Widget")["id"]
        member = svc.create_symbol(
            db, world["admin"], lib,
            {"kind": "method", "name": "Spin", "summary": "s", "owner_symbol_id": klass,
             "definition": {"parameters": [], "returns": {"type": "void"}}},
        )
        assert member.namespace == "Acme.Core"

    def test_scope_validation_errors(self, db: Session, world: dict):
        lib = make_library(db, world)["id"]
        with pytest.raises(AppError) as e:
            svc.create_symbol(db, world["admin"], lib, {"kind": "method", "name": "M", "summary": "s", "owner_symbol_id": uuid.uuid4(), "namespace": "Acme.Core"})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.create_symbol(db, world["admin"], lib, {"kind": "property", "name": "P", "summary": "s", "owner_symbol_id": uuid.uuid4(), "namespace": "Acme.Core"})
        assert e.value.code == "invalid_request"

    def test_enum_create_and_update(self, db: Session, world: dict):
        lib = make_library(db, world)["id"]
        mode = make_symbol(db, world, lib, kind="enum", name="Mode", definition={"members": [{"name": "Read", "position": 0}, {"name": "Write", "position": 1}]})["node"]
        assert [m.name for m in mode.enum_members] == ["Read", "Write"]
        updated = svc.update_symbol(db, world["admin"], mode.id, 1, {"definition": {"is_flags": True, "members": [{"name": "Read", "position": 0}]}})
        assert [m.name for m in updated.enum_members] == ["Read"]

    def test_update_guards(self, db: Session, world: dict):
        lib = make_library(db, world)["id"]
        klass = make_symbol(db, world, lib, kind="class", name="Lock")["id"]
        with pytest.raises(AppError) as e:
            svc.update_symbol(db, world["admin"], klass, 99, {"summary": "x"})
        assert e.value.code == "conflict"
        with pytest.raises(AppError) as e:
            svc.update_symbol(db, world["admin"], klass, 1, {"kind": "struct"})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.update_symbol(db, world["admin"], klass, 1, {"accessibility": "friendly"})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.update_symbol(db, world["admin"], klass, 1, {"deprecated": "yes"})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.update_symbol(db, world["admin"], klass, 1, {"bogus": 1})
        assert e.value.code == "invalid_request"

    def test_members_and_versions(self, db: Session, world: dict):
        lib = make_library(db, world)["id"]
        klass = make_symbol(db, world, lib, kind="class", name="Host")["id"]
        make_symbol(db, world, lib, kind="method", name="Run", namespace=None,
                    extra={"owner_symbol_id": klass, "definition": {"parameters": [], "returns": {"type": "void"}}})
        svc.create_symbol(db, world["admin"], lib, {"kind": "method", "name": "Stop", "summary": "s", "owner_symbol_id": klass, "definition": {"parameters": [], "returns": {"type": "void"}}})
        members = svc.list_members(db, world["member"], klass)
        assert [m["name"] for m in members] == ["Run", "Stop"]
        with pytest.raises(AppError) as e:
            svc.list_members(db, world["member"], make_symbol(db, world, lib, kind="function", name="Top", definition={"parameters": [], "returns": {"type": "int"}})["id"])
        assert e.value.code == "invalid_request"
        versions = svc.list_versions(db, world["member"], klass)
        assert [v["revision"] for v in versions] == [1]
        assert versions[0]["snapshot"]["name"] == "Host"

    def test_rollback(self, db: Session, world: dict):
        lib = make_library(db, world)["id"]
        fn = make_symbol(db, world, lib, kind="function", name="Sum", definition={"parameters": [], "returns": {"type": "int"}})["id"]
        svc.update_symbol(db, world["admin"], fn, 1, {"summary": "v2 摘要"})
        with pytest.raises(AppError) as e:
            svc.rollback_symbol(db, world["admin"], fn, 1, 99)
        assert e.value.code == "conflict"
        with pytest.raises(AppError) as e:
            svc.rollback_symbol(db, world["admin"], fn, 42, 2)
        assert e.value.code == "not_found"
        rolled = svc.rollback_symbol(db, world["admin"], fn, 1, 2)
        assert rolled.summary == "摘要"
        assert rolled.revision == 3

    def test_restore_guards(self, db: Session, world: dict):
        lib = make_library(db, world)["id"]
        klass = make_symbol(db, world, lib, kind="class", name="Gone")["id"]
        with pytest.raises(AppError) as e:
            svc.restore_symbol(db, world["admin"], klass)
        assert e.value.code == "invalid_request"
        svc.delete_symbol(db, world["admin"], klass)
        assert svc.restore_symbol(db, world["admin"], klass).deleted_at is None

    def test_restore_orphan_conflict(self, db: Session, world: dict):
        lib = make_library(db, world)["id"]
        klass = make_symbol(db, world, lib, kind="class", name="Owner")["id"]
        method = make_symbol(db, world, lib, kind="method", name="Inner", namespace=None,
                             extra={"owner_symbol_id": klass, "definition": {"parameters": [], "returns": {"type": "void"}}})["id"]
        svc.delete_symbol(db, world["admin"], klass)
        with pytest.raises(AppError) as e:
            svc.restore_symbol(db, world["admin"], method)
        assert e.value.code == "conflict"


class TestSearchAndTree:
    def test_search_symbols_filters(self, db: Session, world: dict):
        lib = make_library(db, world, package="Search.Core")["id"]
        make_symbol(db, world, lib, kind="class", name="Alpha", summary="handles login")
        make_symbol(db, world, lib, kind="struct", name="Beta")
        by_kind = svc.search_symbols(db, world["member"], world["project"].id, kind="struct")
        assert [s["name"] for s in by_kind] == ["Beta"]
        by_lib = svc.search_symbols(db, world["member"], world["project"].id, library_id=lib)
        assert len(by_lib) == 2
        by_query = svc.search_symbols(db, world["member"], world["project"].id, query="LOGIN")
        assert [s["name"] for s in by_query] == ["Alpha"]
        empty = svc.search_symbols(db, world["member"], world["project"].id, query="missing term")
        assert empty == []

    def test_code_tree_groups_members_by_kind(self, db: Session, world: dict):
        lib = make_library(db, world, package="Tree.Core")["id"]
        klass = make_symbol(db, world, lib, kind="class", name="Player")["id"]
        for kind, name, definition in (
            ("method", "Move", {"parameters": [], "returns": {"type": "void"}}),
            ("field", "speed", {"value_type": "float"}),
            ("property", "Name", {"value_type": "string", "accessors": ["get"]}),
        ):
            svc.create_symbol(db, world["admin"], lib, {"kind": kind, "name": name, "summary": "s", "owner_symbol_id": klass, "definition": definition})
        tree = svc.code_tree(db, world["member"], world["project"].id)
        root = tree["items"][0]
        assert root["node_kind"] == "library"
        namespace = root["children"][0]
        assert namespace["node_kind"] == "namespace"
        player = namespace["children"][0]
        group_titles = sorted(g["title"] for g in player["children"])
        assert group_titles == ["字段", "属性", "方法"]
