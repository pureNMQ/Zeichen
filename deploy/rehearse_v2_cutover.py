#!/usr/bin/env python3
"""Exercise v2 preparation with real Docker and synthetic resources only."""

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import time
import uuid
from pathlib import Path

from prepare_v2_cutover import EXTRACT, IMAGE, SOURCE_REVISION, Runner, candidate_record, main as prepare
from remote_release import write_json


LABEL = "zeichen.rehearsal"
PROJECT, USER, TEAM, COMMENT, FILE, AVATAR, BOT, KEY, REVOKED, SUSPENDED, SUSPENDED_KEY, MEMBER, GRANT = [
    str(uuid.UUID(int=number)) for number in range(1, 14)
]
PDF_BYTES = b"%PDF-1.7\nsynthetic cutover rehearsal bytes\n"
AVATAR_BYTES = b"\x89PNG\r\n\x1a\nsynthetic avatar bytes"
FILE_PATH = f"{PROJECT}/{FILE}.bin"
AVATAR_PATH = f"{AVATAR}.png"
FILE_SHA = hashlib.sha256(PDF_BYTES).hexdigest()
AVATAR_SHA = hashlib.sha256(AVATAR_BYTES).hexdigest()
ACTIVE_TOKEN, REVOKED_TOKEN, SUSPENDED_TOKEN = (
    "synthetic-rehearsal-key", "synthetic-revoked-key", "synthetic-suspended-agent-key",
)
KEY_HASH, REVOKED_HASH, SUSPENDED_HASH = (
    hashlib.sha256(token.encode()).hexdigest() for token in (ACTIVE_TOKEN, REVOKED_TOKEN, SUSPENDED_TOKEN)
)
TIMELINE_BODY = "synthetic history survives cutover"
WIKI_BODY = "synthetic knowledge survives cutover"

SEED = f"""
INSERT INTO team (id,name) VALUES ('{TEAM}','Synthetic');
INSERT INTO "user" (id,username,password_hash,is_agent,is_bootstrap)
VALUES ('{USER}','fixture-owner','',false,false);
INSERT INTO "user" (id,username,password_hash,is_agent,is_bootstrap,owner_id)
VALUES ('{BOT}','fixture-bot','',true,false,'{USER}');
INSERT INTO "user" (id,username,password_hash,is_agent,is_bootstrap,owner_id,deleted_at)
VALUES ('{SUSPENDED}','fixture-suspended','',true,false,'{USER}',now());
INSERT INTO api_key (id,user_id,token_hash,token_encrypted,revoked_at)
VALUES ('{KEY}','{BOT}','{KEY_HASH}','synthetic-legacy-ciphertext',NULL),
       ('{REVOKED}','{BOT}','{REVOKED_HASH}','synthetic-revoked-ciphertext',now()),
       ('{SUSPENDED_KEY}','{SUSPENDED}','{SUSPENDED_HASH}','synthetic-suspended-ciphertext',NULL);
INSERT INTO workspace_member (id,team_id,user_id,role) VALUES ('{MEMBER}','{TEAM}','{USER}','member');
INSERT INTO project (id,team_id,name) VALUES ('{PROJECT}','{TEAM}','Synthetic');
INSERT INTO project_member (id,project_id,user_id,role) VALUES ('{GRANT}','{PROJECT}','{USER}','editor');
INSERT INTO requirement (project_id,code,title,status)
VALUES ('{PROJECT}','REQ-1','Synthetic requirement','backlog');
INSERT INTO comment (id,project_id,target_type,target_id,body,author_id)
VALUES ('{COMMENT}','{PROJECT}','requirement','REQ-1','{TIMELINE_BODY}','{USER}');
INSERT INTO document (project_id,code,title,doc_type,content,created_by)
VALUES ('{PROJECT}','DOC-1','Synthetic Wiki','wiki','{WIKI_BODY}','{USER}');
INSERT INTO attachment (id,project_id,target_type,target_id,file_name,size,storage_path,created_by)
VALUES ('{FILE}','{PROJECT}','requirement','REQ-1','fixture.pdf',{len(PDF_BYTES)},'legacy-offset-path','{USER}'),
       ('{AVATAR}',NULL,'user','{USER}','avatar.png',{len(AVATAR_BYTES)},'storage/attachments/{AVATAR_PATH}','{USER}');
UPDATE "user" SET avatar='{AVATAR}' WHERE id='{USER}';
"""

