#!/usr/bin/env python3
"""Freeze, stage, open, or roll back an accepted side-by-side Zeichen release."""

import argparse
import fcntl
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from cutover_ingress import gate
from prepare_v2_cutover import IMAGE, NAME, SOURCE_REVISION, Runner, fingerprint, private_file, rollback_images, target_connection
from remote_release import digest, http_get, protect_ingress, write_json


GATEWAY = "zeichen-web-1"
POSTGRES = "zeichen-postgres-1"
ATTACHMENTS = "/srv/zeichen/storage/attachments"
WEB = "https://zeichen.mochigm.cn"
MOCHI = "https://mochigm.cn/"
APPS = ("api", "mcp", "frontend")
WRITERS = ("api", "mcp", "worker")
MARKER = "v2-cutover-active.json"
ACCEPTANCE_IDS = {f"AC-{number:02d}" for number in range(1, 32)}
ARCHIVE = """
import sys
import tarfile
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
    archive.add("/attachments", arcname=".")
"""


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def status(url, *, method="GET"):
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def validate_acceptance(acceptance, prepared_path, manifest):
    require(
        acceptance.get("candidate_commit") == manifest["candidate_commit"]
        and acceptance.get("prepared_manifest_sha256") == fingerprint(prepared_path)
        and acceptance.get("migration_exceptions_reviewed") is True,
        "acceptance must bind this candidate and prepared migration",
    )
    checks = acceptance.get("checks", {})
    require(set(checks) == ACCEPTANCE_IDS and all(
        row.get("passed") is True and isinstance(row.get("evidence"), str) and row["evidence"].strip()
        for row in checks.values()
    ), "all 31 criteria need evidence and a passing result")
    proof = acceptance["restore_rehearsal"]
    report_path = Path(proof["path"]).resolve(strict=True)
    require(fingerprint(report_path) == proof["sha256"], "restore rehearsal evidence changed")
    report = read_json(report_path)
    require(report.get("status") == "verified" and report.get("mode") == "synthetic_only"
            and report.get("candidate_commit") == manifest["candidate_commit"],
            "restore rehearsal must verify this exact candidate")


