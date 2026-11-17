"""Cutover preparation tests use synthetic snapshots and no PostgreSQL daemon."""

import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare_v2_cutover as cutover


OLD = "sha256:" + "0" * 64
BACKEND = "sha256:" + "1" * 64
FRONTEND = "sha256:" + "2" * 64
TARGET = "zeichen_v2_fixture"
NEXT = "v2example"
AVATAR = b"legacy avatar bytes"
INGRESS = (
    "MochiSite\n# ---------- 贼船 Zeichen ----------\nproxy_pass OLD;\n"
    "# ---------- 兜底: keep shared settings\n"
)


def make_tar(contents, *, symlink=None) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, value in contents.items():
            member = tarfile.TarInfo(name)
            member.size = len(value)
            archive.addfile(member, io.BytesIO(value))
        if symlink is not None:
            member = tarfile.TarInfo(symlink)
            member.type = tarfile.SYMTYPE
            member.linkname = "/outside"
            archive.addfile(member)
    return output.getvalue()


class DockerFixture:
    def __init__(self, directory, *, fail_restore=False):
        self.directory = directory
        self.calls = []
        self.labels = {}
        self.migrated = False
        self.fail_restore = fail_restore

    def docker(self, *args, source=None, capture=False):
        self.calls.append(args)
        if args[0] == "inspect":
            return json.dumps([{
                "Id": "postgres-fixture", "Name": "/fixture-db",
                "NetworkSettings": {"Networks": {"fixture-net": {"Aliases": ["postgres"]}}},
            }])
        if args[:2] == ("image", "inspect"):
            return args[-1]
        if args[0] == "exec":
            if "pg_restore" in args:
                assert source.read_bytes() == b"synthetic pg_custom placeholder"
                assert args[args.index("--dbname") + 1] == TARGET
                if self.fail_restore:
                    raise subprocess.CalledProcessError(2, ["pg_restore", "private diagnostic"])
            elif "createdb" in args:
                assert args[-1] == TARGET
            elif "psql" in args:
                assert args[args.index("-d") + 1] == TARGET
                if args[-1].startswith("SELECT version_num"):
                    return NEXT if self.migrated else cutover.SOURCE_REVISION
                return "\n".join(f"{table}|1" for table in cutover.TABLES)
            return ""
        if args[:2] == ("volume", "create"):
            self.labels[args[-1]] = args[-2].split("=", 1)[1]
            (self.directory / args[-1]).mkdir()
            return ""
        if args[:2] == ("volume", "inspect"):
            return self.labels[args[-1]]
        if args[0] == "run":
            program = args[args.index("--entrypoint") + 1]
            if program == "python":
                self.assert_archive_restored(args, source)
            elif program == "alembic":
                assert args[-2:] == ("upgrade", "head")
                self.migrated = True
            else:
                assert program == "sh" and self.migrated
                assert "--target" in cutover.IMPORT and args[-1] == TARGET
                self.assert_target_environment(args)
                assert any("dst=/legacy,readonly" in flag for flag in args)
                assert any("dst=/target" in flag for flag in args)
                assert len(self.labels) == 2
                assert all((self.directory / volume / "avatar.jpg").read_bytes() == AVATAR for volume in self.labels)
                return json.dumps({"target": TARGET, "files": {"legacy_files": 1}, "wiki": {},
                                   "timeline": {}, "exceptions": {"files": []}})
            return ""
        if args[0] == "compose":
            overlay = json.loads(Path(args[-4]).read_text(encoding="utf-8"))
            target_volume = overlay["volumes"]["v2-prepared-attachments"]
            assert target_volume["name"] in self.labels and target_volume["external"]
            prepared = {
                "image": BACKEND, "environment": {"DATABASE_URL": f"postgresql+psycopg://zeichen:test@postgres/{TARGET}"},
                "volumes": [{"target": "/srv/zeichen/storage/attachments", "source": "v2-prepared-attachments"}],
                "networks": {"default": {}},
            }
            assert overlay["services"]["worker"]["profiles"] == ["legacy-only"]
            return json.dumps({"services": {"api": prepared, "mcp": prepared, "frontend": {"image": FRONTEND}},
                               "networks": {"default": {"name": "fixture-net"}}, "volumes": overlay["volumes"]})
        raise AssertionError(f"unexpected Docker operation {args[0]}")

    def assert_archive_restored(self, args, source):
        assert args[args.index("--network") + 1] == "none"
        destination = self.directory / args[args.index("--mount") + 1].split(",")[1].split("=", 1)[1]
        subprocess.run(
            [sys.executable, "-c", cutover.EXTRACT, str(destination)], input=source.read_bytes(), check=True,
        )

    def assert_target_environment(self, args):
        env = Path(args[args.index("--env-file") + 1]).read_text(encoding="utf-8")
        assert env == f"DATABASE_URL=postgresql+psycopg://zeichen:test@postgres/{TARGET}\n"


