"""文档服务测试(REQ-59:wiki 单模块、frontmatter、[[双链]]、溯源、INDEX)。"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import DocLink, Document, DocumentVersion
from app.services import documents as svc
from app.services import polymorphic as poly_svc


def db_scalar_doc(db, code):
    from sqlalchemy import select as _select

    return db.scalar(_select(Document).where(Document.code == code).limit(1))


def make_wiki(
    db: Session, world: dict, title="根 Wiki", parent_id=None, content="内容", metadata=None, **kw
) -> dict:
    document, _warnings = svc.create_document(
        db, world["admin"], world["project"].id, title, "wiki", content, metadata or {}, parent_id=parent_id, **kw
    )
    return {"id": document.code, "node": document, "warnings": _warnings}


class TestCreateDocument:
    def test_invalid_module(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.create_document(db, world["admin"], world["project"].id, "t", "glossary", "c", {})
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.create_document(db, world["admin"], world["project"].id, "t", "api", "c", {})
        assert e.value.code == "invalid_request"

    def test_directory_rejected(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.create_document(db, world["admin"], world["project"].id, "t", "wiki", "c", {}, directory_id="DIR-1")
        assert e.value.code == "invalid_request"

    def test_empty_title(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.create_document(db, world["admin"], world["project"].id, "  ", "wiki", "c", {})
        assert e.value.code == "invalid_request"

    def test_title_link_chars_rejected(self, db: Session, world: dict):
        for bad in ("带[括号", "带|竖线", "带#井号"):
            with pytest.raises(AppError) as e:
                svc.create_document(db, world["admin"], world["project"].id, bad, "wiki", "c", {})
            assert e.value.code == "invalid_request"
            assert "链接语法字符" in e.value.message

    def test_viewer_denied(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.create_document(db, world["member"], world["project"].id, "t", "wiki", "c", {})
        assert e.value.code == "permission_denied"

    def test_sibling_title_conflict_and_cross_branch_freedom(self, db: Session, world: dict):
        make_wiki(db, world, "同名")
        with pytest.raises(AppError) as e:
            make_wiki(db, world, "同名")
        assert e.value.code == "conflict"
        other = make_wiki(db, world, "其他")
        child = make_wiki(db, world, "同名", parent_id=other["id"])
        assert child["node"].parent_id == other["id"]

    def test_parent_validation(self, db: Session, world: dict):
        from app.models import Project

        other = Project(team_id=world["team"].id, name="other")
        db.add(other)
        db.commit()
        foreign, _ = svc.create_document(db, world["admin"], other.id, "外部", "wiki", "", {})
        # 短码按项目内寻址(ADR 0002):他项目父码在本项目视同不存在
        with pytest.raises(AppError) as e:
            make_wiki(db, world, "子", parent_id=foreign.code)
        assert e.value.code == "not_found"

    def test_has_children_flag(self, db: Session, world: dict):
        root = make_wiki(db, world, "根")["node"]
        make_wiki(db, world, "叶子", parent_id=root.code)
        doc = svc.get_document(db, world["member"], root.code)
        assert svc._document_dict(db, doc)["has_children"] is True
        single = make_wiki(db, world, "独")["node"]
        assert svc._document_dict(db, single)["has_children"] is False


class TestFrontmatter:
    def test_frontmatter_parsed_into_metadata(self, db: Session, world: dict):
        content = "---\nsummary: 一句话摘要\ndoc_kind: decision\ntags: [a, b]\naliases:\n  - 别名一\n---\n\n正文开始"
        document, _ = svc.create_document(
            db, world["admin"], world["project"].id, "带frontmatter", "wiki", content, {}
        )
        assert document.doc_metadata["summary"] == "一句话摘要"
        assert document.doc_metadata["doc_kind"] == "decision"
        assert document.doc_metadata["tags"] == ["a", "b"]
        assert document.doc_metadata["aliases"] == ["别名一"]
        # 正文含 frontmatter 原样保存(存储不剥离)
        assert document.content.startswith("---\n")

    def test_frontmatter_overrides_explicit_metadata(self, db: Session, world: dict):
        content = "---\ndoc_kind: concept\n---\n正文"
        document, _ = svc.create_document(
            db, world["admin"], world["project"].id, "合并", "wiki", content, {"doc_kind": "spec", "custom": 1}
        )
        assert document.doc_metadata["doc_kind"] == "concept"
        assert document.doc_metadata["custom"] == 1

    def test_no_frontmatter_keeps_explicit_metadata(self, db: Session, world: dict):
        document, _ = svc.create_document(
            db, world["admin"], world["project"].id, "无frontmatter", "wiki", "纯正文", {"doc_kind": "howto"}
        )
        assert document.doc_metadata["doc_kind"] == "howto"

    def test_invalid_yaml_treated_as_body(self, db: Session, world: dict):
        content = "---\n: :\n  bad yaml [\n---\n正文"
        document, _ = svc.create_document(
            db, world["admin"], world["project"].id, "坏YAML", "wiki", content, {}
        )
        assert "doc_kind" not in (document.doc_metadata or {})

    def test_unknown_kind_kept_as_is(self, db: Session, world: dict):
        content = "---\ndoc_kind: 自定义形态\n---\n正文"
        document, _ = svc.create_document(
            db, world["admin"], world["project"].id, "自定义", "wiki", content, {}
        )
        assert document.doc_metadata["doc_kind"] == "自定义形态"

    def test_update_content_reparses_frontmatter(self, db: Session, world: dict):
        created = make_wiki(db, world, "改frontmatter", content="v1")
        svc.update_document(
            db, world["admin"], created["id"], content="---\ndoc_kind: spec\nsummary: s\n---\nv2"
        )
        doc = db_scalar_doc(db, created["id"])
        assert doc.doc_metadata["doc_kind"] == "spec"
        assert doc.doc_metadata["summary"] == "s"

    def test_rollback_restores_metadata_and_links(self, db: Session, world: dict):
        target = make_wiki(db, world, "目标页", content="t")["id"]
        created = make_wiki(db, world, "带链接", content=f"看 [[{target}]]")
        svc.update_document(db, world["admin"], created["id"], content="链接没了", metadata={"doc_kind": "concept"})
        rolled, _ = svc.rollback_document(db, world["admin"], created["id"], 1)
        assert rolled.content == f"看 [[{target}]]"
        assert rolled.doc_metadata.get("doc_kind") is None
        links = svc._links_payload(db, rolled)
        assert [item["to_code"] for item in links["outgoing"]] == [target]

    def test_alias_with_link_chars_rejected(self, db: Session, world: dict):
        content = "---\naliases: ['坏[别名']\n---\n正文"
        with pytest.raises(AppError) as e:
            svc.create_document(db, world["admin"], world["project"].id, "坏别名", "wiki", content, {})
        assert e.value.code == "invalid_request"


class TestWikiLinks:
    def test_code_title_alias_resolution(self, db: Session, world: dict):
        target = make_wiki(db, world, "目标页", content="t")["id"]
        aliased = make_wiki(
            db, world, "别名页", content="---\naliases: [醒目别名]\n---\nb"
        )["id"]
        source, warnings = svc.create_document(
            db, world["admin"], world["project"].id,
            "链接源", "wiki",
            f"短码 [[{target}]] 标题 [[目标页|显示名]] 别名 [[醒目别名]] 小节 [[目标页#章节]] 断链 [[不存在页]]",
            {},
        )
        assert warnings is not None
        assert warnings["count"] == 1
        assert warnings["items"][0]["raw_text"] == "不存在页"
        links = svc._links_payload(db, source)
        outgoing = links["outgoing"]
        assert len(outgoing) == 5
        by_key = {(item["raw_text"], item["display"], item["section"]): item for item in outgoing}
        assert by_key[(target, None, None)]["to_code"] == target
        assert not by_key[(target, None, None)]["broken"]
        assert by_key[("目标页", "显示名", None)]["to_code"] == target
        assert by_key[("醒目别名", None, None)]["to_code"] == aliased
        assert by_key[("目标页", None, "章节")]["to_code"] == target
        assert by_key[("不存在页", None, None)]["broken"] is True
        assert by_key[("不存在页", None, None)]["to_code"] is None

    def test_backlinks_visible_from_target(self, db: Session, world: dict):
        target = make_wiki(db, world, "被链页", content="t")
        source = make_wiki(db, world, "链出页", content=f"参见 [[{target['id']}]]")["id"]
        links = svc._links_payload(db, target["node"])
        assert [item["from_code"] for item in links["incoming"]] == [source]
        assert links["incoming"][0]["from_title"] == "链出页"

    def test_duplicate_title_link_is_broken(self, db: Session, world: dict):
        make_wiki(db, world, "同名页", content="a", parent_id=None)
        other = make_wiki(db, world, "父页", content="p")["id"]
        make_wiki(db, world, "同名页", content="b", parent_id=other)
        source, warnings = svc.create_document(
            db, world["admin"], world["project"].id, "歧义源", "wiki", "看 [[同名页]]", {}
        )
        assert warnings["count"] == 1
        assert "同名" in warnings["items"][0]["reason"]
        links = svc._links_payload(db, source)
        assert links["outgoing"][0]["broken"] is True

    def test_deleted_target_renders_broken_and_delete_clears_outgoing(
        self, db: Session, world: dict
    ):
        target = make_wiki(db, world, "将删页", content="t")["id"]
        source = make_wiki(db, world, "存活页", content=f"看 [[{target}]]")["id"]
        svc.delete_document(db, world["admin"], target)
        links = svc._links_payload(db, db_scalar_doc(db, source))
        # 入链行保留,目标已删 → 断链呈现
        assert links["outgoing"][0]["broken"] is True
        assert links["outgoing"][0]["to_title"] is None
        # 删除将删页时,其自身出链行被清理
        assert db.query(DocLink).filter_by(from_code=target).count() == 0

    def test_restore_rebuilds_outgoing_links(self, db: Session, world: dict):
        target = make_wiki(db, world, "恢复目标", content="t")["id"]
        source = make_wiki(db, world, "恢复源", content=f"看 [[{target}]]")["id"]
        svc.delete_document(db, world["admin"], source)
        assert db.query(DocLink).filter_by(from_code=source).count() == 0
        svc.restore_document(db, world["admin"], source)
        links = svc._links_payload(db, db_scalar_doc(db, source))
        assert [item["to_code"] for item in links["outgoing"]] == [target]

    def test_link_rows_replaced_on_update(self, db: Session, world: dict):
        target = make_wiki(db, world, "旧目标", content="t")["id"]
        source = make_wiki(db, world, "换链页", content=f"看 [[{target}]]")["id"]
        assert db.query(DocLink).filter_by(from_code=source).count() == 1
        svc.update_document(db, world["admin"], source, content="没有链接了")
        assert db.query(DocLink).filter_by(from_code=source).count() == 0

    def test_links_not_parsed_inside_frontmatter(self, db: Session, world: dict):
        source, warnings = svc.create_document(
            db, world["admin"], world["project"].id, "fm链接", "wiki",
            "---\nsummary: 里面是 [[不该解析]]\n---\n正文干净",
            {},
        )
        assert warnings is None
        assert svc._links_payload(db, source)["outgoing"] == []


class TestProvenance:
    def test_author_projection_human(self, db: Session, world: dict):
        document, _ = svc.create_document(
            db, world["admin"], world["project"].id, "人写的", "wiki", "c", {}
        )
        payload = svc._document_dict(db, document)
        assert payload["author"]["is_agent"] is False
        assert payload["author"]["username"] == world["admin"].username
        assert payload["author"]["owner"] is None

    def test_author_projection_agent_with_owner(self, db: Session, world: dict):
        from app.models import User

        agent = User(username="prov-agent", password_hash="", is_agent=True, owner_id=world["admin"].id)
        db.add(agent)
        db.commit()
        document, _ = svc.create_document(db, agent, world["project"].id, "agent写的", "wiki", "c", {})
        payload = svc._document_dict(db, document)
        assert payload["author"]["is_agent"] is True
        assert payload["author"]["owner"]["username"] == world["admin"].username
        versions = svc.list_versions(db, world["admin"], document.code)
        assert versions[0]["author"]["is_agent"] is True
        assert versions[0]["author"]["owner"]["id"] == str(world["admin"].id)


class TestProjectIndex:
    def test_index_sections_and_lint(self, db: Session, world: dict):
        make_wiki(db, world, "决策页", content="---\ndoc_kind: decision\nsummary: 决策摘要\n---\n正文")
        make_wiki(db, world, "概念页", content="---\ndoc_kind: concept\nsummary: 概念摘要\n---\n正文")
        make_wiki(db, world, "无分类页", content="只有正文,没有 frontmatter")
        make_wiki(db, world, "断链源", content="看 [[哪里都没有的页]]")
        index = svc.project_index(db, world["member"], world["project"].id)
        assert index["total"] == 4
        kinds = [(section["kind"], len(section["items"])) for section in index["sections"]]
        assert ("decision", 1) in kinds
        assert ("concept", 1) in kinds
        assert (None, 2) in kinds  # 无分类页 + 断链源
        decision = index["sections"][0]["items"][0]
        assert decision["summary"] == "决策摘要"
        assert decision["doc_kind"] == "decision"
        assert decision["author"]["username"] == world["admin"].username
        uncategorized = next(s for s in index["sections"] if s["kind"] is None)
        no_kind = next(item for item in uncategorized["items"] if item["title"] == "无分类页")
        assert no_kind["summary"] == "只有正文,没有 frontmatter"
        assert index["lint"]["missing_kind"]
        assert any(item["title"] == "断链源" for item in index["lint"]["missing_kind"])
        assert index["lint"]["broken_links"]
        assert index["lint"]["broken_links"][0]["raw_text"] == "哪里都没有的页"

    def test_index_unknown_kind_own_section(self, db: Session, world: dict):
        make_wiki(db, world, "自定义", content="---\ndoc_kind: 私有形态\nsummary: s\n---\n正文")
        index = svc.project_index(db, world["member"], world["project"].id)
        assert [section["kind"] for section in index["sections"]] == ["私有形态"]

    def test_index_viewer_permission(self, db: Session, world: dict):
        make_wiki(db, world, "任何", content="x")
        svc.project_index(db, world["member"], world["project"].id)  # viewer 可读
        from app.models import Project

        stranger = Project(team_id=world["team"].id, name="stranger-space")
        db.add(stranger)
        db.commit()
        with pytest.raises(AppError):
            svc.project_index(db, world["member"], stranger.id)


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

    def test_move_directory_rejected(self, db: Session, world: dict):
        root = make_wiki(db, world, "根")["id"]
        with pytest.raises(AppError) as e:
            svc.move_document(db, world["admin"], root, parent_id=None, directory_id="DIR-1")
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


class TestDeleteRestoreDocument:
    def test_delete_impact_and_recursive_delete(self, db: Session, world: dict):
        root = make_wiki(db, world, "根")["id"]
        child = make_wiki(db, world, "子", parent_id=root)["id"]
        impact = svc.delete_impact_document(db, world["member"], root)
        assert impact == {"documents": 2}
        svc.delete_document(db, world["admin"], root)
        assert db_scalar_doc(db, root).deleted_at is not None
        assert db_scalar_doc(db, child).deleted_at is not None

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
        assert db_scalar_doc(db, child).deleted_at is None

    def test_restore_conflicts_on_title(self, db: Session, world: dict):
        gone = make_wiki(db, world, "旧页")["id"]
        svc.delete_document(db, world["admin"], gone)
        make_wiki(db, world, "旧页")
        with pytest.raises(AppError) as e:
            svc.restore_document(db, world["admin"], gone)
        assert e.value.code == "conflict"

    def test_deleted_nodes_listing(self, db: Session, world: dict):
        gone = make_wiki(db, world, "回收页")["id"]
        svc.delete_document(db, world["admin"], gone)
        page = svc.list_deleted_nodes(db, world["member"], world["project"].id, "wiki", None, 20)
        assert [item["title"] for item in page["items"]] == ["回收页"]


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

    def test_ancestor_paths(self, db: Session, world: dict):
        root = make_wiki(db, world, "根")["id"]
        child = make_wiki(db, world, "子", parent_id=root)["id"]
        wiki_path = svc.ancestor_path(db, world["member"], world["project"].id, "wiki", "document", child)
        assert [item["title"] for item in wiki_path["items"]] == ["根", "子"]
        with pytest.raises(AppError) as e:
            svc.ancestor_path(db, world["member"], world["project"].id, "wiki", "document", "DOC-999")
        assert e.value.code == "not_found"
        with pytest.raises(AppError) as e:
            svc.ancestor_path(db, world["member"], world["project"].id, "wiki", "directory", root)
        assert e.value.code == "invalid_request"

    def test_ancestor_path_cross_project_document(self, db: Session, world: dict):
        from app.models import Project

        other = Project(team_id=world["team"].id, name="other")
        db.add(other)
        db.commit()
        foreign, _ = svc.create_document(db, world["admin"], other.id, "外部", "wiki", "", {})
        with pytest.raises(AppError) as e:
            svc.ancestor_path(db, world["member"], world["project"].id, "wiki", "document", foreign.code)
        assert e.value.code == "not_found"

    def test_wrong_module_access_hidden(self, db: Session, world: dict):
        page, _ = svc.create_document(db, world["admin"], world["project"].id, "普通页", "wiki", "c", {})
        with pytest.raises(AppError) as e:
            svc.get_document(db, world["member"], page.code, module="glossary")
        assert e.value.code == "not_found"


class TestVersionsAndReferences:
    def test_rollback_document(self, db: Session, world: dict):
        created = make_wiki(db, world, "标题1", content="c1")
        svc.update_document(db, world["admin"], created["id"], title="标题2", content="c2")
        rolled, _ = svc.rollback_document(db, world["admin"], created["id"], 1)
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
        other_doc = make_wiki(db, world, "另一篇")["node"]
        poly_svc.create_reference(db, world["admin"], "document", wiki.code, "document", other_doc.code, "mentions")
        refs = svc.document_references(db, world["member"], wiki.code, "wiki")
        assert refs["count"] == 1
        assert refs["items"][0]["to_id"] == other_doc.code
        other = svc.document_references(db, world["member"], other_doc.code, "wiki")
        assert other["count"] == 1
        assert other["items"][0]["from_id"] == wiki.code


class TestAccessGuards:
    def test_deleted_document_hidden_from_reads(self, db: Session, world: dict):
        gone = make_wiki(db, world, "已删")["id"]
        svc.delete_document(db, world["admin"], gone)
        with pytest.raises(AppError) as e:
            svc.get_document(db, world["member"], gone)
        assert e.value.code == "not_found"
