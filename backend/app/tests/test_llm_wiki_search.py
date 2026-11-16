"""REQ-59 关键词读平面专项:多关键词 AND、命中片段、别名/summary 参与、分页。"""

from sqlalchemy.orm import Session

from app.services import documents as doc_svc
from app.services import search as svc


def seed_pages(db: Session, world: dict) -> dict:
    karpathy, _ = doc_svc.create_document(
        db, world["admin"], world["project"].id, "Karpathy 范式调查",
        "wiki",
        "---\ndoc_kind: research\nsummary: LLM Wiki 范式调查摘要\naliases: [范式调查, Karpathy Wiki]\n---\n"
        "知识在写入时被编译进持久 wiki,而不是每次查询重新推导。",
        {},
    )
    decision, _ = doc_svc.create_document(
        db, world["admin"], world["project"].id, "双链落表裁定",
        "wiki",
        "---\ndoc_kind: decision\nsummary: 保存时解析落表\n---\n"
        "正文提 Karpathy 以验证跨页命中与片段截取。",
        {},
    )
    noise, _ = doc_svc.create_document(
        db, world["admin"], world["project"].id, "无关页面", "wiki", "完全不相干的内容", {}
    )
    return {"karpathy": karpathy.code, "decision": decision.code, "noise": noise.code}


class TestMultiKeyword:
    def test_and_semantics(self, db: Session, world: dict):
        codes = seed_pages(db, world)
        rows = svc.search_documents(db, [world["project"].id], "Karpathy 范式")
        assert {row["id"] for row in rows} == {codes["karpathy"]}
        # 单词命中多页
        rows = svc.search_documents(db, [world["project"].id], "Karpathy")
        assert {row["id"] for row in rows} == {codes["karpathy"], codes["decision"]}

    def test_alias_and_summary_participate(self, db: Session, world: dict):
        codes = seed_pages(db, world)
        rows = svc.search_documents(db, [world["project"].id], "范式调查")
        assert [row["id"] for row in rows] == [codes["karpathy"]]
        rows = svc.search_documents(db, [world["project"].id], "编译 摘要")
        assert [row["id"] for row in rows] == [codes["karpathy"]]

    def test_snippet_from_body_hit(self, db: Session, world: dict):
        seed_pages(db, world)
        rows = svc.search_documents(db, [world["project"].id], "编译")
        assert rows and rows[0]["snippet"] and "编译" in rows[0]["snippet"]
        # frontmatter 不进片段/正文匹配
        rows = svc.search_documents(db, [world["project"].id], "summary")
        assert rows == []

    def test_title_ranks_above_body(self, db: Session, world: dict):
        codes = seed_pages(db, world)
        doc_svc.create_document(
            db, world["admin"], world["project"].id, "正文提及 Karpathy 的页面",
            "wiki", "正文里也有 Karpathy", {},
        )
        rows = svc.search_documents(db, [world["project"].id], "Karpathy")
        assert rows[0]["id"] == codes["karpathy"]  # 标题命中优先

    def test_row_shape_isomorphic_with_index(self, db: Session, world: dict):
        seed_pages(db, world)
        rows = svc.search_documents(db, [world["project"].id], "范式")
        row = rows[0]
        assert {"id", "title", "doc_kind", "summary", "snippet", "updated_at", "score"} <= set(row)

    def test_short_keyword_fallback_contains(self, db: Session, world: dict):
        codes = seed_pages(db, world)
        # 1 字 CJK 短词走包含匹配兜底
        rows = svc.search_documents(db, [world["project"].id], "链")
        assert codes["decision"] in {row["id"] for row in rows}

    def test_paged_project_search(self, db: Session, world: dict):
        seed_pages(db, world)
        page = svc.search_documents_paged(db, world["member"], world["project"].id, "Karpathy")
        assert page["items"] and "next_cursor" in page
        # 检索词为空拒绝
        from app.errors import AppError

        try:
            svc.search_documents_paged(db, world["member"], world["project"].id, "  ")
            raise AssertionError("应拒绝空检索词")
        except AppError as e:
            assert e.code == "invalid_request"
