"""Publish a verified v2 schema change using an upgraded copy of a frozen database."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
from urllib.parse import urlsplit, urlunsplit

from remote_release import IMAGE_ID, V2Release, inspect, run


class SchemaRelease(V2Release):
    def check_target_revision(self):
        if self.target_revision == self.old_revision:
            raise RuntimeError("Use a routine release for the same schema")

    def sql(self, database, query):
        return run(["docker", "exec", "zeichen-postgres-1", "psql", "-XAt", "-v", "ON_ERROR_STOP=1",
                    "-U", self.role, "-d", database, "-c", query], capture=True)

    def ledger(self, database):
        # Compare every project's requirement/task identity, original parent and workflow state.
        task_code = "COALESCE(legacy_code, code)" if self.sql(database, """
            SELECT count(*) FROM information_schema.columns WHERE table_schema='public'
                AND table_name='task' AND column_name='legacy_code'""") == "1" else "code"
        return self.sql(database, f"""
            SELECT md5(COALESCE(string_agg(row_data::text, E'\n' ORDER BY row_data::text), ''))
            FROM (
                SELECT jsonb_build_array('R', project_id, code, status, deleted_at) row_data FROM requirement
                UNION ALL SELECT jsonb_build_array('T', project_id, {task_code}, requirement_id, status,
                                                    assignee_id, deleted_at) FROM task
            ) AS ledger""")

    def prepare_clone(self, dump, phase):
        target = "zeichen_upgrade_" + uuid.uuid4().hex[:16]
        self.record[phase + "_database"] = target
        self.save(phase)
        run(["docker", "exec", "zeichen-postgres-1", "createdb", "-U", self.role, "-T", "template0", target])
        with dump.open("rb") as source:
            subprocess.run(["docker", "exec", "-i", "zeichen-postgres-1", "pg_restore", "--exit-on-error",
                            "-U", self.role, "-d", target], stdin=source, check=True)
        if self.sql(target, "SELECT version_num FROM alembic_version") != self.old_revision:
            raise RuntimeError("Restored snapshot does not match the active schema")
        before = self.ledger(target)
        dsn = urlunsplit(urlsplit(self.dsn)._replace(path="/" + target))
        # Docker inherits the DSN from the environment; no credentials in argv or release evidence.
        run(["docker", "run", "--rm", "--pull=never", "--network", self.network, "-e", "DATABASE_URL",
             "--entrypoint", "alembic", self.backend, "upgrade", "head"],
            env={**self.environment, "DATABASE_URL": dsn})
        if self.sql(target, "SELECT version_num FROM alembic_version") != self.target_revision or self.ledger(target) != before:
            raise RuntimeError("Clone migration changed requirement/task identities, assignment, parent or state")
        self.record[phase + "_work_checksum"] = before
        return target

    def rehearse(self):
        archive = self.directory / "rehearsal.dump"
        with archive.open("wb") as output:
            self.pg("pg_dump", "-Fc", output=output)
        rehearsal = self.prepare_clone(archive, "rehearsal")
        run(["docker", "exec", "zeichen-postgres-1", "dropdb", "-U", self.role, rehearsal])
        self.save("rehearsed")

    def backup(self):
        super().backup()
        target = self.prepare_clone(self.directory / "backup" / "postgres.dump", "frozen_clone")
        if self.ledger(self.database_name) != self.record["frozen_clone_work_checksum"]:
            raise RuntimeError("Work data changed after the writers stopped")
        previous = "zeichen_previous_" + uuid.uuid4().hex[:16]
        self.record["rollback_database"] = previous
        self.save("switching_database_names")
        # Both renames commit together. PostgreSQL refuses to rename an in-use database.
        self.sql("postgres", f'BEGIN; ALTER DATABASE "{self.database_name}" RENAME TO "{previous}"; '
                            f'ALTER DATABASE "{target}" RENAME TO "{self.database_name}"; COMMIT')
        self.save("switched_database")


@contextmanager
def pause_maintenance():
    timer = "zeichen-v2-maintenance.timer"
    service = "zeichen-v2-maintenance.service"
    active = subprocess.run(["systemctl", "is-active", "--quiet", timer]).returncode == 0
    if active:
        run(["sudo", "-n", "systemctl", "stop", timer])
    try:
        if subprocess.run(["systemctl", "is-active", "--quiet", service]).returncode == 0:
            raise RuntimeError("Maintenance is currently executing; retry the release when it completes")
        yield
    finally:
        if active:
            run(["sudo", "-n", "systemctl", "start", timer])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if not re.fullmatch(r"[a-f0-9]{40}", args.commit):
        raise RuntimeError("Invalid candidate commit")
    checks = Path.home() / ".zeichen-checks"
    for report in sorted(checks.glob(f"*-{args.commit[:12]}*/result.json"), reverse=True):
        result = json.loads(report.read_text())
        if result.get("commit") == args.commit and result.get("mode") == "candidate" and result.get("status") == "verified":
            break
    else:
        raise RuntimeError("Run -CheckOnly for this exact commit before migrating")
    args.candidate_source = None
    args.allow_migration = False
    if run(["git", "-C", args.root, "rev-parse", "refs/remotes/origin/develop"], capture=True) != args.commit:
        raise RuntimeError("The candidate must be the published develop commit")
    with (args.root / ".release" / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release = SchemaRelease(args)
        print("Release evidence:", release.directory, flush=True)
        try:
            release.preflight()
            release.backend, release.frontend = result["backend_image"], result["frontend_image"]
            for image in (release.backend, release.frontend):
                if not IMAGE_ID.fullmatch(image) or inspect(image)["Id"] != image:
                    raise RuntimeError("Candidate image identity mismatch")
            head = run(["docker", "run", "--rm", "--network", "none", release.backend, "alembic", "heads"], capture=True)
            if head != result["database_target"] + " (head)":
                raise RuntimeError("Candidate schema does not match its test evidence")
            release.target_revision = result["database_target"]
            release.environment.update(ZEICHEN_BACKEND_IMAGE=release.backend, ZEICHEN_FRONTEND_IMAGE=release.frontend)
            release.record.update(backend_image=release.backend, frontend_image=release.frontend,
                database_target=release.target_revision, candidate_evidence=str(report.resolve()))
            release.configure_release()
            release.rehearse()
            with pause_maintenance():
                release.activate()
            print("RELEASE DEPLOYED:", args.commit, flush=True)
        except BaseException:
            print("Release stopped at", release.record["status"], flush=True)
            raise


if __name__ == "__main__":
    main()
