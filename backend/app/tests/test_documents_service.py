"""文档服务补边测试(规格书 §4 docs.wiki/glossary 与 HTTP 同后端)。"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Document, DocumentDirectory, DocumentVersion
from app.services import documents as svc
from app.services import polymorphic as poly_svc


def make_wiki(db: Session, world: dict, title="根 Wiki", parent_id=None, content="内容", **kw) -> dict:
    doc = svc.create_document(
        db, world["admin"], world["project"].id, title, "wiki", content, {}, parent_id=parent_id, **kw
    )
    return {"id": doc.id, "node": doc}


def make_term(db: Session, world: dict, title="词条", directory_id=None, **kw) -> dict:
    doc = svc.create_document(
        db, world["admin"], world["project"].id, title, "glossary", "定义", {}, directory_id=directory_id, **kw
    )
    return {"id": doc.id, "node": doc}


class TestCreateDocument:
    def test_invalid_module(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.create_document(db, world["admin"], world["project"].id, "t", "api", "c", {})
        assert e.value.code == "invalid_request"

    def test_empty_title(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.create_document(db, world["admin"], world["project"].id, "  ", "wiki", "c", {})
        assert e.value.code == "invalid_request"

    def test_viewer_denied(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.create_document(db, world["member"], world["project"].id, "t", "wiki", "c", {})
        assert e.value.code == "permission_denied"

    def test_wiki_rejects_directory(self, db: Session, world: dict):
        directory = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "术语")
        with pytest.raises(AppError) as e:
            svc.create_document(db, world["admin"], world["project"].id, "t", "wiki", "c", {}, directory_id=directory.id)
        assert e.value.code == "invalid_request"

    def test_glossary_rejects_parent(self, db: Session, world: dict):
        parent = make_wiki(db, world)["id"]
        with pytest.raises(AppError) as e:
            svc.create_document(db, world["admin"], world["project"].id, "t", "glossary", "c", {}, parent_id=parent)
        assert e.value.code == "invalid_request"

    def test_sibling_title_conflict_and_cross_branch_freedom(self, db: Session, world: dict):
        make_wiki(db, world, "同名")
        with pytest.raises(AppError) as e:
            make_wiki(db, world, "同名")
        assert e.value.code == "conflict"
        other = make_wiki(db, world, "其他")
        child = make_wiki(db, world, "同名", parent_id=other["id"])
        assert child["node"].parent_id == other["id"]

    def test_glossary_title_unique_per_project(self, db: Session, world: dict):
        make_term(db, world, "重复词")
        with pytest.raises(AppError) as e:
            make_term(db, world, "重复词")
        assert e.value.code == "conflict"
        assert "词条" in e.value.message

    def test_parent_validation(self, db: Session, world: dict):
        from app.models import Project

        other = Project(team_id=world["team"].id, name="other")
        db.add(other)
        db.commit()
        foreign = svc.create_document(db, world["admin"], other.id, "外部", "wiki", "", {})
        with pytest.raises(AppError) as e:
            make_wiki(db, world, "子", parent_id=foreign.id)
        assert e.value.code == "invalid_request"
        term = make_term(db, world, "词条X")["node"]
        with pytest.raises(AppError) as e:
            make_wiki(db, world, "子", parent_id=term.id)
        assert e.value.code == "invalid_request"

    def test_child_reports_has_children_flag(self, db: Session, world: dict):
        root = make_wiki(db, world, "根")["node"]
        make_wiki(db, world, "叶子", parent_id=root.id)
        doc = svc.get_document(db, world["member"], root.id)
        assert svc._document_dict(db, doc)["has_children"] is True
        term = make_term(db, world, "词")["node"]
        assert svc._document_dict(db, term)["has_children"] is False


class TestUpdateDocument:
    def test_update_creates_version(self, db: Session, world: dict):
        created = make_wiki(db, world, "初版", content="v1")
        doc, warning = svc.update_document(
            db, world["admin"], created["id"], title="新版", content="v2", metadata={"tags": ["a"]}
        )
        assert warning is None
        assert doc.title == "新版"
        versions = svc.list_versions(db, world["member"], created["id"])
        assert [v["version_no"] for v in versions] == [2, 1]
        assert versions[0]["content"] == "v2"

    def test_update_validation(self, db: Session, world: dict):
        created = make_wiki(db, world, "标题")
        with pytest.raises(AppError) as e:
            svc.update_document(db, world["admin"], created["id"], title="  ")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.update_document(db, world["admin"], created["id"], metadata="not-dict")
        assert e.value.code == "invalid_request"
        make_wiki(db, world, "占用")
        with pytest.raises(AppError) as e:
            svc.update_document(db, world["admin"], created["id"], title="占用")
        assert e.value.code == "conflict"
        with pytest.raises(AppError) as e:
            svc.update_document(db, world["member"], created["id"], content="x")
        assert e.value.code == "permission_denied"

    def test_versions_pruned_beyond_twenty(self, db: Session, world: dict):
        created = make_wiki(db, world, "版本雨")
        for i in range(24):
            svc.update_document(db, world["admin"], created["id"], content=f"c{i}")
        versions = svc.list_versions(db, world["member"], created["id"])
        assert len(versions) == 20
        assert versions[0]["version_no"] == 25


class TestMoveDocument:
    def test_move_into_own_descendant_rejected(self, db: Session, world: dict):
        root = make_wiki(db, world, "根")["id"]
        child = make_wiki(db, world, "子", parent_id=root)["id"]
        with pytest.raises(AppError) as e:
            svc.move_document(db, world["admin"], root, parent_id=child)
        assert e.value.code == "invalid_request"
        assert "后代" in e.value.message

    def test_move_to_self_rejected(self, db: Session, world: dict):
        root = make_wiki(db, world, "根")["id"]
        with pytest.raises(AppError) as e:
            svc.move_document(db, world["admin"], root, parent_id=root)
        assert e.value.code == "invalid_request"

    def test_valid_move_reparents(self, db: Session, world: dict):
        a = make_wiki(db, world, "A")["id"]
        b = make_wiki(db, world, "B")["id"]
        moved = svc.move_document(db, world["admin"], a, parent_id=b)
        assert moved.parent_id == b

    def test_move_keeps_sibling_title_rule(self, db: Session, world: dict):
        a = make_wiki(db, world, "A")["id"]
        b = make_wiki(db, world, "B")["id"]
        make_wiki(db, world, "A", parent_id=b)
        with pytest.raises(AppError) as e:
            svc.move_document(db, world["admin"], a, parent_id=b)
        assert e.value.code == "conflict"


class TestDirectories:
    def test_directory_validation(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.create_directory(db, world["admin"], world["project"].id, "wiki", "x")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.create_directory(db, world["admin"], world["project"].id, "glossary", "  ")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.create_directory(db, world["member"], world["project"].id, "glossary", "x")
        assert e.value.code == "permission_denied"

    def test_directory_name_unique_per_level(self, db: Session, world: dict):
        parent = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "网络")
        with pytest.raises(AppError) as e:
            svc.create_directory(db, world["admin"], world["project"].id, "glossary", "网络")
        assert e.value.code == "conflict"
        nested = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "网络", parent_id=parent.id)
        assert nested.parent_id == parent.id

    def test_rename_directory(self, db: Session, world: dict):
        directory = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "旧名")
        with pytest.raises(AppError) as e:
            svc.rename_directory(db, world["admin"], directory.id, "  ")
        assert e.value.code == "invalid_request"
        renamed = svc.rename_directory(db, world["admin"], directory.id, "新名")
        assert renamed.name == "新名"

    def test_move_directory_cycles_rejected(self, db: Session, world: dict):
        parent = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "父")
        child = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "子", parent_id=parent.id)
        with pytest.raises(AppError) as e:
            svc.move_directory(db, world["admin"], parent.id, child.id)
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.move_directory(db, world["admin"], parent.id, parent.id)
        assert e.value.code == "invalid_request"
        assert svc.move_directory(db, world["admin"], child.id, None).parent_id is None

    def test_delete_and_restore_directory_tree(self, db: Session, world: dict):
        directory = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "数学")
        term = make_term(db, world, "质数", directory_id=directory.id)["node"]

        impact = svc.delete_impact_directory(db, world["member"], directory.id)
        assert impact == {"documents": 1, "directories": 1}

        svc.delete_directory(db, world["admin"], directory.id)
        assert db.get(Document, term.id).deleted_at is not None
        assert db.get(DocumentDirectory, directory.id).deleted_at is not None

        restored = svc.restore_directory(db, world["admin"], directory.id)
        assert restored.deleted_at is None
        assert db.get(Document, term.id).deleted_at is None

    def test_restore_directory_conflicts_on_name(self, db: Session, world: dict):
        directory = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "物理")
        svc.delete_directory(db, world["admin"], directory.id)
        svc.create_directory(db, world["admin"], world["project"].id, "glossary", "物理")
        with pytest.raises(AppError) as e:
            svc.restore_directory(db, world["admin"], directory.id)
        assert e.value.code == "conflict"

    def test_restore_directory_missing_or_alive(self, db: Session, world: dict):
        directory = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "化学")
        with pytest.raises(AppError) as e:
            svc.restore_directory(db, world["admin"], directory.id)
        assert e.value.code == "not_found"
        with pytest.raises(AppError) as e:
            svc.restore_directory(db, world["admin"], uuid.uuid4())
        assert e.value.code == "not_found"


class TestDeleteRestoreDocument:
    def test_delete_impact_and_recursive_delete(self, db: Session, world: dict):
        root = make_wiki(db, world, "根")["id"]
        child = make_wiki(db, world, "子", parent_id=root)["id"]
        impact = svc.delete_impact_document(db, world["member"], root)
        assert impact == {"documents": 2, "directories": 0}
        svc.delete_document(db, world["admin"], root)
        assert db.get(Document, root).deleted_at is not None
        assert db.get(Document, child).deleted_at is not None

    def test_restore_requires_deleted_and_parent_chain(self, db: Session, world: dict):
        root = make_wiki(db, world, "根")["id"]
        child = make_wiki(db, world, "子", parent_id=root)["id"]
        with pytest.raises(AppError) as e:
            svc.restore_document(db, world["admin"], root)
        assert e.value.code == "not_found"
        svc.delete_document(db, world["admin"], root)
        with pytest.raises(AppError) as e:
            svc.restore_document(db, world["admin"], child)
        assert e.value.code == "conflict"
        assert "父 Wiki" in e.value.message
        restored = svc.restore_document(db, world["admin"], root)
        assert restored.deleted_at is None
        assert db.get(Document, child).deleted_at is None

    def test_restore_conflicts_on_title(self, db: Session, world: dict):
        gone = make_term(db, world, "旧词")["id"]
        svc.delete_document(db, world["admin"], gone)
        make_term(db, world, "旧词")
        with pytest.raises(AppError) as e:
            svc.restore_document(db, world["admin"], gone)
        assert e.value.code == "conflict"

    def test_glossary_delete_and_restore(self, db: Session, world: dict):
        term = make_term(db, world, "单体")["id"]
        svc.delete_document(db, world["admin"], term)
        assert db.get(Document, term).deleted_at is not None
        assert svc.restore_document(db, world["admin"], term).deleted_at is None

    def test_glossary_deleted_nodes_listing(self, db: Session, world: dict):
        directory = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "待回收")
        term = make_term(db, world, "孤儿词", directory_id=directory.id)["id"]
        svc.delete_directory(db, world["admin"], directory.id)
        page = svc.list_deleted_nodes(db, world["member"], world["project"].id, "glossary", None, 20)
        kinds = {(item["node_kind"], item["title"]) for item in page["items"]}
        assert ("directory", "待回收") in kinds
        assert ("document", "孤儿词") in kinds


class TestListingAndPaths:
    def test_wiki_children_sorted_and_paginated(self, db: Session, world: dict):
        root = make_wiki(db, world, "根")["id"]
        for title in ("b", "a", "c"):
            make_wiki(db, world, title, parent_id=root)
        page = svc.list_module_children(db, world["member"], world["project"].id, "wiki", root, None, 20)
        assert [item["title"] for item in page["items"]] == ["a", "b", "c"]
        page1 = svc.list_module_children(db, world["member"], world["project"].id, "wiki", root, None, 2)
        assert len(page1["items"]) == 2
        page2 = svc.list_module_children(db, world["member"], world["project"].id, "wiki", root, page1["next_cursor"], 2)
        assert [item["title"] for item in page2["items"]] == ["c"]

    def test_glossary_children_mix_directories_and_documents(self, db: Session, world: dict):
        directory = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "目录")
        make_term(db, world, "词条", directory_id=directory.id)
        make_term(db, world, "散词")
        page = svc.list_module_children(db, world["member"], world["project"].id, "glossary", None, None, 20)
        assert [item["node_kind"] for item in page["items"]] == ["directory", "document"]
        assert [item["title"] for item in page["items"]] == ["目录", "散词"]
        inside = svc.list_module_children(db, world["member"], world["project"].id, "glossary", directory.id, None, 20)
        assert [item["title"] for item in inside["items"]] == ["词条"]

    def test_ancestor_paths(self, db: Session, world: dict):
        root = make_wiki(db, world, "根")["id"]
        child = make_wiki(db, world, "子", parent_id=root)["id"]
        wiki_path = svc.ancestor_path(db, world["member"], world["project"].id, "wiki", "document", child)
        assert [item["title"] for item in wiki_path["items"]] == ["根", "子"]

        directory = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "顶层")
        sub = svc.create_directory(db, world["admin"], world["project"].id, "glossary", "子层", parent_id=directory.id)
        term = make_term(db, world, "深词", directory_id=sub.id)["node"]
        deep = svc.ancestor_path(db, world["member"], world["project"].id, "glossary", "document", term.id)
        assert [item["title"] for item in deep["items"]] == ["顶层", "子层", "深词"]

        bare = make_term(db, world, "散词")["node"]
        bare_path = svc.ancestor_path(db, world["member"], world["project"].id, "glossary", "document", bare.id)
        assert [item["title"] for item in bare_path["items"]] == ["散词"]

        dir_path = svc.ancestor_path(db, world["member"], world["project"].id, "glossary", "directory", sub.id)
        assert [item["title"] for item in dir_path["items"]] == ["顶层", "子层"]

        with pytest.raises(AppError) as e:
            svc.ancestor_path(db, world["member"], world["project"].id, "glossary", "document", uuid.uuid4())
        assert e.value.code == "not_found"
        with pytest.raises(AppError) as e:
            svc.ancestor_path(db, world["member"], world["project"].id, "wiki", "directory", root)
        assert e.value.code == "invalid_request"

    def test_ancestor_path_cross_project_document(self, db: Session, world: dict):
        from app.models import Project

        other = Project(team_id=world["team"].id, name="other")
        db.add(other)
        db.commit()
        foreign = svc.create_document(db, world["admin"], other.id, "外部", "wiki", "", {})
        with pytest.raises(AppError) as e:
            svc.ancestor_path(db, world["member"], world["project"].id, "wiki", "document", foreign.id)
        assert e.value.code == "not_found"

    def test_wrong_module_access_hidden(self, db: Session, world: dict):
        term = make_term(db, world, "词")["id"]
        with pytest.raises(AppError) as e:
            svc.get_document(db, world["member"], term, module="wiki")
        assert e.value.code == "not_found"

    def test_get_glossary_term(self, db: Session, world: dict):
        make_term(db, world, "契约")
        assert svc.get_glossary_term(db, world["member"], world["project"].id, "契约").doc_type == "glossary"
        with pytest.raises(AppError) as e:
            svc.get_glossary_term(db, world["member"], world["project"].id, "不存在")
        assert e.value.code == "not_found"


class TestVersionsAndReferences:
    def test_rollback_document(self, db: Session, world: dict):
        created = make_wiki(db, world, "标题1", content="c1")
        svc.update_document(db, world["admin"], created["id"], title="标题2", content="c2")
        rolled = svc.rollback_document(db, world["admin"], created["id"], 1)
        assert rolled.title == "标题1"
        assert rolled.content == "c1"
        versions = svc.list_versions(db, world["member"], created["id"])
        assert versions[0]["version_no"] == 3

    def test_rollback_validation(self, db: Session, world: dict):
        created = make_wiki(db, world, "标题")
        with pytest.raises(AppError) as e:
            svc.rollback_document(db, world["admin"], created["id"], 99)
        assert e.value.code == "not_found"
        with pytest.raises(AppError) as e:
            svc.rollback_document(db, world["admin"], created["id"], 1, module="glossary")
        assert e.value.code == "not_found"
        with pytest.raises(AppError) as e:
            svc.rollback_document(db, world["member"], created["id"], 1)
        assert e.value.code == "permission_denied"

    def test_document_references_bidirectional(self, db: Session, world: dict):
        wiki = make_wiki(db, world, "参考文档")["node"]
        task_doc = make_term(db, world, "任务")["node"]
        poly_svc.create_reference(db, world["admin"], "document", wiki.id, "document", task_doc.id, "mentions")
        refs = svc.document_references(db, world["member"], wiki.id, "wiki")
        assert refs["count"] == 1
        assert refs["items"][0]["to_id"] == str(task_doc.id)
        other = svc.document_references(db, world["member"], task_doc.id, "glossary")
        assert other["count"] == 1
        assert other["items"][0]["from_id"] == str(wiki.id)


class TestAccessGuards:
    def test_deleted_document_hidden_from_reads(self, db: Session, world: dict):
        term = make_term(db, world, "已删")["id"]
        svc.delete_document(db, world["admin"], term)
        with pytest.raises(AppError) as e:
            svc.get_document(db, world["member"], term)
        assert e.value.code == "not_found"
        with pytest.raises(AppError) as e:
            svc.get_directory(db, world["member"], uuid.uuid4())
        assert e.value.code == "not_found"
