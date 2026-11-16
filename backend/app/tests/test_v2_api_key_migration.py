import asyncio
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.mcp_server import auth
from app.models import ApiKey, Base, User
from app.security import token_digest


def test_migration_authenticates_old_active_key_and_preserves_revocation(monkeypatch):
    path = Path(__file__).parents[2] / "alembic/versions/v2keyonce.py"
    spec = importlib.util.spec_from_file_location("v2keyonce", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[User.__table__, ApiKey.__table__])
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)

    with sessions.begin() as db:
        owner = User(username="migration-owner", password_hash="")
        db.add(owner)
        db.flush()
        agent = User(username="migration-agent", is_agent=True, owner_id=owner.id, password_hash="")
        db.add(agent)
        db.flush()
        db.add_all([
            ApiKey(user_id=agent.id, token_hash=token_digest("legacy-active")),
            ApiKey(user_id=agent.id, token_hash=token_digest("legacy-revoked"),
                   revoked_at=datetime.now(timezone.utc)),
        ])

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE api_key ADD COLUMN token_encrypted TEXT NOT NULL DEFAULT 'legacy'"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert "token_encrypted" not in {c["name"] for c in inspect(conn).get_columns("api_key")}

    verifier = auth.ApiKeyTokenVerifier()
    assert asyncio.run(verifier.verify_token("legacy-active")) is not None
    assert asyncio.run(verifier.verify_token("legacy-revoked")) is None
    engine.dispose()