ARCHIVE = """
import sys
import tarfile
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
    archive.add("/fixture", arcname=".")
"""
HASHES = """
import hashlib
import json
import sys
from pathlib import Path
root = Path("/fixture")
print(json.dumps({name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sys.argv[1:]}))
"""

VERIFY_AUTH = """
import asyncio
import json
import os
import sys
from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.engine import make_url

from app.db import SessionLocal
from app.errors import AppError
from app.mcp_server.auth import ApiKeyTokenVerifier
from app.models import ProjectMember
from app.services.permissions import get_accessible_project, get_project_role

database, raw_project, raw_owner, raw_agent, key_id, active, revoked, suspended = sys.argv[1:]
assert database.startswith("zeichen_v2_rehearsal_") and make_url(os.environ["DATABASE_URL"]).database == database
project, owner, agent = map(UUID, (raw_project, raw_owner, raw_agent))

async def check_tokens():
    verifier = ApiKeyTokenVerifier()
    token = await verifier.verify_token(active)
    assert token is not None and token.subject == str(agent) and token.client_id == key_id
    assert await verifier.verify_token(revoked) is None
    assert await verifier.verify_token(suspended) is None

asyncio.run(check_tokens())
with SessionLocal() as db:
    membership = (ProjectMember.project_id == project, ProjectMember.user_id == owner)
    assert get_project_role(db, agent, project) == "editor"
    db.execute(update(ProjectMember).where(*membership).values(role="viewer"))
    assert get_project_role(db, agent, project) == "viewer"
    try:
        get_accessible_project(db, agent, project, min_level="editor")
    except AppError as exc:
        assert exc.code == "permission_denied"
    else:
        raise AssertionError("demoted owner still grants write access to its agent")
    db.execute(delete(ProjectMember).where(*membership))
    try:
        get_accessible_project(db, agent, project)
    except AppError as exc:
        assert exc.code == "not_found"
    else:
        raise AssertionError("revoked membership still grants agent project access")
    db.rollback()
print(json.dumps({"active_key": "accepted", "revoked_key": "rejected",
                  "suspended_agent": "rejected", "owner_permissions": "inherited_and_rechecked"}))
"""


