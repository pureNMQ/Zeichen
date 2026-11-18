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
V2_SERVICES = ("api", "mcp", "frontend")
V2_MARKER = "v2-cutover-active.json"
V2_ATTACHMENTS = "/srv/zeichen/storage/attachments"
V2_MAINTENANCE = "deploy/docker-compose.maintenance.yml"
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
ENVIRONMENT_OVERRIDES = ("deploy/docker-compose.ip.yml", "/srv/site/compose.override.yml")
V2_ARCHIVE = """
import sys
import tarfile

def include(member):
    if member.name != "./library-v2/.staging":
        return member

with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
    archive.add("/attachments", arcname=".", filter=include)
"""


def run(args, *, capture=False, env=None, cwd=None, output=None):
    args = [str(a) for a in args]
    if capture:
        return subprocess.check_output(args, text=True, env=env, cwd=cwd).strip()
    print("+ " + " ".join(args), flush=True)
    subprocess.run(args, check=True, env=env, cwd=cwd, stdout=output)


def inspect(name):
    return json.loads(run(["docker", "inspect", name], capture=True))[0]


def worktree_changes(root, *excluded):
    # The first run creates state before the updated .gitignore is installed.
    return run(["git", "status", "--porcelain", "--", ".", ":(exclude).release",
                *(f":(exclude){path}" for path in excluded)], capture=True, cwd=root)


def write_json(path, value):
    write_private(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def write_private(path, content):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
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


def validate_release_config(config, services=SERVICES):
    for name in services:
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
    services = SERVICES

    def __init__(self, args):
        self.args = args
        self.root = args.root.resolve()
        self.candidate = args.candidate_source is not None
        self.state = self.root if self.candidate else self.root / ".release"
        self.state.mkdir(mode=0o700, exist_ok=True)
        self.state.chmod(0o700)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = f"-{time.time_ns()}"
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
               "--env-file", self.root / ".env", "-p", "zeichen", "--profile", "legacy-only"]
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
        self.configure_release()

    def configure_release(self):
        if self.target_revision.startswith("v2"):
            raise RuntimeError("Zeichen v2 requires the separate database and file-volume cutover flow")
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
        with (self.root / "deploy/nginx.conf").open("w", encoding="utf-8", newline="") as output:
            output.write(text)
        run(["docker", "exec", "zeichen-web-1", "nginx", "-t"])
        run(["docker", "exec", "zeichen-web-1", "nginx", "-s", "reload"])

    def verify_live(self, *, backend=None, frontend=None):
        for name in self.services:
            wait_healthy(f"zeichen-{name}-1")
            actual = inspect(f"zeichen-{name}-1")
            expected = (frontend or self.frontend) if name == "frontend" else (backend or self.backend)
            if actual["Image"] != expected or "--reload" in (actual["Config"]["Cmd"] or []):
                raise RuntimeError(f"{name}: unexpected image or reload")
            if any(m["Type"] == "bind" for m in actual["Mounts"]):
                raise RuntimeError(f"{name}: source mount survived")
        # Nginx reload is asynchronous; retry the public probes while workers switch.
        for attempt in range(20):
            try:
                if json.loads(http_get("https://zeichen.mochigm.cn/api/health")).get("status") != "ok":
                    raise RuntimeError("Published API is unhealthy")
                mcp = json.loads(http_get("https://zeichen.mochigm.cn/.well-known/oauth-protected-resource/mcp"))
                if mcp.get("resource") != "https://zeichen.mochigm.cn/mcp":
                    raise RuntimeError("Published MCP resource is unexpected")
                expected = run(["docker", "exec", "zeichen-frontend-1", "sha256sum",
                                "/usr/share/nginx/html/index.html"], capture=True).split()[0]
                if digest(http_get("https://zeichen.mochigm.cn/")) != expected:
                    raise RuntimeError("Published frontend differs from the built artifact")
                break
            except Exception:
                if attempt == 19:
                    raise
                time.sleep(2)
        if inspect("zeichen-web-1")["Id"] != self.gateway["Id"]:
            raise RuntimeError("Shared gateway was replaced")
        if inspect("zeichen-postgres-1")["Id"] != self.database["Id"]:
            raise RuntimeError("Database was replaced")
        if digest(http_get("https://mochigm.cn/")) != self.mochi_hash:
            raise RuntimeError("MochiSite content changed")
        if self.db_revision() != self.target_revision:
            raise RuntimeError("Unexpected database version")

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


