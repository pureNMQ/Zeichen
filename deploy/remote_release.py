#!/usr/bin/env python3
"""Remote-only release runner. No production credentials enter test containers.

Invoked by deploy.ps1 from a Git archive, never from the live source mount.
State/backups are private; nothing automatically deletes volumes or downgrades DBs.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request


SERVICES = ("api", "mcp", "worker", "frontend")
ENVIRONMENT_OVERRIDES = ("deploy/docker-compose.ip.yml", "/srv/site/compose.override.yml")


def run(args, *, capture=False, env=None, cwd=None, output=None):
    args = [str(a) for a in args]
    if capture:
        return subprocess.check_output(args, text=True, env=env, cwd=cwd).strip()
    print("+ " + " ".join(args), flush=True)
    subprocess.run(args, check=True, env=env, cwd=cwd, stdout=output)


def inspect(name):
    return json.loads(run(["docker", "inspect", name], capture=True))[0]


def worktree_changes(root):
    # The first run creates state before the updated .gitignore is installed.
    return run(["git", "status", "--porcelain", "--", ".", ":(exclude).release"], capture=True, cwd=root)


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def http_get(url):
    with urllib.request.urlopen(url, timeout=15) as response:
        return response.read()


def protect_ingress(old, new):
    """Only the Zeichen TLS block may change; preserve Mochi, ACME and fallback."""
    marker = "# ---------- 贼船 Zeichen ----------"
    tail = "# ---------- 兜底:"
    if old.count(marker) != 1 or new.count(marker) != 1:
        raise RuntimeError("Unrecognized shared ingress layout")
    old_prefix, old_body = old.split(marker)
    new_prefix, new_body = new.split(marker)
    if tail not in old_body or tail not in new_body:
        raise RuntimeError("Missing fallback block")
    if old_prefix != new_prefix or old_body.split(tail)[1] != new_body.split(tail)[1]:
        raise RuntimeError("Refusing to modify MochiSite, HTTP/ACME or shared fallback config")


def validate_release_config(config):
    for name in SERVICES:
        service = config["services"][name]
        command = service.get("command") or []
        if "--reload" in command or any(v.get("type") == "bind" for v in (service.get("volumes") or [])):
            raise RuntimeError(f"{name}: release must not mount source or use reload")
        if service.get("ports"):
            raise RuntimeError(f"{name}: application ports must remain private")


def sync_repository(root, revision, expected_head):
    # nginx.conf is a read-only single-file bind mount in the shared gateway.
    # Git checkout would replace its inode. It has already been written IN PLACE.
    run(["git", "restore", f"--source={revision}", "--staged", "--worktree", "--",
         ".", ":(exclude)deploy/nginx.conf"], cwd=root)
    run(["git", "restore", f"--source={revision}", "--staged", "--", "deploy/nginx.conf"], cwd=root)
    run(["git", "update-ref", "-m", "remote release", "refs/heads/develop", revision, expected_head], cwd=root)


def wait_healthy(name, timeout=150):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = inspect(name)["State"]
        if state.get("Status") == "running" and state.get("Health", {}).get("Status", "healthy") == "healthy":
            return
        time.sleep(3)
    raise RuntimeError(f"{name} failed its health check")


class Release:
    def __init__(self, args):
        self.args = args
        self.root = args.root.resolve()
        self.candidate = args.candidate_source is not None
        self.state = self.root if self.candidate else self.root / ".release"
        self.state.mkdir(mode=0o700, exist_ok=True)
        self.state.chmod(0o700)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = f"-{time.time_ns()}" if self.candidate else ""
        self.directory = self.state / f"{stamp}-{args.commit[:12]}{suffix}"
        self.directory.mkdir(mode=0o700)
        self.source = self.directory / "source"
        source = args.candidate_source if self.candidate else Path(__file__).resolve().parent.parent
        shutil.copytree(source, self.source, symlinks=True)
        self.environment = os.environ.copy()
        self.image_prefix = "zeichen-check" if self.candidate else "zeichen-release"
        self.backend = f"{self.image_prefix}-backend:{args.commit}"
        self.frontend = f"{self.image_prefix}-frontend:{args.commit}"
        self.record = {"commit": args.commit, "started_utc": stamp, "status": "checking",
                       "mode": "candidate" if self.candidate else "release"}

    def save(self, status):
        self.record["status"] = status
        write_json(self.directory / "result.json", self.record)

    def compose(self, files):
        cmd = ["docker", "compose", "--project-directory", self.root,
               "--env-file", self.root / ".env", "-p", "zeichen"]
        for path in files:
            cmd += ["-f", path]
        return cmd

    def db_revision(self):
        return run(["docker", "exec", "zeichen-postgres-1", "psql", "-U", "zeichen",
                    "-d", "zeichen", "-Atc", "SELECT version_num FROM alembic_version"], capture=True)

    def counts(self):
        tables = ("user", "project", "requirement", "task", "document", "attachment")
        sql = " UNION ALL ".join(f'SELECT \'{t}\', count(*) FROM "{t}"' for t in tables)
        return run(["docker", "exec", "zeichen-postgres-1", "psql", "-U", "zeichen",
                    "-d", "zeichen", "-Atc", sql], capture=True)

    def preflight(self):
        if worktree_changes(self.root):
            raise RuntimeError("Server worktree is dirty; preserve its changes before deploying")
        if run(["git", "branch", "--show-current"], capture=True, cwd=self.root) != "develop":
            raise RuntimeError("Server must be on develop")
        self.old_head = run(["git", "rev-parse", "HEAD"], capture=True, cwd=self.root)
        run(["git", "merge-base", "--is-ancestor", self.old_head, self.args.commit], cwd=self.root)
        if shutil.disk_usage(self.root).free < 5 * 1024**3:
            raise RuntimeError("At least 5 GiB free disk required")
        self.gateway = inspect("zeichen-web-1")
        self.database = inspect("zeichen-postgres-1")
        self.old_nginx = (self.root / "deploy/nginx.conf").read_text()
        self.new_nginx = (self.source / "deploy/nginx.conf").read_text()
        protect_ingress(self.old_nginx, self.new_nginx)
        self.mochi_hash = digest(http_get("https://mochigm.cn/"))
        self.old_revision = self.db_revision()
        self.record.update(previous_commit=self.old_head, database_before=self.old_revision,
                           counts_before=self.counts(), mochi_home_sha256=self.mochi_hash,
                           gateway_id=self.gateway["Id"], postgres_id=self.database["Id"])
        self.save("checking")

    def build_and_test(self):
        if not self.candidate:
            run([sys.executable, "-m", "unittest", "discover", "-s", self.source / "deploy/tests"])
        for component in ("backend", "frontend"):
            image = f"{self.image_prefix}-{component}-test:{self.args.commit}"
            dockerfile = self.source / f"deploy/Dockerfile.release-{component}"
            if not dockerfile.resolve().is_relative_to(self.source):
                raise RuntimeError(f"{component}: Dockerfile must be inside the source archive")
            run(["docker", "build", "--target", "test", "-t", image, "-f", dockerfile, self.source])
            run(["docker", "run", "--rm", "--network", "none", "--cpus", "1",
                 "--memory", "1536m", image])
            if component == "backend":
                if self.candidate:
                    run(["docker", "run", "--rm", "--network", "none", "--cpus", "1",
                         "--memory", "512m", image, "python", "-m", "unittest", "discover",
                         "-s", "/workspace/deploy/tests"])
                self.test_migration(image)
            target = self.backend if component == "backend" else self.frontend
            run(["docker", "build", "--target", "runtime", "-t", target, "-f", dockerfile, self.source])
        # Use immutable IDs, not mutable tags, from here onward.
        self.backend = inspect(self.backend)["Id"]
        self.frontend = inspect(self.frontend)["Id"]
        self.environment.update(ZEICHEN_BACKEND_IMAGE=self.backend, ZEICHEN_FRONTEND_IMAGE=self.frontend)
        heads = run(["docker", "run", "--rm", "--network", "none", self.backend,
                     "alembic", "heads"], capture=True)
        if len(heads.splitlines()) != 1:
            raise RuntimeError("Expected one Alembic head")
        self.target_revision = heads.split()[0]
        self.record.update(backend_image=self.backend, frontend_image=self.frontend,
                           database_target=self.target_revision)
        if self.candidate:
            self.save("verified")
            return
        if self.target_revision != self.old_revision and not self.args.allow_migration:
            raise RuntimeError(f"Migration {self.old_revision} -> {self.target_revision} requires -AllowMigration")
        self.files = [self.source / "docker-compose.yml", self.source / "deploy/docker-compose.prod.yml"]
        self.files += [self.root / p for p in ENVIRONMENT_OVERRIDES if (self.root / p).exists()]
        self.files += [self.source / "deploy/docker-compose.release.yml"]
        self.command = self.compose(self.files)
        config = json.loads(run(self.command + ["config", "--format", "json"], capture=True, env=self.environment))
        validate_release_config(config)
        # Store resolved, private configuration with pinned images for recovery.
        for service in config["services"].values():
            service.pop("build", None)
        write_json(self.directory / "compose.json", config)
        self.save("verified")

    def test_migration(self, image):
        # Disposable Postgres on a separate INTERNAL network. No production
        # credentials, volumes or networks are passed to either test container.
        name = "zeichen-verify-" + digest(self.directory.name.encode())[:24]
        run(["docker", "network", "create", "--internal", name])
        try:
            run(["docker", "run", "-d", "--name", name, "--network", name,
                 "--memory", "256m", "--tmpfs", "/var/lib/postgresql/data",
                 "-e", "POSTGRES_PASSWORD=release-test-only", "-e", "POSTGRES_DB=zeichen", "postgres:16-alpine"])
            for attempt in range(30):
                ready = subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1",
                                        "-U", "postgres", "-d", "zeichen"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Disposable migration database did not start")
            run(["docker", "run", "--rm", "--network", name, "--memory", "1024m", "--cpus", "1",
                 "-e", f"ZEICHEN_TEST_POSTGRES_URL=postgresql+psycopg://postgres:release-test-only@{name}/zeichen",
                 image, "python", "-m", "pytest", "app/tests/test_wiki_merge_migration.py"])
            run(["docker", "exec", name, "createdb", "-U", "postgres", "zeichen_v2_candidate"])
            run(["docker", "run", "--rm", "--network", name, "--memory", "1024m", "--cpus", "1",
                 "-e", f"ZEICHEN_TEST_V2_POSTGRES_URL=postgresql+psycopg://postgres:release-test-only@{name}/zeichen_v2_candidate",
                 image, "python", "-m", "pytest", "app/tests/test_v2_postgres_rehearsal.py"])
        finally:
            subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL)
            subprocess.run(["docker", "network", "rm", name], stdout=subprocess.DEVNULL)

    def backup(self):
        backup = self.directory / "backup"
        backup.mkdir(mode=0o700)
        old_files = self.gateway["Config"]["Labels"]["com.docker.compose.project.config_files"].split(",")
        # After the first release, the gateway labels still describe the original
        # ingress stack. Use the last successful app config for subsequent rollback.
        current = self.state / "current.json"
        if current.exists():
            previous = json.loads(current.read_text())
            config = json.loads(Path(previous["compose_file"]).read_text())
        else:
            config = json.loads(run(self.compose(old_files) + ["config", "--format", "json"], capture=True))
        self.previous_services = []
        for name in SERVICES:
            found = run(["docker", "ps", "-aq", "--filter", f"name=^/zeichen-{name}-1$"], capture=True)
            if found:
                actual = inspect(found)
                config["services"][name]["image"] = actual["Image"]
                config["services"][name]["command"] = actual["Config"]["Cmd"]
                self.previous_services.append(name)
                run(["docker", "tag", actual["Image"], f"zeichen-rollback-{name}:{self.directory.name}"])
        for service in config["services"].values():
            service.pop("build", None)
        self.rollback_file = backup / "compose.json"
        write_json(self.rollback_file, config)
        (backup / "nginx.conf").write_text(self.old_nginx)
        for path in [self.root / ".env", *[self.root / p for p in ENVIRONMENT_OVERRIDES]]:
            if path.exists():
                shutil.copy2(path, backup / (path.name + ".private"))
        with (backup / "postgres.dump").open("wb") as output:
            run(["docker", "exec", "zeichen-postgres-1", "pg_dump", "-U", "zeichen",
                 "-d", "zeichen", "-Fc"], output=output)
        run(["docker", "run", "--rm", "--network", "none", "-v", "zeichen_attachments:/data:ro",
             "-v", f"{backup}:/backup", "alpine:latest", "sh", "-c",
             "umask 077; tar czf /backup/attachments.tar.gz -C /data ."])
        if (backup / "postgres.dump").stat().st_size == 0:
            raise RuntimeError("Database backup is empty")
        self.record["backup"] = str(backup)
        self.record["rollback_services"] = self.previous_services
        self.save("backed_up")

    def reload_gateway(self, text):
        # Preserve bind-mounted inode; an atomic rename would leave nginx on old bytes.
        with (self.root / "deploy/nginx.conf").open("w") as output:
            output.write(text)
        run(["docker", "exec", "zeichen-web-1", "nginx", "-t"])
        run(["docker", "exec", "zeichen-web-1", "nginx", "-s", "reload"])

    def verify_live(self):
        for name in SERVICES:
            wait_healthy(f"zeichen-{name}-1")
            actual = inspect(f"zeichen-{name}-1")
            expected = self.frontend if name == "frontend" else self.backend
            if actual["Image"] != expected or "--reload" in actual["Config"]["Cmd"]:
                raise RuntimeError(f"{name}: unexpected image or reload")
            if any(m["Type"] == "bind" for m in actual["Mounts"]):
                raise RuntimeError(f"{name}: source mount survived")
        # Nginx reload is asynchronous; retry the public probes while workers switch.
        for attempt in range(20):
            try:
                assert json.loads(http_get("https://zeichen.mochigm.cn/api/health"))["status"] == "ok"
                json.loads(http_get("https://zeichen.mochigm.cn/.well-known/oauth-protected-resource/mcp"))
                expected = run(["docker", "exec", "zeichen-frontend-1", "sha256sum",
                                "/usr/share/nginx/html/index.html"], capture=True).split()[0]
                assert digest(http_get("https://zeichen.mochigm.cn/")) == expected
                break
            except Exception:
                if attempt == 19:
                    raise
                time.sleep(2)
        assert inspect("zeichen-web-1")["Id"] == self.gateway["Id"], "Shared gateway was replaced"
        assert inspect("zeichen-postgres-1")["Id"] == self.database["Id"], "Database was replaced"
        assert digest(http_get("https://mochigm.cn/")) == self.mochi_hash, "MochiSite content changed"
        assert self.db_revision() == self.target_revision, "Unexpected database version"

    def activate(self):
        # Recheck after long builds; no lost updates or concurrent manual edits.
        if worktree_changes(self.root):
            raise RuntimeError("Server changed during checks; refusing activation")
        if run(["git", "rev-parse", "HEAD"], capture=True, cwd=self.root) != self.old_head:
            raise RuntimeError("Server HEAD changed during checks")
        if self.db_revision() != self.old_revision:
            raise RuntimeError("Database version changed during checks")
        self.backup()
        self.save("activating")
        try:
            if self.target_revision != self.old_revision:
                run(self.command + ["run", "--rm", "--no-deps", "api", "alembic", "upgrade", "head"], env=self.environment)
            # Never call down, --remove-orphans, or up on web/postgres.
            run(self.command + ["up", "-d", "--no-deps", "--no-build", "--wait", "--wait-timeout", "150",
                                "api", "mcp", "worker", "frontend"], env=self.environment)
            self.reload_gateway(self.new_nginx)
            self.verify_live()
        except BaseException:
            if self.db_revision() == self.old_revision:
                print("Activation failed; restoring previous app images. Database is not restored.", flush=True)
                run(self.compose([self.rollback_file]) + ["up", "-d", "--no-deps", "--no-build",
                    "--wait", "--wait-timeout", "150", *self.previous_services])
                self.reload_gateway(self.old_nginx)
                self.save("rolled_back")
            else:
                self.save("manual_recovery_required")
                print("Schema changed; automatic database downgrade/restore is forbidden. Backups: " + str(self.directory), flush=True)
            raise
        sync_repository(self.root, self.args.commit, self.old_head)
        self.record.update(database_after=self.db_revision(), counts_after=self.counts(),
                           compose_file=str(self.directory / "compose.json"))
        self.save("deployed")
        write_json(self.state / "current.json", self.record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--allow-migration", action="store_true")
    parser.add_argument("--candidate-source", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        parser.error("Expected a full Git commit SHA")
    if args.candidate_source is not None and (not args.check_only or args.allow_migration):
        parser.error("Candidate sources require --check-only without --allow-migration")
    os.umask(0o077)
    state = args.root if args.candidate_source is not None else args.root / ".release"
    state.mkdir(mode=0o700, exist_ok=True)
    with (state / "lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another check or release is running in this state directory")
        release = Release(args)
        print("Release evidence: " + str(release.directory), flush=True)
        try:
            if release.candidate:
                if shutil.disk_usage(release.state).free < 5 * 1024**3:
                    raise RuntimeError("At least 5 GiB free disk required")
            else:
                release.preflight()
            release.build_and_test()
            if not args.check_only:
                release.activate()
            print("RELEASE " + release.record["status"].upper() + ": " + args.commit, flush=True)
        except BaseException:
            if release.record["status"] not in ("rolled_back", "manual_recovery_required"):
                release.save("failed")
            raise


if __name__ == "__main__":
    main()
