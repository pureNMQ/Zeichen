#!/usr/bin/env python3
"""Prepare a frozen v1 snapshot in new v2 resources. Never activates services."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from remote_release import protect_ingress, write_json


SOURCE_REVISION = "1007wikimerge"
TABLES = (
    "user", "api_key", "workspace_member", "project", "project_member", "repository",
    "requirement", "task", "task_blocker", "document", "document_version",
    "comment", "activity", "attachment", "reference", "notification", "project_filter_view",
)
IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")

# Stream the old volume into a blank named volume. The same archive is also
# seeded into the target, so legacy avatar and attachment paths keep working.
EXTRACT = r"""
from pathlib import Path, PurePosixPath
import gzip
import shutil
import sys
import tarfile

root = Path(sys.argv[1])
with gzip.GzipFile(fileobj=sys.stdin.buffer) as compressed:
    with tarfile.open(fileobj=compressed, mode="r|") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if (name.is_absolute() or ".." in name.parts or "\\" in member.name
                    or (name.parts and name.parts[0] == "library-v2")):
                raise ValueError("unsafe or reserved attachment path")
            target = root.joinpath(*name.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isreg() and name.parts:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as out, archive.extractfile(member) as source:
                    shutil.copyfileobj(source, out, 1024 * 1024)
            else:
                raise ValueError("unsupported attachment archive member")
    while compressed.read(1024 * 1024):
        pass  # Validate the gzip trailer, even if tar reached its end marker first.
"""
IMPORT = r"""
set -eu
workspace="$(mktemp -d)"
trap 'rm -rf -- "$workspace"' EXIT
python -m app.v2.import_legacy --target "$1" --legacy-storage /legacy --report "$workspace/report.json" >&2
cat "$workspace/report.json"
"""


def fingerprint(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def snapshot_file(directory: Path, name: str) -> Path:
    path = directory / name
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise ValueError(f"snapshot must contain non-empty regular {name}")
    return path


def private_file(path: Path, data: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
        output.write(data)


def candidate_record(path: Path) -> dict:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("mode") != "candidate" or record.get("status") != "verified":
        raise ValueError("need a verified isolated candidate result.json")
    if not re.fullmatch(r"[0-9a-f]{40}", record.get("commit", "")):
        raise ValueError("candidate must identify its full commit")
    if not all(IMAGE.fullmatch(record.get(field, "")) for field in ("backend_image", "frontend_image")):
        raise ValueError("candidate must pin both image IDs")
    if not re.fullmatch(r"v2[a-z0-9_]+", record.get("database_target", "")):
        raise ValueError("candidate has no v2 migration head")
    return record


def target_connection(compose: dict, target: str) -> tuple[str, str, str]:
    # Read the actual v1 service state. Never accept an independent arbitrary
    # migration DSN or carry its password into the preparation manifest.
    try:
        api = compose["services"]["api"]["environment"]["DATABASE_URL"]
        mcp = compose["services"]["mcp"]["environment"]["DATABASE_URL"]
        parsed = urlsplit(api)
        role = unquote(parsed.username or "")
        host = parsed.hostname
        if (
            api != mcp or parsed.scheme not in {"postgresql", "postgresql+psycopg"}
            or parsed.path != "/zeichen" or not host or parsed.query or parsed.fragment
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", role)
            or any(ord(c) < 32 for c in api)
            or parsed.port not in {None, 5432}
        ):
            raise ValueError
        return role, host, urlunsplit(parsed._replace(path=f"/{target}"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("snapshot compose needs matching API/MCP PostgreSQL connections to the legacy database") from exc


def rollback_images(compose: dict) -> dict[str, str]:
    try:
        images = {name: compose["services"][name]["image"] for name in ("api", "mcp", "frontend", "worker")}
        if not all(IMAGE.fullmatch(image) for image in images.values()):
            raise ValueError
        return images
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("snapshot must record immutable rollback images for all v1 application services") from exc


def activation_overlay(candidate: dict, target_volume: str) -> dict:
    shared = {
        "image": candidate["backend_image"],
        "pull_policy": "never",
        "environment": {
            "DATABASE_URL": "${ZEICHEN_PREPARED_DATABASE_URL:?Load prepared activation.env}",
            "ATTACHMENT_STORAGE_DIR": "/srv/zeichen/storage/attachments",
        },
        "volumes": ["v2-prepared-attachments:/srv/zeichen/storage/attachments"],
    }
    return {
        "services": {
            "api": shared, "mcp": shared,
            "frontend": {"image": candidate["frontend_image"], "pull_policy": "never"},
            "worker": {"profiles": ["legacy-only"]},
        },
        "volumes": {"v2-prepared-attachments": {"name": target_volume, "external": True}},
    }


class Runner:
    def __init__(self, log):
        self.log = log

    def docker(self, *args: str, source: Path | None = None, capture: bool = False) -> str:
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"ZEICHEN_PREPARED_DATABASE_URL", "COMPOSE_PROFILES", "COMPOSE_FILE"}}
        with (source.open("rb") if source is not None else nullcontext(subprocess.DEVNULL)) as stream:
            result = subprocess.run(
                ["docker", *args], stdin=stream, stdout=subprocess.PIPE if capture else self.log,
                stderr=self.log, check=True, env=environment,
            )
        return result.stdout.decode("utf-8").strip() if capture else ""


class Preparation:
    def __init__(self, args, run):
        self.args = args
        self.run = run
        self.output = args.output
        self.record = {
            "status": "preparing", "started_at": datetime.now(UTC).isoformat(),
            "target_database": args.target, "postgres_container": args.postgres, "network": args.network,
            "source_database": "zeichen", "source_application_writes_frozen_attested": True,
        }
        self.phase = "validate_inputs"

    def save(self, status: str) -> None:
        self.record.update(status=status, phase=self.phase)
        write_json(self.output / "prepared.json", self.record)

    def psql(self, query: str) -> str:
        return self.run.docker(
            "exec", self.args.postgres, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-A", "-t",
            "-U", self.role, "-d", self.args.target, "-c", query, capture=True,
        )

    def counts(self) -> dict[str, int]:
        sql = " UNION ALL ".join(f'SELECT \'{table}\', count(*) FROM "{table}"' for table in TABLES)
        rows = dict(row.split("|", 1) for row in self.psql(sql).splitlines())
        if set(rows) != set(TABLES):
            raise RuntimeError("incomplete clone count check")
        return {key: int(count) for key, count in rows.items()}

    def blank_volume(self, name: str, token: str) -> None:
        self.run.docker("volume", "create", "--label", f"zeichen.cutover={token}", name)
        label = self.run.docker(
            "volume", "inspect", "--format", '{{index .Labels "zeichen.cutover"}}', name, capture=True,
        )
        if label != token:
            raise RuntimeError("refusing to use a pre-existing volume")

    def verify_activation(self, source: Path, overlay: Path, env: Path, candidate: dict,
                          dsn: str, target_volume: str) -> None:
        config = json.loads(self.run.docker(
            "compose", "-p", "zeichen", "--env-file", str(env), "-f", str(source), "-f", str(overlay),
            "config", "--format", "json", capture=True,
        ))
        services = config["services"]
        expected_mount = "/srv/zeichen/storage/attachments"
        if "worker" in services or services["frontend"]["image"] != candidate["frontend_image"]:
            raise RuntimeError("activation must omit legacy worker and pin candidate frontend")
        if config["volumes"]["v2-prepared-attachments"] != {"name": target_volume, "external": True}:
            raise RuntimeError("activation must use the prepared external file volume")
        for name in ("api", "mcp"):
            service = services[name]
            mounts = [item for item in service["volumes"] if item["target"] == expected_mount]
            networks = {config["networks"][key]["name"] for key in service["networks"]}
            if (service["image"] != candidate["backend_image"] or service["environment"]["DATABASE_URL"] != dsn
                    or len(mounts) != 1 or mounts[0]["source"] != "v2-prepared-attachments"
                    or self.args.network not in networks):
                raise RuntimeError(f"activation {name} does not target the prepared database and file volume")

    def prepare(self) -> None:
        args = self.args
        source = {
            name: snapshot_file(args.snapshot, name)
            for name in ("postgres.dump", "attachments.tar.gz", "compose.json", "nginx.conf")
        }
        compose = json.loads(source["compose.json"].read_text(encoding="utf-8"))
        self.role, host, dsn = target_connection(compose, args.target)
        old_images = rollback_images(compose)
        candidate_checksum = fingerprint(args.candidate)
        candidate = candidate_record(args.candidate)
        new_ingress = snapshot_file(args.candidate.parent / "source" / "deploy", "nginx.conf")
        original_ingress = source["nginx.conf"].read_bytes().decode("utf-8")
        staged_ingress = new_ingress.read_bytes().decode("utf-8")
        protect_ingress(original_ingress, staged_ingress)

        container = json.loads(self.run.docker("inspect", args.postgres, capture=True))[0]
        attached = container["NetworkSettings"]["Networks"].get(args.network)
        names = {(container.get("Name") or "").lstrip("/").casefold()}
        if attached is not None:
            names.update(alias.casefold() for alias in (attached.get("Aliases") or []))
            if attached.get("IPAddress"):
                names.add(attached["IPAddress"])
        if attached is None or host.casefold() not in names:
            raise ValueError("snapshot database hostname must identify the selected PostgreSQL network/container")
        for image in set(old_images.values()) | {candidate["backend_image"], candidate["frontend_image"]}:
            actual = self.run.docker("image", "inspect", "--format", "{{.Id}}", image, capture=True)
            if actual != image:
                raise RuntimeError("candidate or rollback image has an unexpected identity")

        target_env = self.output / "database.env"
        private_file(target_env, f"DATABASE_URL={dsn}\n")
        token = uuid.uuid4().hex
        target_volume = f"{args.target}_files_{token[:10]}"
        legacy_volume = f"{args.target}_legacy_ro_{token[:10]}"
        checksums = {key: fingerprint(path) for key, path in source.items()}
        self.record.update({
            "target_attachment_volume": target_volume, "legacy_import_volume": legacy_volume,
            "volume_owner_token": token,
            "candidate_commit": candidate["commit"], "backend_image": candidate["backend_image"],
            "frontend_image": candidate["frontend_image"], "alembic_target": candidate["database_target"],
            "postgres_container_id": container["Id"], "snapshot_root": str(args.snapshot),
            "snapshot_sha256": checksums, "candidate_result_sha256": candidate_checksum,
            "rollback_images": old_images,
            "created_resources": [],
        })
        self.phase = "restore_database"
        self.save("preparing")
        self.run.docker("exec", args.postgres, "createdb", "-U", self.role, "--maintenance-db=postgres",
                        "--template=template0", "--owner", self.role, args.target)
        self.record["created_resources"].append({"database": args.target})
        self.save("preparing")
        self.run.docker(
            "exec", "-i", args.postgres, "pg_restore", "--exit-on-error", "--single-transaction",
            "--no-owner", "--no-privileges", "-U", self.role, "--dbname", args.target,
            source=source["postgres.dump"],
        )
        if self.psql("SELECT version_num FROM alembic_version") != SOURCE_REVISION:
            raise RuntimeError("clone dump does not match the supported v1 Alembic revision")
        self.record["legacy_counts"] = self.counts()

        self.phase = "restore_files"
        for volume in (legacy_volume, target_volume):
            self.blank_volume(volume, token)
            self.record["created_resources"].append({"volume": volume})
            self.save("preparing")
            self.run.docker(
                "run", "--rm", "-i", "--network", "none",
                "--mount", f"type=volume,src={volume},dst=/restore",
                "--entrypoint", "python", candidate["backend_image"], "-c", EXTRACT, "/restore",
                source=source["attachments.tar.gz"],
            )

        self.phase = "migrate_clone"
        app = ["run", "--rm", "--network", args.network, "--env-file", str(target_env)]
        self.run.docker(*app, "--entrypoint", "alembic", candidate["backend_image"], "upgrade", "head")
        if self.psql("SELECT version_num FROM alembic_version") != candidate["database_target"]:
            raise RuntimeError("clone did not reach the verified candidate Alembic head")

        self.phase = "import_legacy"
        report_path = self.output / "import-report.json"
        report_text = self.run.docker(
            *app, "-e", "ATTACHMENT_STORAGE_DIR=/target",
            "--mount", f"type=volume,src={legacy_volume},dst=/legacy,readonly",
            "--mount", f"type=volume,src={target_volume},dst=/target",
            "--entrypoint", "sh", candidate["backend_image"], "-c", IMPORT, "cutover", args.target,
            capture=True,
        )
        report = json.loads(report_text)
        if report.get("target") != args.target or not all(key in report for key in ("files", "timeline", "wiki", "exceptions")):
            raise RuntimeError("unexpected legacy import report")
        private_file(report_path, report_text + "\n")
        self.phase = "verify_preparation"
        if self.counts() != self.record["legacy_counts"]:
            raise RuntimeError("legacy entity counts changed during clone migration/import")
        if any(fingerprint(source[key]) != expected for key, expected in checksums.items()):
            raise RuntimeError("snapshot inputs changed during preparation")
        if fingerprint(args.candidate) != candidate_checksum or new_ingress.read_bytes().decode("utf-8") != staged_ingress:
            raise RuntimeError("candidate inputs changed during preparation")
        private_file(self.output / "nginx.candidate.conf", staged_ingress)
        overlay = self.output / "activation.override.json"
        write_json(overlay, activation_overlay(candidate, target_volume))
        activation_env = self.output / "activation.env"
        private_file(activation_env, f"ZEICHEN_PREPARED_DATABASE_URL={dsn}\n")
        self.verify_activation(source["compose.json"], overlay, activation_env, candidate, dsn, target_volume)
        self.record.update({
            "import_report_sha256": fingerprint(report_path),
            "import_counts": {name: report[name] for name in ("files", "timeline", "wiki")},
            "import_exception_counts": {domain: len(items) for domain, items in report["exceptions"].items()},
            "candidate_ingress_sha256": fingerprint(self.output / "nginx.candidate.conf"),
            "activation_override_sha256": fingerprint(overlay),
            "activation": {
                "runs_automatically": False,
                "requires_accepted_ac_01_through_31_and_rehearsed_restore": True,
                "requires_frozen_legacy_writes": True,
                "database_env_file": "activation.env", "attachment_volume": target_volume,
                "nginx_file": "nginx.candidate.conf", "start_services": ["api", "mcp", "frontend"],
                "compose_base": str(source["compose.json"]), "compose_override": "activation.override.json",
                "keep_stopped": ["worker"], "enable_maintenance_after_health": True,
                "unset_before_compose": ["ZEICHEN_PREPARED_DATABASE_URL", "COMPOSE_PROFILES", "COMPOSE_FILE"],
                "start_command": [
                    "docker", "compose", "-p", "zeichen", "--env-file", str(activation_env),
                    "-f", str(source["compose.json"]), "-f", str(overlay),
                    "up", "-d", "--no-deps", "--no-build", "--wait", "--wait-timeout", "150",
                    "api", "mcp", "frontend",
                ],
                "steps_after_start": [
                    "Check candidate images, prepared database and volume, and application health while writes stay blocked.",
                    "Validate the prepared ingress and update the Zeichen block in-place; do not recreate nginx or PostgreSQL.",
                    "Verify Web, MCP and unchanged MochiSite before opening writes.",
                    "Run one-shot maintenance with the activated database, attachment volume, network and image, then enable its timer.",
                ],
            },
            "rollback_before_v2_writes": [
                "Disable v2 maintenance and stop v2 api/mcp/frontend.",
                "Restore pinned v1 services and their database/volume from the snapshot Compose configuration.",
                "Restore the Zeichen ingress bytes in place, validate and reload the shared gateway.",
                "Verify v1 and MochiSite health before resuming legacy writes.",
            ],
            "rollback_after_v2_writes": "Freeze and preserve v2 changes before choosing corrective migration or rollback.",
        })
        self.phase = "prepared"
        self.save("prepared")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True, help="Private v1 backup directory")
    parser.add_argument("--candidate", type=Path, required=True, help="Verified result.json from -CheckOnly")
    parser.add_argument("--output", type=Path, required=True, help="New private evidence directory, must not exist")
    parser.add_argument("--postgres", required=True, help="Existing PostgreSQL container for the clone")
    parser.add_argument("--network", required=True, help="Docker network used by migration containers")
    parser.add_argument("--target", required=True, help="Unused zeichen_v2_* database name")
    parser.add_argument("--snapshot-writes-frozen", action="store_true", required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"zeichen_v2_[a-z0-9_]{1,28}", args.target):
        parser.error("--target must be a new zeichen_v2_* database (up to 28 suffix characters)")
    if not NAME.fullmatch(args.postgres) or not NAME.fullmatch(args.network) or args.network in {"none", "host"}:
        parser.error("explicit PostgreSQL container and application network names required")
    os.umask(0o077)
    args.snapshot = args.snapshot.resolve(strict=True)
    args.candidate = args.candidate.resolve(strict=True)
    if args.snapshot.stat().st_mode & 0o077:
        parser.error("snapshot directory must be private")
    args.output = args.output.resolve()
    args.output.mkdir(mode=0o700)
    with (args.output / "prepare.log").open("xb") as log:
        item = Preparation(args, Runner(log))
        try:
            item.prepare()
        except Exception as error:
            # Subprocess errors and supplied Compose may contain secrets.
            item.record["error_type"] = type(error).__name__
            item.save("failed")
            print(f"Preparation failed during {item.phase}. Review {args.output / 'prepared.json'} and private prepare.log.")
            return 1
    print(f"Prepared v2 clone; activation has not run. Review {args.output / 'prepared.json'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
