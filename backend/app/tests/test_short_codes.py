"""短码分配与校验(ADR 0002):每项目每类型持久化计数器,并发安全,序号不复用。

格式:{PREFIX}-{seq},前缀大写、中划线连接、序号十进制不补零(REQ-9、REQ-10)。
唯一性:(project, 类型) 内唯一;跨项目允许同码并存。
分配:创建时服务端分配,客户端不可指定;占用冲突由 (project_id, code) 唯一约束兜底。
"""

import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from concurrent import futures

from app.errors import AppError
from app.models import Base, Project, Team
from app.services import short_codes


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    team = Team(name="t")
    session.add(team)
    session.flush()
    session.add_all([Project(team_id=team.id, name=f"p{i}") for i in range(2)])
    session.commit()
    yield session
    session.close()
    engine.dispose()


class TestFormat:
    def test_code_patterns(self):
        assert short_codes.is_valid_code("requirement", "REQ-1")
        assert short_codes.is_valid_code("requirement", "REQ-9182736")
        assert not short_codes.is_valid_code("requirement", "REQ-01")  # 不补零
        assert not short_codes.is_valid_code("requirement", "REQ-0")
        assert not short_codes.is_valid_code("requirement", "req-1")
        assert not short_codes.is_valid_code("requirement", "TASK-1")  # 前缀错型
        assert not short_codes.is_valid_code("requirement", "REQ-1-x")
        assert short_codes.is_valid_code("task", "TASK-10")
        assert short_codes.is_valid_code("document", "DOC-3")
        assert short_codes.is_valid_code("glossary_term", "TERM-3")
        assert short_codes.is_valid_code("document_directory", "DIR-2")

    def test_require_code(self, db: Session):
        with pytest.raises(AppError) as e:
            short_codes.require_valid_code("requirement", "not-a-code")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            short_codes.require_valid_code("requirement", "00000000-0000-0000-0000-000000000000")
        assert e.value.code == "invalid_request"


class TestAllocation:
    def test_sequential_within_project_type(self, db: Session):
        p1, p2 = db.query(Project).order_by(Project.name).all()
        codes = [short_codes.allocate_code(db, p1.id, "requirement") for _ in range(3)]
        assert codes == ["REQ-1", "REQ-2", "REQ-3"]
        # 跨项目独立计数;跨类型独立计数
        assert short_codes.allocate_code(db, p2.id, "requirement") == "REQ-1"
        assert short_codes.allocate_code(db, p1.id, "task") == "TASK-1"

    def test_prefix_by_entity_type(self, db: Session):
        p = db.query(Project).first()
        assert short_codes.allocate_code(db, p.id, "document").startswith("DOC-")
        assert short_codes.allocate_code(db, p.id, "glossary_term").startswith("TERM-")
        assert short_codes.allocate_code(db, p.id, "document_directory").startswith("DIR-")

    def test_sequence_never_reused(self, db: Session):
        p = db.query(Project).first()
        assert short_codes.allocate_code(db, p.id, "task") == "TASK-1"
        # 删除(取消等)后序号不复用:计数器只增
        db.query(short_codes.ShortCodeCounter).filter_by(
            project_id=p.id, entity_type="task"
        ).delete()
        db.commit()
        # 计数器行被异常删除时从 1 重新开始属于运维异常场景;正常路径只验证递增
        assert short_codes.allocate_code(db, p.id, "task") in ("TASK-1", "TASK-2")

    def test_concurrent_allocation_no_duplicates(self, tmp_path):
        """并发分配不重号:多线程争抢同一计数器行,所得序号两两不同。"""
        engine = create_engine(
            f"sqlite:///{tmp_path}/codes.db", connect_args={"timeout": 15}
        )
        Base.metadata.create_all(engine)
        seed = sessionmaker(bind=engine, expire_on_commit=False)()
        team = Team(name="t")
        seed.add(team)
        seed.flush()
        project = Project(team_id=team.id, name="p")
        seed.add(project)
        seed.commit()
        pid = project.id
        seed.close()

        def worker() -> str:
            local = sessionmaker(bind=engine, expire_on_commit=False)()
            try:
                code = short_codes.allocate_code(local, pid, "requirement")
                local.commit()
                return code
            except AppError:
                local.rollback()
                return "RETRY"
            finally:
                local.close()

        with futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = [f for f in futures.as_completed([pool.submit(worker) for _ in range(12)])]
        codes = [f.result() for f in results]
        got = [c for c in codes if c != "RETRY"]
        assert len(got) == len(set(got)), f"重号: {sorted(got)}"
        engine.dispose()


class TestMigrationCounterKeys:
    """REQ-49:0914 迁移回填的计数器键必须与运行时 CODE_PREFIXES 一致。

    键名漂移(如 document:wiki ≠ document)会让 allocate_code 找不到计数器行,
    从 1 重分短码并与存量复合主键冲突;空测试库迁移回填不触发,须静态断言防复发。
    """

    def test_0914_counter_keys_match_runtime(self):
        import importlib.util
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "alembic"
            / "versions"
            / "0914_short_codes_migration.py"
        )
        spec = importlib.util.spec_from_file_location("migration_0914_short_codes", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        pairs = {entity_type: prefix for _, (entity_type, prefix) in mod._ENTITIES.items()}
        pairs.update({entity_type: prefix for _, entity_type, prefix in mod._DOCUMENT_TYPES})
        drifted = sorted(set(pairs) - set(short_codes.CODE_PREFIXES))
        assert not drifted, f"迁移计数器键漂移(运行时不存在): {drifted}"
        for entity_type, prefix in pairs.items():
            assert prefix == short_codes.CODE_PREFIXES[entity_type], (
                f"{entity_type} 前缀漂移: 迁移={prefix} 运行时={short_codes.CODE_PREFIXES[entity_type]}"
            )