class Rehearsal:
    def __init__(self, args, log):
        self.args = args
        self.log = log
        self.run = Runner(log)
        self.token = uuid.uuid4().hex
        self.name = "zeichen-v2-rehearsal-" + self.token
        self.network = self.name + "-net"
        self.database = self.name + "-pg"
        self.source_volume = self.name + "-source"
        self.target = "zeichen_v2_rehearsal_" + self.token[:16]
        self.evidence = args.output / "preparation"
        self.snapshot = args.output / "synthetic-snapshot"
        self.phase = "validate_candidate"
        self.record = {
            "mode": "synthetic_only", "target": self.target, "cleanup_failures": [], "removed_resources": [],
            "synthetic_resources": {
                "network": self.network, "postgres_container": self.database, "source_volume": self.source_volume,
            },
        }
        self.owned: list[tuple[str, str, str, str]] = []

    def check_label(self, kind, name, key, token) -> None:
        query = f'{{{{index .{"Config." if kind == "container" else ""}Labels "{key}"}}}}'
        actual = self.run.docker(kind, "inspect", "--format", query, name, capture=True)
        if actual != token:
            raise RuntimeError("resource does not have the current rehearsal label")

    def claim_synthetic(self, kind, name) -> None:
        self.check_label(kind, name, LABEL, self.token)
        self.owned.append((kind, name, LABEL, self.token))

    def cleanup(self) -> None:
        manifest = self.evidence / "prepared.json"
        if manifest.is_file():
            try:
                prepared = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.record["cleanup_failures"].append({"kind": "manifest", "name": str(manifest)})
                prepared = {}
            token = prepared.get("volume_owner_token", "")
            if prepared.get("target_database") == self.target and re.fullmatch(r"[0-9a-f]{32}", token):
                names = {f"{self.target}_files_{token[:10]}", f"{self.target}_legacy_ro_{token[:10]}"}
                for resource in prepared.get("created_resources", []):
                    if resource.get("volume") in names:
                        self.owned.append(("volume", resource["volume"], "zeichen.cutover", token))
        for kind, name, label, token in reversed(self.owned):
            try:
                self.check_label(kind, name, label, token)
                options = ("--force",) if kind == "container" else ()
                self.run.docker(kind, "rm", *options, name)
                self.record["removed_resources"].append({"kind": kind, "name": name})
            except (RuntimeError, OSError, subprocess.SubprocessError):
                self.record["cleanup_failures"].append({"kind": kind, "name": name})

    def write_capture(self, path: Path, *args) -> None:
        with path.open("xb") as output:
            subprocess.run(["docker", *args], stdout=output, stderr=self.log,
                           stdin=subprocess.DEVNULL, check=True)

    def psql(self, database, sql) -> str:
        if database not in {"zeichen", self.target}:
            raise ValueError("outside synthetic database scope")
        return self.run.docker(
            "exec", self.database, "psql", "-X", "-v", "ON_ERROR_STOP=1",
            "-At", "-U", "zeichen", "-d", database, "-c", sql, capture=True,
        )

    def file_hashes(self, volume, *names) -> dict:
        response = self.run.docker(
            "run", "--rm", "--pull=never", "--network", "none",
            "--mount", f"type=volume,src={volume},dst=/fixture,readonly",
            "--entrypoint", "python", self.backend, "-c", HASHES, *names, capture=True,
        )
        return json.loads(response)

    def legacy_state(self) -> str:
        return self.psql("zeichen", f"""
SELECT version_num FROM alembic_version;
SELECT token_hash || ':' || token_encrypted FROM api_key WHERE id='{KEY}';
SELECT count(*) FROM api_key WHERE id='{REVOKED}' AND revoked_at IS NOT NULL;
SELECT role FROM project_member WHERE id='{GRANT}';
SELECT body FROM comment WHERE id='{COMMENT}';
SELECT content FROM document WHERE code='DOC-1';
SELECT file_name || ':' || storage_path FROM attachment WHERE id='{FILE}';
SELECT avatar::text FROM "user" WHERE id='{USER}';
SELECT (to_regclass('public.v2_project_file') IS NULL)::text;
""")

    def build_fixture(self) -> None:
        self.phase = "create_synthetic_resources"
        image = self.run.docker("image", "inspect", "--format", "{{.Id}}", self.args.postgres_image, capture=True)
        if not IMAGE.fullmatch(image):
            raise RuntimeError("cached PostgreSQL image is required")
        self.run.docker("network", "create", "--internal", "--label", f"{LABEL}={self.token}", self.network)
        self.claim_synthetic("network", self.network)
        password = "fixture-" + self.token
        self.dsn = f"postgresql+psycopg://zeichen:{password}@postgres/zeichen"
        self.run.docker(
            "run", "-d", "--pull=never", "--name", self.database, "--label", f"{LABEL}={self.token}",
            "--network", self.network, "--network-alias", "postgres",
            "--tmpfs", "/var/lib/postgresql/data", "--memory", "512m",
            "-e", f"POSTGRES_PASSWORD={password}", "-e", "POSTGRES_USER=zeichen", "-e", "POSTGRES_DB=zeichen",
            image,
        )
        self.claim_synthetic("container", self.database)
        for _ in range(60):
            try:
                self.run.docker("exec", self.database, "pg_isready", "-h", "127.0.0.1", "-U", "zeichen", "-d", "zeichen")
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
        else:
            raise RuntimeError("synthetic PostgreSQL did not start")
        self.run.docker(
            "run", "--rm", "--pull=never", "--network", self.network, "-e", f"DATABASE_URL={self.dsn}",
            "--entrypoint", "alembic", self.backend, "upgrade", SOURCE_REVISION,
        )
        self.psql("zeichen", SEED)
        self.run.docker("volume", "create", "--label", f"{LABEL}={self.token}", self.source_volume)
        self.claim_synthetic("volume", self.source_volume)
        fixture_tar = self.args.output / "attachments.seed.tar.gz"
        with tarfile.open(fixture_tar, "x:gz") as archive:
            for name, contents in ((FILE_PATH, PDF_BYTES), (AVATAR_PATH, AVATAR_BYTES)):
                member = tarfile.TarInfo(name)
                member.size = len(contents)
                archive.addfile(member, io.BytesIO(contents))
        self.run.docker(
            "run", "--rm", "-i", "--pull=never", "--network", "none",
            "--mount", f"type=volume,src={self.source_volume},dst=/fixture",
            "--entrypoint", "python", self.backend, "-c", EXTRACT, "/fixture", source=fixture_tar,
        )

    def capture_snapshot(self) -> None:
        self.phase = "capture_frozen_synthetic_snapshot"
        self.snapshot.mkdir(mode=0o700)
        self.write_capture(self.snapshot / "postgres.dump",
                           "exec", self.database, "pg_dump", "-Fc", "-U", "zeichen", "-d", "zeichen")
        self.write_capture(
            self.snapshot / "attachments.tar.gz", "run", "--rm", "--pull=never", "--network", "none",
            "--mount", f"type=volume,src={self.source_volume},dst=/fixture,readonly",
            "--entrypoint", "python", self.backend, "-c", ARCHIVE,
        )
        fixture_service = {
            "image": self.backend, "environment": {"DATABASE_URL": self.dsn},
            "volumes": ["attachments:/srv/zeichen/storage/attachments"],
        }
        write_json(self.snapshot / "compose.json", {
            "services": {service: fixture_service for service in ("api", "mcp", "frontend", "worker")},
            "volumes": {"attachments": {"external": True, "name": self.source_volume}},
            "networks": {"default": {"external": True, "name": self.network}},
        })
        ingress = self.args.candidate.parent / "source" / "deploy" / "nginx.conf"
        (self.snapshot / "nginx.conf").write_bytes(ingress.read_bytes())

    def verify(self, source_state: str) -> None:
        self.phase = "verify_source_and_clone"
        if not source_state.startswith(SOURCE_REVISION + "\n") or self.legacy_state() != source_state:
            raise RuntimeError("legacy source rows or schema changed")
        if self.file_hashes(self.source_volume, FILE_PATH, AVATAR_PATH) != {FILE_PATH: FILE_SHA, AVATAR_PATH: AVATAR_SHA}:
            raise RuntimeError("legacy source file bytes changed")
        prepared = json.loads((self.evidence / "prepared.json").read_text(encoding="utf-8"))
        target_volume = prepared["target_attachment_volume"]
        self.check_label("volume", target_volume, "zeichen.cutover", prepared["volume_owner_token"])
        v2_path = "library-v2/" + FILE_PATH
        if self.file_hashes(target_volume, v2_path, FILE_PATH, AVATAR_PATH) != {
            v2_path: FILE_SHA, FILE_PATH: FILE_SHA, AVATAR_PATH: AVATAR_SHA,
        }:
            raise RuntimeError("clone file layout or bytes do not match the fixture")
        target = self.psql(self.target, f"""
SELECT version_num FROM alembic_version;
SELECT token_hash FROM api_key WHERE id='{KEY}';
SELECT body FROM v2_timeline_revision WHERE entry_id='{COMMENT}' AND version=1;
SELECT body FROM v2_wiki WHERE project_id='{PROJECT}' AND code='DOC-1';
SELECT sha256 || ':' || media_type FROM v2_project_file WHERE project_id='{PROJECT}' AND id='{FILE}';
SELECT target_kind || ':' || target_id FROM v2_file_association WHERE project_id='{PROJECT}' AND file_id='{FILE}';
SELECT count(*) FROM v2_notification;
SELECT count(*) FROM information_schema.columns
WHERE table_schema='public' AND table_name='api_key' AND column_name='token_encrypted';
""")
        expected = [
            self.candidate["database_target"], KEY_HASH, TIMELINE_BODY, WIKI_BODY, FILE_SHA + ":application/pdf",
            "requirements:REQ-1", "0", "0",
        ]
        if target.splitlines() != expected:
            raise RuntimeError("clone preserved rows do not match the synthetic fixture")
        self.phase = "verify_legacy_authentication"
        auth = self.run.docker(
            "run", "--rm", "--pull=never", "--network", self.network, "--env-file",
            str(self.evidence / "database.env"), "--entrypoint", "python", self.backend, "-c", VERIFY_AUTH,
            self.target, PROJECT, USER, BOT, KEY, ACTIVE_TOKEN, REVOKED_TOKEN, SUSPENDED_TOKEN, capture=True,
        )
        auth_report = json.loads(auth)
        if auth_report != {"active_key": "accepted", "revoked_key": "rejected", "suspended_agent": "rejected",
                            "owner_permissions": "inherited_and_rechecked"} or self.legacy_state() != source_state:
            raise RuntimeError("synthetic credential or permission rehearsal failed")
        self.record["authentication"] = auth_report
        self.record["verified"] = ["v1 schema, records and bytes intact", "v2 timeline, Wiki and file rows",
                                   "v2 file hashes and legacy avatar fallback", "Key digest retained without reread data",
                                   "no historical notifications emitted", "legacy Key and owner permission behavior"]

    def execute(self) -> None:
        self.candidate = candidate_record(self.args.candidate)
        self.backend = self.candidate["backend_image"]
        if self.run.docker("image", "inspect", "--format", "{{.Id}}", self.backend, capture=True) != self.backend:
            raise RuntimeError("candidate image is unavailable")
        self.record["candidate_commit"] = self.candidate["commit"]
        self.build_fixture()
        source_state = self.legacy_state()
        self.capture_snapshot()
        self.phase = "prepare_v2"
        result = prepare([
            "--snapshot", str(self.snapshot), "--candidate", str(self.args.candidate),
            "--output", str(self.evidence), "--postgres", self.database, "--network", self.network,
            "--target", self.target, "--snapshot-writes-frozen",
        ])
        if result != 0:
            raise RuntimeError("v2 preparation failed")
        self.verify(source_state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--postgres-image", default="postgres:16-alpine", help="Cached local PostgreSQL image")
    args = parser.parse_args()
    os.umask(0o077)
    args.candidate = args.candidate.resolve(strict=True)
    args.output = args.output.resolve()
    args.output.mkdir(mode=0o700)
    with (args.output / "rehearsal.log").open("xb") as log:
        exercise = Rehearsal(args, log)
        try:
            exercise.execute()
            exercise.record["status"] = "verified"
        except Exception as error:
            exercise.record.update(status="failed", phase=exercise.phase, error_type=type(error).__name__)
        finally:
            exercise.cleanup()
            if exercise.record["cleanup_failures"] and exercise.record["status"] == "verified":
                exercise.record["status"] = "cleanup_failed"
            write_json(args.output / "rehearsal.json", exercise.record)
    print(f'{exercise.record["status"]}: {args.output / "rehearsal.json"}')
    return int(exercise.record["status"] != "verified")


if __name__ == "__main__":
    raise SystemExit(main())