class Cutover:
    def __init__(self, root, working, run, log):
        self.root, self.working, self.run, self.log = root, working, run, log
        self.ingress = root / "deploy" / "nginx.conf"
        self.marker = root / ".release" / MARKER
        self.journal = working / "status.json"
        self.snapshot = working / "snapshot"
        self.record = read_json(self.journal) if self.journal.exists() else {}

    def save(self, phase, **data):
        self.record.update(data, phase=phase, updated_at=datetime.now(UTC).isoformat())
        write_json(self.journal, self.record)

    def assert_owner(self):
        require(read_json(self.marker)["state"] == str(self.working), "another cutover owns this deployment lock")

    def inspect(self, name):
        return json.loads(self.run.docker("container", "inspect", name, capture=True))[0]

    def app(self, service):
        info = self.inspect(f"zeichen-{service}-1")
        labels = info["Config"]["Labels"]
        require(labels.get("com.docker.compose.project") == "zeichen"
                and labels.get("com.docker.compose.service") == service, f"unexpected {service} container identity")
        return info

    def compose(self, *args, candidate=None):
        environment = str(candidate / "activation.env") if candidate else os.devnull
        command = [
            "compose", "-p", "zeichen", "--project-directory", str(self.root),
            "--env-file", environment, "-f", str(self.snapshot / "compose.json"),
        ]
        if candidate:
            command += ["-f", str(candidate / "activation.override.json")]
        self.run.docker(*command, *args)

    def pg(self, database, sql):
        return self.run.docker(
            "exec", POSTGRES, "psql", "-X", "-At", "-v", "ON_ERROR_STOP=1",
            "-U", self.record["legacy_role"], "-d", database, "-c", sql, capture=True,
        )

    def capture(self, path, *args):
        with path.open("xb") as output:
            subprocess.run(["docker", *args], stdout=output, stderr=self.log,
                           stdin=subprocess.DEVNULL, check=True)
        require(path.stat().st_size > 0, "empty snapshot artifact")

    def write_ingress(self, data):
        # The shared gateway bind-mounts this file; a rename replaces the inode.
        with self.ingress.open("r+b") as output:
            opened = os.fstat(output.fileno())
            require([opened.st_dev, opened.st_ino] == self.record["ingress_identity"], "shared ingress inode changed")
            output.seek(0)
            output.write(data)
            output.truncate()
            output.flush()
            os.fsync(output.fileno())

    def reload(self):
        self.run.docker("exec", GATEWAY, "nginx", "-t")
        self.run.docker("exec", GATEWAY, "nginx", "-s", "reload")

    def install_ingress(self, rendered, *, restore_on_error=True):
        original = self.ingress.read_bytes()
        self.write_ingress(rendered)
        try:
            self.reload()
        except Exception:
            if restore_on_error:
                self.write_ingress(original)
                self.reload()
            raise

    def worker_pids(self):
        output = self.run.docker("exec", GATEWAY, "ps", "-o", "pid,args", capture=True)
        return {row.split()[0] for row in output.splitlines() if "nginx: worker process" in row}

    def wait_drain(self, previous):
        require(bool(previous), "could not identify pre-freeze ingress workers")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if not (previous & self.worker_pids()):
                return
            time.sleep(1)
        raise RuntimeError("prior ingress workers did not drain")

    def require_closed(self, *, probes):
        # Both requests are harmless even if the expected restriction is absent.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if (status(f"{WEB}/api/health", method="POST") == 503
                    and status("http://zeichen.mochigm.cn/api/health") == 503
                    and status(f"{WEB}/api/health") == (200 if probes else 503)):
                return
            time.sleep(1)
        raise RuntimeError("Zeichen ingress has not reached the expected write-closed state")

    def check_shared(self):
        require(self.inspect(GATEWAY)["Id"] == self.record["gateway_id"], "shared gateway container changed")
        require(self.inspect(POSTGRES)["Id"] == self.record["postgres_id"], "shared PostgreSQL container changed")
        require(digest(http_get(MOCHI)) == self.record["mochi_sha256"], "MochiSite changed during cutover")

    def pinned_services(self, images, database, volume, *, dsn):
        names = APPS if "worker" not in images else (*APPS, "worker")
        for name in names:
            container = self.app(name)
            require(container["Image"] == images[name], f"{name} is not using its pinned image")
            require(not any((container["NetworkSettings"].get("Ports") or {}).values()), f"{name} has a host port")
            if name in WRITERS:
                env = dict(value.partition("=")[::2] for value in container["Config"]["Env"])
                actual = env.get("DATABASE_URL", "")
                require(actual == dsn and urlsplit(actual).path == f"/{database}", f"{name} database does not match")
            if name in {"api", "mcp"}:
                found = [mount for mount in container["Mounts"] if mount["Destination"] == ATTACHMENTS]
                require(len(found) == 1 and found[0].get("Name") == volume
                        and found[0]["Type"] == "volume", f"{name} attachment volume does not match")

    def stopped(self, *names):
        for name in names:
            require(not self.app(name)["State"]["Running"], f"{name} is still running")

    def verify_routes(self):
        require(json.loads(http_get(f"{WEB}/api/health")).get("status") == "ok", "candidate API is unhealthy")
        metadata = json.loads(http_get(f"{WEB}/.well-known/oauth-protected-resource/mcp"))
        require(metadata.get("resource") == f"{WEB}/mcp", "unexpected MCP resource")
        expected = self.run.docker(
            "exec", "zeichen-frontend-1", "sha256sum", "/usr/share/nginx/html/index.html", capture=True,
        ).split()[0]
        require(digest(http_get(WEB + "/")) == expected, "published frontend is not the pinned artifact")
        self.check_shared()

    def freeze(self, legacy_compose):
        require(not self.marker.exists(), "another v2 cutover is already active")
        require(not self.record, "cutover state already exists")
        legacy = read_json(legacy_compose)
        legacy_images = rollback_images(legacy)
        role, host, _ = target_connection(legacy, "zeichen_v2_validate")
        gateway, postgres = self.inspect(GATEWAY), self.inspect(POSTGRES)
        require(not any((postgres["NetworkSettings"].get("Ports") or {}).values()),
                "legacy PostgreSQL has a published port")
        mounts = [mount for mount in gateway["Mounts"] if mount["Destination"] == "/etc/nginx/conf.d/default.conf"]
        require(len(mounts) == 1 and mounts[0]["Type"] == "bind"
                and Path(mounts[0]["Source"]).resolve() == self.ingress.resolve(), "unexpected ingress mount")
        old_api = self.app("api")
        db_aliases = {
            alias
            for name, attachment in postgres["NetworkSettings"]["Networks"].items()
            if name in old_api["NetworkSettings"]["Networks"]
            for alias in (*(attachment.get("Aliases") or []), attachment.get("IPAddress"))
            if alias
        }
        require(host in db_aliases, "legacy backup target is not the database used by the application")
        names = {mount.get("Name") for mount in old_api["Mounts"] if mount["Destination"] == ATTACHMENTS}
        require(len(names) == 1, "could not resolve legacy attachment volume")
        old_volume = names.pop()
        require(isinstance(old_volume, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", old_volume),
                "legacy attachment mount is not a named volume")
        self.pinned_services(
            legacy_images, "zeichen", old_volume, dsn=legacy["services"]["api"]["environment"]["DATABASE_URL"],
        )
        self.record.update(legacy_role=role)
        require(self.pg("zeichen", "SELECT version_num FROM alembic_version") == SOURCE_REVISION,
                "legacy database revision is not supported")
        original = self.ingress.read_bytes()
        ingress_stat = self.ingress.stat()
        closed = gate(original.decode("utf-8"), probes=False).encode("utf-8")
        previous = self.worker_pids()
        require(bool(previous), "could not identify active ingress workers")
        self.snapshot.mkdir(mode=0o700)
        private_file(self.snapshot / "compose.json", legacy_compose.read_text(encoding="utf-8"))
        (self.snapshot / "nginx.conf").write_bytes(original)
        self.save(
            "freezing", gateway_id=gateway["Id"], postgres_id=postgres["Id"], legacy_volume=old_volume,
            legacy_images=legacy_images, mochi_sha256=digest(http_get(MOCHI)),
            old_ingress_sha256=digest(original), closed_ingress_sha256=digest(closed),
            ingress_identity=[ingress_stat.st_dev, ingress_stat.st_ino],
            rollback_compose_sha256=fingerprint(self.snapshot / "compose.json"),
            writes_may_exist=False, legacy_worker_was_running=self.app("worker")["State"]["Running"],
        )
        write_json(self.marker, {"state": str(self.working)})
        self.install_ingress(closed)
        self.require_closed(probes=False)
        self.compose("stop", *WRITERS)
        self.stopped(*WRITERS)
        self.wait_drain(previous)
        self.check_shared()
        self.capture(self.snapshot / "postgres.dump", "exec", POSTGRES, "pg_dump", "-Fc",
                     "-U", role, "-d", "zeichen")
        self.capture(
            self.snapshot / "attachments.tar.gz", "run", "--rm", "--pull=never", "--network", "none",
            "--mount", f"type=volume,src={old_volume},dst=/attachments,readonly",
            "--entrypoint", "python", legacy_images["api"], "-c", ARCHIVE,
        )
        self.save("frozen", snapshot_sha256={
            name: fingerprint(self.snapshot / name)
            for name in ("postgres.dump", "attachments.tar.gz", "compose.json", "nginx.conf")
        })

    def validate_prepared(self, prepared_path, acceptance):
        manifest = read_json(prepared_path)
        root = prepared_path.parent
        require(manifest.get("status") == "prepared" and manifest.get("postgres_container") == POSTGRES
                and manifest.get("postgres_container_id") == self.record["postgres_id"]
                and Path(manifest["snapshot_root"]).resolve() == self.snapshot.resolve(),
                "prepared release does not belong to this frozen source")
        require(re.fullmatch(r"zeichen_v2_[a-z0-9_]{1,28}", manifest["target_database"])
                and re.fullmatch(r"[0-9a-f]{40}", manifest["candidate_commit"])
                and all(IMAGE.fullmatch(manifest[name]) for name in ("backend_image", "frontend_image")),
                "incorrect candidate identity")
        for name in ("postgres.dump", "attachments.tar.gz", "compose.json", "nginx.conf"):
            require(fingerprint(self.snapshot / name) == manifest["snapshot_sha256"][name]
                    == self.record["snapshot_sha256"][name], "frozen snapshot changed")
        for name, field in (("import-report.json", "import_report_sha256"),
                            ("activation.override.json", "activation_override_sha256"),
                            ("nginx.candidate.conf", "candidate_ingress_sha256")):
            require(fingerprint(root / name) == manifest[field], f"prepared {name} changed")
        _, _, dsn = target_connection(read_json(self.snapshot / "compose.json"), manifest["target_database"])
        require((root / "activation.env").read_text(encoding="utf-8") == f"ZEICHEN_PREPARED_DATABASE_URL={dsn}\n"
                and (root / "database.env").read_text(encoding="utf-8") == f"DATABASE_URL={dsn}\n",
                "prepared activation credentials do not target the clone")
        network = manifest["network"]
        require(NAME.fullmatch(network) and network != "host"
                and network in self.inspect(POSTGRES)["NetworkSettings"]["Networks"],
                "prepared application network no longer reaches the clone")
        require(self.pg(manifest["target_database"], "SELECT version_num FROM alembic_version")
                == manifest["alembic_target"], "prepared database revision changed")
        volume = manifest["target_attachment_volume"]
        token = manifest["volume_owner_token"]
        require(re.fullmatch(r"[0-9a-f]{32}", token) and volume == f'{manifest["target_database"]}_files_{token[:10]}',
                "prepared volume has an unexpected identity")
        require(self.run.docker("volume", "inspect", "--format", '{{index .Labels "zeichen.cutover"}}',
                                volume, capture=True) == token, "prepared volume ownership changed")
        validate_acceptance(read_json(acceptance), prepared_path, manifest)
        return manifest

    def staged_health(self, manifest):
        self.require_closed(probes=True)
        _, _, dsn = target_connection(read_json(self.snapshot / "compose.json"), manifest["target_database"])
        self.pinned_services({"api": manifest["backend_image"], "mcp": manifest["backend_image"],
                              "frontend": manifest["frontend_image"]},
                             manifest["target_database"], manifest["target_attachment_volume"], dsn=dsn)
        self.stopped("worker")
        self.verify_routes()

    def verify_maintenance(self, prepared, manifest):
        image, volume, network = (manifest[name] for name in ("backend_image", "target_attachment_volume", "network"))
        output = self.run.docker(
            "run", "--rm", "--pull=never", "--network", network, "--env-file", str(prepared / "database.env"),
            "-e", f"ATTACHMENT_STORAGE_DIR={ATTACHMENTS}",
            "--mount", f"type=volume,src={volume},dst={ATTACHMENTS}",
            "--entrypoint", "python", image, "-m", "app.workers.maintenance", capture=True,
        )
        result = json.loads(output)
        require(result.get("event") == "zeichen_v2_maintenance" and result.get("status") == "success",
                "candidate one-shot maintenance did not succeed")
        _, _, dsn = target_connection(read_json(self.snapshot / "compose.json"), manifest["target_database"])
        maintenance_env = self.working / "maintenance.env"
        private_file(maintenance_env, f"ZEICHEN_BACKEND_IMAGE={image}\nZEICHEN_MAINTENANCE_DATABASE_URL={dsn}\n"
                     f"ZEICHEN_MAINTENANCE_VOLUME={volume}\nZEICHEN_MAINTENANCE_NETWORK={network}\n")
        return maintenance_env, result

    def stage(self, prepared_path, acceptance):
        self.assert_owner()
        require(self.record["phase"] == "frozen", "use the frozen cutover state")
        require(fingerprint(self.ingress) == self.record["closed_ingress_sha256"], "frozen ingress changed")
        self.stopped(*WRITERS)
        self.check_shared()
        manifest = self.validate_prepared(prepared_path, acceptance)
        original = (self.snapshot / "nginx.conf").read_bytes().decode("utf-8")
        next_ = (prepared_path.parent / "nginx.candidate.conf").read_bytes().decode("utf-8")
        protect_ingress(original, next_)
        probe_gate = gate(next_, probes=True).encode("utf-8")
        self.save("staging", prepared=str(prepared_path), acceptance=str(acceptance),
                  gated_candidate_sha256=digest(probe_gate))
        self.compose("up", "-d", "--no-deps", "--no-build", "--pull", "never",
                     "--wait", "--wait-timeout", "150", *APPS, candidate=prepared_path.parent)
        self.install_ingress(probe_gate)
        self.staged_health(manifest)
        maintenance_env, result = self.verify_maintenance(prepared_path.parent, manifest)
        self.save("staged", one_shot_maintenance=result, maintenance_env=str(maintenance_env))

    def open(self):
        self.assert_owner()
        require(self.record["phase"] == "staged" and not self.record["writes_may_exist"], "candidate is not staged")
        require(fingerprint(self.ingress) == self.record["gated_candidate_sha256"], "candidate ingress drifted")
        prepared = Path(self.record["prepared"])
        manifest = self.validate_prepared(prepared, Path(self.record["acceptance"]))
        self.staged_health(manifest)
        candidate = (prepared.parent / "nginx.candidate.conf").read_bytes()
        gated = self.ingress.read_bytes()
        # Persist the irreversible boundary before any write-capable worker can serve.
        self.save("opening", writes_may_exist=True)
        try:
            self.install_ingress(candidate)
            self.verify_routes()
        except Exception:
            self.install_ingress(gated, restore_on_error=False)
            self.save("v2_refrozen")
            raise
        self.save("active", maintenance_timer_pending=True)

    def rollback(self):
        self.assert_owner()
        require(not self.record["writes_may_exist"] and self.record["phase"] in {
            "freezing", "frozen", "staging", "staged", "rolling_back",
        }, "automatic rollback forbidden after writes might have reached v2")
        original = (self.snapshot / "nginx.conf").read_bytes()
        require(digest(original) == self.record["old_ingress_sha256"], "rollback ingress changed")
        legacy_probe = gate(original.decode("utf-8"), probes=True).encode("utf-8")
        require(fingerprint(self.ingress) in {
            self.record["old_ingress_sha256"], self.record["closed_ingress_sha256"],
            self.record.get("gated_candidate_sha256"), digest(legacy_probe),
        }, "ingress changed outside this cutover")
        require(fingerprint(self.snapshot / "compose.json") == self.record["rollback_compose_sha256"],
                "rollback configuration changed")
        legacy = read_json(self.snapshot / "compose.json")
        self.save("rolling_back")
        closed = gate(original.decode("utf-8"), probes=False).encode("utf-8")
        self.install_ingress(closed)
        self.require_closed(probes=False)
        self.compose("stop", *APPS)
        self.compose("up", "-d", "--no-deps", "--no-build", "--pull", "never",
                     "--wait", "--wait-timeout", "150", *APPS)
        self.pinned_services({name: self.record["legacy_images"][name] for name in APPS},
                             "zeichen", self.record["legacy_volume"],
                             dsn=legacy["services"]["api"]["environment"]["DATABASE_URL"])
        require(self.pg("zeichen", "SELECT version_num FROM alembic_version") == SOURCE_REVISION,
                "legacy database no longer supports rollback")
        self.install_ingress(legacy_probe)
        self.require_closed(probes=True)
        self.verify_routes()
        self.install_ingress(original)
        self.verify_routes()
        if self.record["legacy_worker_was_running"]:
            self.compose("up", "-d", "--no-deps", "--no-build", "--pull", "never", "worker")
        self.save("rolled_back")
        self.marker.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--state", required=True, help="Private directory name under .release")
    sub = parser.add_subparsers(dest="operation", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--legacy-compose", required=True, type=Path)
    stage = sub.add_parser("stage")
    stage.add_argument("--prepared", required=True, type=Path)
    stage.add_argument("--acceptance", required=True, type=Path)
    sub.add_parser("open")
    sub.add_parser("rollback")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"cutover-[a-z0-9-]{1,60}", args.state):
        parser.error("state must be a new or known cutover-* identifier")
    root = args.root.resolve(strict=True)
    release = root / ".release"
    working = release / args.state
    os.umask(0o077)
    with (release / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another release or cutover command is running") from None
        if args.operation == "freeze":
            working.mkdir(mode=0o700)
        with (working / "cutover.log").open("ab") as log:
            deployment = Cutover(root, working, Runner(log), log)
            try:
                if args.operation == "freeze":
                    deployment.freeze(args.legacy_compose.resolve(strict=True))
                elif args.operation == "stage":
                    deployment.stage(args.prepared.resolve(strict=True), args.acceptance.resolve(strict=True))
                else:
                    getattr(deployment, args.operation)()
            except Exception as error:
                deployment.save(deployment.record.get("phase", "preflight_failed"), error_type=type(error).__name__)
                print(f"Cutover {args.operation} failed. See {deployment.journal} and private cutover.log.")
                return 1
    print(f"Cutover {args.operation} complete. See {deployment.journal}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