class V2Release(Release):
    """Publish code changes on the accepted v2 database and file volume."""

    services = V2_SERVICES

    def compose(self, files):
        return ["docker", "compose", "--project-directory", self.root, "--env-file",
                self.prepared / "activation.env", "-p", "zeichen", "-f", self.snapshot,
                "-f", self.prepared / "activation.override.json", *[
                    value for path in files for value in ("-f", path)
                ]]

    def pg(self, *args, capture=False, output=None):
        return run(["docker", "exec", "zeichen-postgres-1", *args, "-U", self.role,
                    "-d", self.database_name], capture=capture, output=output)

    def db_revision(self):
        return self.pg("psql", "-X", "-At", "-v", "ON_ERROR_STOP=1",
                       "-c", "SELECT version_num FROM alembic_version", capture=True)

    def check_source(self, head=None):
        # The initial cutover installs these two live files before the Git checkout catches up.
        paths = ("deploy/nginx.conf", V2_MAINTENANCE)
        if worktree_changes(self.root, *(paths if self.last is None else ())):
            raise RuntimeError("Server worktree contains changes outside the cutover files")
        run(["git", "diff", "--cached", "--quiet", "--", *paths], cwd=self.root)
        if head is not None and run(["git", "rev-parse", "HEAD"], capture=True, cwd=self.root) != head:
            raise RuntimeError("Server HEAD changed during release checks")

    def check_ingress(self):
        ingress = self.root / "deploy/nginx.conf"
        stat = ingress.stat()
        if [stat.st_dev, stat.st_ino] != self.ingress_identity or digest(ingress.read_bytes()) != self.old_ingress_hash:
            raise RuntimeError("Shared ingress changed outside an accepted release")

    def check_bindings(self, images):
        if inspect("zeichen-postgres-1")["Id"] != self.database["Id"]:
            raise RuntimeError("PostgreSQL container changed")
        if inspect("zeichen-web-1")["Id"] != self.gateway["Id"]:
            raise RuntimeError("Shared gateway container changed")
        if inspect("zeichen-worker-1")["State"]["Running"]:
            raise RuntimeError("Legacy worker must remain stopped")
        if run(["docker", "volume", "inspect", "--format", '{{index .Labels "zeichen.cutover"}}',
                self.volume], capture=True) != self.volume_token:
            raise RuntimeError("Active v2 file volume changed")
        for name, image in images.items():
            container = inspect(f"zeichen-{name}-1")
            config = container["Config"]
            labels = config["Labels"]
            wiring = container["NetworkSettings"]
            if (container["Image"] != image or not container["State"]["Running"]
                    or labels.get("com.docker.compose.project") != "zeichen"
                    or labels.get("com.docker.compose.service") != name
                    or any((wiring.get("Ports") or {}).values())
                    or any(mount["Type"] == "bind" for mount in container["Mounts"])):
                raise RuntimeError(f"{name}: active container differs from the accepted release")
            if name in ("api", "mcp"):
                mounts = [mount for mount in container["Mounts"] if mount["Destination"] == V2_ATTACHMENTS]
                if (f"DATABASE_URL={self.dsn}" not in config["Env"] or self.network not in wiring["Networks"]
                        or len(mounts) != 1 or mounts[0]["Type"] != "volume" or mounts[0]["Name"] != self.volume):
                    raise RuntimeError(f"{name}: active database or file volume changed")

    def preflight(self):
        # Imported here because the cutover preparation tool uses the common release helpers.
        from prepare_v2_cutover import fingerprint, target_connection

        if self.args.allow_migration:
            raise RuntimeError("-AllowMigration is unavailable for routine v2 releases")
        marker = json.loads((self.state / V2_MARKER).read_text(encoding="utf-8"))
        working = Path(marker["state"]).resolve(strict=True)
        if working.parent != self.state or not re.fullmatch(r"cutover-[a-z0-9-]{1,60}", working.name):
            raise RuntimeError("Invalid active cutover state directory")
        journal = json.loads((working / "status.json").read_text(encoding="utf-8"))
        if journal.get("phase") != "active" or journal.get("writes_may_exist") is not True:
            raise RuntimeError("Routine releases require an active, write-open v2 cutover")
        manifest_path = Path(journal["prepared"])
        self.prepared = manifest_path.parent
        manifest_hash = fingerprint(manifest_path)
        acceptance = json.loads(Path(journal["acceptance"]).read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        commit = manifest["candidate_commit"]
        self.snapshot = working / "snapshot" / "compose.json"
        if (manifest["status"] != "prepared" or acceptance.get("prepared_manifest_sha256") != manifest_hash
                or acceptance.get("candidate_commit") != commit or not re.fullmatch(r"[0-9a-f]{40}", commit)
                or acceptance.get("migration_exceptions_reviewed") is not True
                or fingerprint(self.snapshot) != journal.get("rollback_compose_sha256")
                or fingerprint(self.prepared / "activation.override.json") != manifest["activation_override_sha256"]):
            raise RuntimeError("Accepted v2 cutover artifacts changed")
        self.database_name = manifest["target_database"]
        self.volume, self.volume_token = manifest["target_attachment_volume"], manifest["volume_owner_token"]
        self.network, self.old_revision = manifest["network"], manifest["alembic_target"]
        if (not re.fullmatch(r"zeichen_v2_[a-z0-9_]{1,28}", self.database_name)
                or not re.fullmatch(r"[0-9a-f]{32}", self.volume_token)
                or self.volume != f"{self.database_name}_files_{self.volume_token[:10]}"
                or not self.old_revision.startswith("v2")):
            raise RuntimeError("Invalid accepted v2 database or volume")
        self.role, _, self.dsn = target_connection(json.loads(self.snapshot.read_text(encoding="utf-8")), self.database_name)
        if (self.prepared / "activation.env").read_text(encoding="utf-8") != f"ZEICHEN_PREPARED_DATABASE_URL={self.dsn}\n":
            raise RuntimeError("Accepted v2 activation database changed")
        for variable in ("ZEICHEN_PREPARED_DATABASE_URL", "COMPOSE_PROFILES", "COMPOSE_FILE"):
            self.environment.pop(variable, None)
        self.current = self.state / "v2-current.json"
        self.last = self.current.read_bytes() if self.current.exists() else None
        self.old_ingress_hash = manifest["candidate_ingress_sha256"]
        backend, frontend = manifest["backend_image"], manifest["frontend_image"]
        self.ingress_identity = journal["ingress_identity"]
        self.check_source()
        if run(["git", "branch", "--show-current"], capture=True, cwd=self.root) != "develop":
            raise RuntimeError("Server must be on develop")
        self.old_head = run(["git", "rev-parse", "HEAD"], capture=True, cwd=self.root)
        self.artifacts = self.directory / "compose.override.json"
        self.rollback_file = self.directory / "rollback.override.json"
        if self.last is not None:
            last = json.loads(self.last)
            if (last["status"] != "deployed" or last["cutover_manifest_sha256"] != manifest_hash
                    or last["commit"] != self.old_head or last["database_after"] != self.old_revision):
                raise RuntimeError("Prior v2 release state does not match the active cutover")
            self.old_ingress_hash = last["ingress_sha256"]
            backend, frontend = last["backend_image"], last["frontend_image"]
        if not all(IMAGE_ID.fullmatch(value) for value in (backend, frontend)):
            raise RuntimeError("Active v2 images must have immutable IDs")
        self.previous_images = {"api": backend, "mcp": backend, "frontend": frontend}
        for revision in (commit, self.old_head):
            run(["git", "merge-base", "--is-ancestor", revision, self.args.commit], cwd=self.root)
        if shutil.disk_usage(self.root).free < 5 * 1024**3:
            raise RuntimeError("At least 5 GiB free disk required")
        self.database = inspect("zeichen-postgres-1")
        self.gateway = inspect("zeichen-web-1")
        if (self.database["Id"] != journal["postgres_id"] or self.database["Id"] != manifest["postgres_container_id"]
                or self.gateway["Id"] != journal["gateway_id"]
                or self.network not in self.database["NetworkSettings"]["Networks"]):
            raise RuntimeError("Shared gateway or PostgreSQL differs from the accepted cutover")
        self.check_ingress()
        self.check_bindings(self.previous_images)
        if self.db_revision() != self.old_revision:
            raise RuntimeError("Active v2 schema differs from the accepted cutover")
        self.old_nginx = (self.root / "deploy/nginx.conf").read_bytes().decode("utf-8")
        self.new_nginx = (self.source / "deploy/nginx.conf").read_bytes().decode("utf-8")
        protect_ingress(self.old_nginx, self.new_nginx)
        self.mochi_hash = digest(http_get("https://mochigm.cn/"))
        self.maintenance = self.maintenance_state(working, backend)
        self.inputs = {path: fingerprint(path) for path in (
            self.snapshot, manifest_path, self.prepared / "activation.override.json", self.prepared / "activation.env",
        )}
        self.record.update(mode="release_v2", previous_commit=self.old_head, database_before=self.old_revision,
                           cutover_manifest_sha256=manifest_hash, database_name=self.database_name,
                           attachment_volume=self.volume, mochi_home_sha256=self.mochi_hash)
        self.save("checking")

    def maintenance_state(self, working, backend):
        expected = (f"ZEICHEN_BACKEND_IMAGE={backend}\nZEICHEN_MAINTENANCE_DATABASE_URL={self.dsn}\n"
                    f"ZEICHEN_MAINTENANCE_VOLUME={self.volume}\nZEICHEN_MAINTENANCE_NETWORK={self.network}\n").encode()
        paths = [working / "maintenance.env"]
        installed = self.state / "v2-maintenance.env"
        if installed.exists() or installed.is_symlink():
            paths.append(installed)
        for path in paths:
            if path.is_symlink() or path.read_bytes() != expected:
                raise RuntimeError("Active maintenance inputs differ from the accepted release")
        live = self.root / V2_MAINTENANCE
        if len(paths) > 1 and not live.is_file():
            raise RuntimeError("Installed maintenance requires its live Compose configuration")
        if live.exists() and live.read_bytes() != (self.source / V2_MAINTENANCE).read_bytes():
            raise RuntimeError("Routine v2 releases must retain the installed maintenance Compose configuration")
        return dict.fromkeys(paths, expected)

    def configure_release(self):
        if self.target_revision != self.old_revision:
            raise RuntimeError("Routine v2 releases require the active Alembic head")
        for file, images in (
            (self.artifacts, {"api": self.backend, "mcp": self.backend, "frontend": self.frontend}),
            (self.rollback_file, self.previous_images),
        ):
            write_json(file, {"services": {name: {"image": image} for name, image in images.items()}})
            config = json.loads(run(self.compose([file]) + ["config", "--format", "json"],
                                    capture=True, env=self.environment))
            validate_release_config(config, self.services)
            if "worker" in config["services"]:
                raise RuntimeError("Routine v2 releases must keep the legacy worker disabled")
            for name, image in images.items():
                service = config["services"][name]
                if service["image"] != image:
                    raise RuntimeError(f"{name}: published image does not match routine release")
                if name != "frontend":
                    mounts = [mount for mount in service["volumes"] if mount["target"] == V2_ATTACHMENTS]
                    networks = {config["networks"][key]["name"] for key in service["networks"]}
                    if (service["environment"]["DATABASE_URL"] != self.dsn or self.network not in networks
                            or len(mounts) != 1 or mounts[0]["type"] != "volume"
                            or config["volumes"][mounts[0]["source"]] != {"name": self.volume, "external": True}):
                        raise RuntimeError(f"{name}: published database or volume does not match routine release")
        self.save("verified")

    def backup(self):
        backup = self.directory / "backup"
        backup.mkdir(mode=0o700)
        (backup / "nginx.conf").write_bytes((self.root / "deploy/nginx.conf").read_bytes())
        for name, image in self.previous_images.items():
            run(["docker", "tag", image, f"zeichen-rollback-{name}:{self.directory.name}"])
        with (backup / "postgres.dump").open("wb") as output:
            self.pg("pg_dump", "-Fc", output=output)
        with (backup / "attachments.tar.gz").open("wb") as output:
            run(["docker", "run", "--rm", "--pull=never", "--network", "none", "--mount",
                 f"type=volume,src={self.volume},dst=/attachments,readonly", "--entrypoint", "python",
                 self.previous_images["api"], "-c", V2_ARCHIVE], output=output)
        if not all((backup / name).stat().st_size for name in ("postgres.dump", "attachments.tar.gz")):
            raise RuntimeError("Active v2 backup is empty")
        self.record.update(backup=str(backup), rollback_override=str(self.rollback_file))
        self.save("backed_up")

    def start_apps(self, override):
        run(self.compose([override]) + ["up", "-d", "--no-deps", "--no-build", "--pull", "never",
            "--wait", "--wait-timeout", "150", *self.services], env=self.environment)

    def activate(self):
        from prepare_v2_cutover import fingerprint

        self.check_source(self.old_head)
        self.check_ingress()
        self.check_bindings(self.previous_images)
        if any(fingerprint(path) != checksum for path, checksum in self.inputs.items()):
            raise RuntimeError("Accepted cutover artifacts changed during release checks")
        if self.db_revision() != self.old_revision or any(path.read_bytes() != data for path, data in self.maintenance.items()):
            raise RuntimeError("Database or maintenance inputs changed during release checks")
        self.save("stopping_writers_for_backup")
        try:
            # Quiesce the app before taking both snapshots. Scheduled maintenance
            # affects only expiring grants and the excluded staging directory.
            run(self.compose([self.rollback_file]) + ["stop", "--timeout", "45", "api", "mcp"], env=self.environment)
            if any(inspect(f"zeichen-{name}-1")["State"]["Running"] for name in ("api", "mcp")):
                raise RuntimeError("Application writers did not stop for the v2 backup")
            self.backup()
            self.save("activating")
            self.start_apps(self.artifacts)
            self.reload_gateway(self.new_nginx)
            self.verify_live()
            self.check_bindings({"api": self.backend, "mcp": self.backend, "frontend": self.frontend})
            for path, data in self.maintenance.items():
                write_private(path, data.replace(self.previous_images["api"].encode(), self.backend.encode(), 1))
        except BaseException:
            try:
                if self.db_revision() == self.old_revision:
                    self.start_apps(self.rollback_file)
                    self.reload_gateway(self.old_nginx)
                    for path, data in self.maintenance.items():
                        if path.read_bytes() != data:
                            write_private(path, data)
                    self.check_bindings(self.previous_images)
                    self.verify_live(backend=self.previous_images["api"], frontend=self.previous_images["frontend"])
                    self.save("rolled_back")
                else:
                    self.save("manual_recovery_required")
            except BaseException:
                self.save("manual_recovery_required")
                raise
            raise
        try:
            sync_repository(self.root, self.args.commit, self.old_head)
            self.record.update(database_after=self.db_revision(),
                               ingress_sha256=digest((self.root / "deploy/nginx.conf").read_bytes()),
                               compose_override=str(self.artifacts))
            self.save("deployed")
            write_json(self.current, self.record)
        except BaseException:
            self.save("manual_recovery_required")
            raise


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
        marker = state / V2_MARKER
        kind = V2Release if args.candidate_source is None and (marker.exists() or marker.is_symlink()) else Release
        release = kind(args)
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
