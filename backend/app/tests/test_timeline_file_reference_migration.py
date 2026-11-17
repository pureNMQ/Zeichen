from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Base, Project, Requirement, Team
from app.v2.timeline_models import TimelineEntry, TimelineFileReference, TimelineRevision


def test_migration_backfills_old_revisions_with_retained_links_and_leaves_bodies_unchanged(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'timeline.db').as_posix()}"
    monkeypatch.setattr(get_settings(), "database_url", url)
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    project, team, entry, file = (uuid4() for _ in range(4))
    scope = {"project_id": project, "requirement_code": "REQ-1"}
    body = f"![kept](/projects/{project}/files/{file})"
    engine = create_engine(url)
    try:
        # Match the v2 schema immediately before this migration. The historical
        # 0914shortcodes migration only rewrites the old work tables on PostgreSQL.
        Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t is not TimelineFileReference.__table__])
        command.stamp(config, "v2worktrash")
        with Session(engine) as db, db.begin():
            db.add_all([Team(id=team, name="Team"), Project(id=project, team_id=team, name="Project"),
                        Requirement(project_id=project, code="REQ-1", title="Requirement")])
            db.flush()
            db.add(TimelineEntry(id=entry, **scope, kind="manual", latest_version=2, occurred_at=datetime.now(UTC)))
            db.flush()
            db.add_all([TimelineRevision(entry_id=entry, **scope, version=1, kind="create", body=body),
                        TimelineRevision(entry_id=entry, **scope, version=2, kind="withdraw")])

        command.upgrade(config, "v2timelinefiles")
        with Session(engine) as db:
            indexed = db.scalars(select(TimelineFileReference)).all()
            assert [(ref.entry_id, ref.version, ref.file_id) for ref in indexed] == [(entry, 1, file)]
            assert db.get(TimelineRevision, (entry, 1)).body == body
            assert db.get(TimelineRevision, (entry, 2)).body is None
        command.downgrade(config, "v2worktrash")
        assert not inspect(engine).has_table("v2_timeline_file_reference")
    finally:
        engine.dispose()
