"""Exercise v1 to v2 migrations with data in the dedicated release-test database."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.security import token_digest
from app.v2.import_legacy_timeline import import_timeline
from app.v2.import_legacy_wiki import import_wiki


def test_v1_to_v2_postgres_rehearsal(monkeypatch):
    url = os.getenv("ZEICHEN_TEST_V2_POSTGRES_URL")
    if not url:
        pytest.skip("Requires disposable PostgreSQL database from deploy/remote_release.py")
    assert make_url(url).database == "zeichen_v2_candidate"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    engine = create_engine(url)
    team, owner, agent, project, key, comment = (uuid4() for _ in range(6))
    try:
        command.upgrade(config, "1007wikimerge")
        records = {"team": team, "owner": owner, "agent": agent, "project": project, "key": key,
                   "comment": comment, "digest": token_digest("fixture-key")}
        with engine.begin() as conn:
            for query in (
                "INSERT INTO team (id,name) VALUES (:team,'fixture')",
                'INSERT INTO "user" (id,username,password_hash,is_agent,is_bootstrap) VALUES (:owner,\'owner\',\'\',false,false)',
                'INSERT INTO "user" (id,username,password_hash,is_agent,is_bootstrap,owner_id) VALUES (:agent,\'bot\',\'\',true,false,:owner)',
                "INSERT INTO api_key (id,user_id,token_hash,token_encrypted) VALUES (:key,:agent,:digest,'legacy')",
                "INSERT INTO project (id,team_id,name) VALUES (:project,:team,'fixture')",
                "INSERT INTO requirement (project_id,code,title,status) VALUES (:project,'REQ-1','Req','backlog')",
                "INSERT INTO comment (id,project_id,target_type,target_id,body,author_id) VALUES (:comment,:project,'requirement','REQ-1','history',:owner)",
                "INSERT INTO document (project_id,code,title,doc_type,content) VALUES (:project,'DOC-1','Wiki','wiki','body')",
            ):
                conn.execute(text(query), records)

        command.upgrade(config, "head")
        with Session(engine) as db, db.begin():
            assert import_timeline(db)[0]["comments_imported"] == 1
            assert import_wiki(db)[0]["documents_imported"] == 1
        with Session(engine) as db, db.begin():
            assert import_timeline(db)[0]["already_imported"] == 1
            assert import_wiki(db)[0]["already_imported"] == 1
            assert db.scalar(text("SELECT token_hash FROM api_key WHERE id = :key"), records) == records["digest"]
            assert db.scalar(text("SELECT authored.body FROM v2_timeline_revision AS authored")) == "history"
        assert "token_encrypted" not in {column["name"] for column in inspect(engine).get_columns("api_key")}
    finally:
        engine.dispose()
        get_settings.cache_clear()