class CutoverTests(unittest.TestCase):
    def fixtures(self, root):
        snapshot = root / "snapshot"
        snapshot.mkdir(mode=0o700)
        (snapshot / "postgres.dump").write_bytes(b"synthetic pg_custom placeholder")
        (snapshot / "attachments.tar.gz").write_bytes(make_tar({"avatar.jpg": AVATAR}))
        (snapshot / "nginx.conf").write_text(INGRESS, encoding="utf-8")
        services = {name: {"image": OLD, "environment": {"DATABASE_URL": "postgresql+psycopg://zeichen:test@postgres/zeichen"}}
                    for name in ("api", "mcp", "worker", "frontend")}
        (snapshot / "compose.json").write_text(json.dumps({"services": services}), encoding="utf-8")
        evidence = root / "evidence"
        candidate_source = evidence / "source" / "deploy"
        candidate_source.mkdir(parents=True)
        (candidate_source / "nginx.conf").write_text(INGRESS.replace("proxy_pass OLD", "proxy_pass NEW"),
                                                     encoding="utf-8")
        candidate = evidence / "result.json"
        candidate.write_text(json.dumps({
            "mode": "candidate", "status": "verified", "commit": "a" * 40,
            "backend_image": BACKEND, "frontend_image": FRONTEND, "database_target": NEXT,
        }), encoding="utf-8")
        output = root / "output"
        options = ["--snapshot", str(snapshot), "--candidate", str(candidate), "--output", str(output),
                   "--postgres", "fixture-db", "--network", "fixture-net", "--target", TARGET,
                   "--snapshot-writes-frozen"]
        return snapshot, output, options

    def run_fixture(self, options, docker):
        previous_umask = os.umask(0o077)
        try:
            with patch.object(cutover, "Runner", return_value=docker), redirect_stdout(io.StringIO()):
                return cutover.main(options)
        finally:
            os.umask(previous_umask)

    def test_prepares_distinct_clone_and_files_and_records_no_activation(self):
        with tempfile.TemporaryDirectory() as path:
            directory = Path(path)
            source, output, options = self.fixtures(directory)
            before = cutover.fingerprint(source / "attachments.tar.gz")
            docker = DockerFixture(directory)
            self.assertEqual(self.run_fixture(options, docker), 0)
            result = json.loads((output / "prepared.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "prepared")
            self.assertEqual(result["target_database"], TARGET)
            self.assertNotEqual(result["target_attachment_volume"], result["legacy_import_volume"])
            self.assertEqual(result["activation"]["start_services"], ["api", "mcp", "frontend"])
            self.assertEqual(result["snapshot_sha256"]["attachments.tar.gz"], before)
            self.assertEqual(cutover.fingerprint(source / "attachments.tar.gz"), before)
            self.assertEqual(result["import_report_sha256"], cutover.fingerprint(output / "import-report.json"))
            self.assertFalse(any({"up", "dropdb", "stop", "restart", "reload"} & set(call) for call in docker.calls))
            self.assertEqual((output / "activation.env").stat().st_mode & 0o777, 0o600)
            self.assertNotIn("zeichen:test", json.dumps(result))

    def test_restore_failure_records_only_new_database_and_stops(self):
        with tempfile.TemporaryDirectory() as path:
            directory = Path(path)
            _, output, options = self.fixtures(directory)
            docker = DockerFixture(directory, fail_restore=True)
            self.assertEqual(self.run_fixture(options, docker), 1)
            result = json.loads((output / "prepared.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["phase"], "restore_database")
            self.assertEqual(result["created_resources"], [{"database": TARGET}])
            self.assertFalse(docker.labels)
            self.assertNotIn("private diagnostic", json.dumps(result))

    def test_rejects_tar_escape_symlink_and_truncated_archive(self):
        valid = make_tar({"avatar.jpg": AVATAR})
        archives = (
            make_tar({"../outside": b"escape"}),
            make_tar({}, symlink="linked"),
            valid[:-8],
        )
        for source in archives:
            with self.subTest(length=len(source)), tempfile.TemporaryDirectory() as directory:
                process = subprocess.run(
                    [sys.executable, "-c", cutover.EXTRACT, directory], input=source, capture_output=True,
                )
                self.assertNotEqual(process.returncode, 0)


if __name__ == "__main__":
    unittest.main()
