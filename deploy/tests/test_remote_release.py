"""Release safety boundaries; run on the remote build host, not production DB."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location("release", Path(__file__).parents[1] / "remote_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class SafetyTests(unittest.TestCase):
    def test_image_default_command_and_no_mounts_are_valid(self):
        config = {"services": {name: {"command": None, "volumes": None} for name in release.SERVICES}}
        release.validate_release_config(config)

    def test_shared_ingress_preserves_other_site_and_acme(self):
        old = "HTTP/ACME\nMOCHI\n# ---------- 贼船 Zeichen ----------\nold\n# ---------- 兜底: unchanged"
        release.protect_ingress(old, old.replace("\nold\n", "\nnew\n"))
        for altered in (old.replace("MOCHI", "BROKEN"), old.replace("ACME", "BROKEN"), old.replace("unchanged", "BROKEN")):
            with self.assertRaises(RuntimeError):
                release.protect_ingress(old, altered)

    def test_source_mount_reload_or_public_port_rejected(self):
        for violation in ({"volumes": [{"type": "bind"}]}, {"command": ["uvicorn", "--reload"]}, {"ports": [8000]}):
            config = {"services": {name: {} for name in release.SERVICES}}
            config["services"]["api"] = violation
            with self.assertRaises(RuntimeError):
                release.validate_release_config(config)

    def test_repository_sync_preserves_live_nginx_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
            git("init", "-b", "develop")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "test")
            (root / "deploy").mkdir()
            nginx = root / "deploy/nginx.conf"
            nginx.write_text("old")
            (root / "app.py").write_text("old")
            git("add", ".")
            git("commit", "-m", "old")
            old = git("rev-parse", "HEAD")
            nginx.write_text("new")
            (root / "app.py").write_text("new")
            git("add", ".")
            git("commit", "-m", "new")
            new = git("rev-parse", "HEAD")
            git("reset", "--hard", old)
            inode = nginx.stat().st_ino
            nginx.write_text("new")
            release.sync_repository(root, new, old)
            self.assertEqual(nginx.stat().st_ino, inode)
            self.assertEqual(git("status", "--porcelain"), "")
            self.assertEqual(git("rev-parse", "HEAD"), new)

    def fake_release(self):
        item = release.Release.__new__(release.Release)
        item.root = Path("/fake")
        item.args = Mock(commit="new", allow_migration=False)
        item.old_head = "old"
        item.old_revision = item.target_revision = "schema"
        item.command = ["docker", "compose", "-f", "new.json"]
        item.environment = {}
        item.backup = Mock()
        item.save = Mock()
        item.db_revision = Mock(return_value="schema")
        item.verify_live = Mock(side_effect=RuntimeError("health failed"))
        item.reload_gateway = Mock()
        item.new_nginx, item.old_nginx = "new", "old"
        item.previous_services = ["api", "mcp", "worker"]
        item.rollback_file = Path("old.json")
        item.directory = Path("/evidence")
        item.compose = Mock(return_value=["docker", "compose", "-f", "old.json"])
        return item

    @patch.object(release, "worktree_changes", return_value="")
    @patch.object(release, "run", return_value="old")
    def test_failed_health_rolls_back_only_apps_without_restoring_database(self, command, changes):
        item = self.fake_release()
        with self.assertRaisesRegex(RuntimeError, "health failed"):
            item.activate()
        item.save.assert_called_with("rolled_back")
        item.reload_gateway.assert_called_with("old")
        commands = [call.args[0] for call in command.call_args_list]
        rollback = next(c for c in commands if "old.json" in c)
        self.assertNotIn("web", rollback)
        self.assertNotIn("postgres", rollback)
        self.assertNotIn("down", rollback)
        self.assertEqual(rollback[-3:], ["api", "mcp", "worker"])

    @patch.object(release, "worktree_changes", return_value="")
    @patch.object(release, "run", return_value="old")
    def test_schema_change_prevents_automatic_code_or_data_rollback(self, command, changes):
        item = self.fake_release()
        item.target_revision = "new-schema"
        item.db_revision.side_effect = ["schema", "new-schema"]
        with self.assertRaisesRegex(RuntimeError, "health failed"):
            item.activate()
        item.save.assert_called_with("manual_recovery_required")
        self.assertFalse(any("old.json" in call.args[0] for call in command.call_args_list))

    @patch.object(release.Release, "activate")
    @patch.object(release.Release, "preflight")
    @patch.object(release.Release, "compose")
    @patch.object(release.Release, "test_migration")
    @patch.object(release, "inspect", return_value={"Id": "sha256:fixture"})
    @patch.object(release, "run", return_value="candidate-head (head)")
    @patch.object(release.shutil, "disk_usage", return_value=Mock(free=10 * 1024**3))
    def test_candidate_checks_use_disposable_builds_and_skip_production(
        self, disk_usage, command, inspect, migrate, compose, preflight, activate
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "archive"
            source.mkdir()
            state = root / "checks"
            args = ["remote_release.py", "--candidate-source", str(source),
                    "--root", str(state), "--commit", "a" * 40, "--check-only"]
            with patch.object(sys, "argv", args):
                release.main()
            results = list(state.glob("*/result.json"))
            self.assertEqual(len(results), 1)
            self.assertIn('"database_target": "candidate-head"', results[0].read_text())
            self.assertIn('"status": "verified"', results[0].read_text())
        preflight.assert_not_called()
        activate.assert_not_called()
        compose.assert_not_called()
        migrate.assert_called_once_with("zeichen-check-backend-test:" + "a" * 40)
        for call in command.call_args_list:
            cmd = call.args[0]
            self.assertEqual(cmd[0], "docker")
            if cmd[1] == "run":
                self.assertEqual(cmd[cmd.index("--network") + 1], "none")
                self.assertNotIn("-v", cmd)
        self.assertTrue(any("/workspace/deploy/tests" in call.args[0] for call in command.call_args_list))

    @patch.object(release.Release, "activate")
    def test_candidate_source_cannot_activate(self, activate):
        args = ["remote_release.py", "--candidate-source", "/fake",
                "--root", "/fake", "--commit", "a" * 40]
        with patch.object(sys, "argv", args), self.assertRaises(SystemExit) as error:
            release.main()
        self.assertEqual(error.exception.code, 2)
        activate.assert_not_called()


class V2ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / ".release"
        self.working = self.state / "cutover-example"
        self.prepared = self.working / "prepared"
        self.prepared.mkdir(parents=True)
        self.candidate = "a" * 40
        self.backend, self.frontend = ("sha256:" + digit * 64 for digit in "bc")
        self.new_backend, self.new_frontend = ("sha256:" + digit * 64 for digit in "de")
        self.schema = "v2timelinefiles"
        self.database = "zeichen_v2_example"
        self.token = "a" * 32
        self.volume = f"{self.database}_files_{self.token[:10]}"
        self.dsn = f"postgresql+psycopg://zeichen:synthetic@postgres:5432/{self.database}"
        self.network = "zeichen_default"
        self.ingress = "MOCHI\n# ---------- 贼船 Zeichen ----------\na\n# ---------- 兜底: fallback\n"
        self.new_ingress = self.ingress.replace("\na\n", "\nb\n")
        (self.root / "deploy").mkdir()
        self.ingress_path = self.root / "deploy" / "nginx.conf"
        self.ingress_path.write_text(self.ingress, encoding="utf-8")
        self.manifest_path = self.prepared / "prepared.json"
        self.acceptance = self.working / "acceptance.json"
        self.journal = self.working / "status.json"
        self.snapshot = self.working / "snapshot" / "compose.json"
        self.snapshot.parent.mkdir()
        release.write_json(self.snapshot, {"services": {
            name: {"environment": {"DATABASE_URL": self.dsn.rsplit("/", 1)[0] + "/zeichen"}}
            for name in ("api", "mcp")
        }})
        overlay = self.prepared / "activation.override.json"
        release.write_json(overlay, {"fixture": True})
        (self.prepared / "activation.env").write_text(f"ZEICHEN_PREPARED_DATABASE_URL={self.dsn}\n")
        release.write_json(self.manifest_path, {
            "status": "prepared", "candidate_commit": self.candidate, "postgres_container_id": "postgres",
            "activation_override_sha256": release.digest(overlay.read_bytes()),
            "candidate_ingress_sha256": release.digest(self.ingress_path.read_bytes()),
            "target_database": self.database, "target_attachment_volume": self.volume, "volume_owner_token": self.token,
            "network": self.network, "alembic_target": self.schema,
            "backend_image": self.backend, "frontend_image": self.frontend,
        })
        self.manifest_hash = release.digest(self.manifest_path.read_bytes())
        release.write_json(self.acceptance, {
            "prepared_manifest_sha256": self.manifest_hash, "candidate_commit": self.candidate,
            "migration_exceptions_reviewed": True,
        })
        ingress_stat = self.ingress_path.stat()
        self.journal_data = {
            "phase": "active", "writes_may_exist": True, "prepared": str(self.manifest_path),
            "acceptance": str(self.acceptance), "postgres_id": "postgres", "gateway_id": "gateway",
            "ingress_identity": [ingress_stat.st_dev, ingress_stat.st_ino],
            "rollback_compose_sha256": release.digest(self.snapshot.read_bytes()),
        }
        release.write_json(self.journal, self.journal_data)
        release.write_json(self.state / release.V2_MARKER, {"state": str(self.working)})
        self.template = self.working / "maintenance.env"
        self.installed = self.state / "v2-maintenance.env"
        (self.root / release.V2_MAINTENANCE).write_text("# maintenance fixture\n")
        self.maintenance = (
            f"ZEICHEN_BACKEND_IMAGE={self.backend}\nZEICHEN_MAINTENANCE_DATABASE_URL={self.dsn}\n"
            f"ZEICHEN_MAINTENANCE_VOLUME={self.volume}\nZEICHEN_MAINTENANCE_NETWORK={self.network}\n"
        ).encode()
        self.template.write_bytes(self.maintenance)
        self.installed.write_bytes(self.maintenance)

        self.item = release.V2Release.__new__(release.V2Release)
        self.item.args = Mock(commit="f" * 40, allow_migration=False)
        self.item.root = self.root
        self.item.state = self.state
        self.item.directory = self.state / "routine"
        self.item.directory.mkdir()
        self.item.source = self.item.directory / "source"
        (self.item.source / "deploy").mkdir(parents=True)
        (self.item.source / "deploy" / "nginx.conf").write_text(self.new_ingress, encoding="utf-8")
        (self.item.source / release.V2_MAINTENANCE).write_text("# maintenance fixture\n")
        self.item.environment = {"COMPOSE_PROFILES": "legacy-only"}
        self.item.record = {"commit": self.item.args.commit, "backend_image": self.new_backend,
                            "frontend_image": self.new_frontend}
        self.item.backend = self.new_backend
        self.item.frontend = self.new_frontend
        self.item.target_revision = self.schema
        self.head = "1" * 40
        self.live_backend, self.live_frontend = self.backend, self.frontend
        self.running = True
        self.commands = []

    def docker_inspect(self, name):
        service = name.removeprefix("zeichen-").removesuffix("-1")
        if service == "postgres":
            return {"Id": "postgres", "NetworkSettings": {"Networks": {self.network: {}}}}
        if service == "web":
            return {"Id": "gateway"}
        if service == "worker":
            return {"State": {"Running": False}}
        return {
            "Image": self.live_frontend if service == "frontend" else self.live_backend,
            "State": {"Running": self.running},
            "NetworkSettings": {"Networks": {self.network: {}}},
            "Config": {"Env": [f"DATABASE_URL={self.dsn}"], "Labels": {
                "com.docker.compose.project": "zeichen", "com.docker.compose.service": service,
            }},
            "Mounts": [{"Destination": release.V2_ATTACHMENTS, "Type": "volume", "Name": self.volume}],
        }

    def command(self, args, **kwargs):
        cmd = [str(value) for value in args]
        self.commands.append(cmd)
        if cmd[0] == "git":
            return {("branch", "--show-current"): "develop", ("rev-parse", "HEAD"): self.head}.get(tuple(cmd[1:]), "")
        if cmd[:3] == ["docker", "volume", "inspect"]:
            return self.token
        if cmd[:4] == ["docker", "exec", "zeichen-postgres-1", "psql"]:
            return self.schema
        if kwargs.get("output") is not None:
            kwargs["output"].write(b"synthetic backup")
        if cmd[-5:] == ["stop", "--timeout", "45", "api", "mcp"]:
            self.running = False
        if cmd[-3:] == list(release.V2_SERVICES) or cmd[-3:] == ["config", "--format", "json"]:
            overlay = [cmd[index + 1] for index, argument in enumerate(cmd) if argument == "-f"][-1]
            images = json.loads(Path(overlay).read_text())["services"]
            if cmd[-3:] == list(release.V2_SERVICES):
                self.running = True
                self.live_backend, self.live_frontend = images["api"]["image"], images["frontend"]["image"]
            else:
                return json.dumps({"services": {
                    name: {**image, "environment": {"DATABASE_URL": self.dsn}, "networks": ["database"],
                           "volumes": [{"target": release.V2_ATTACHMENTS, "type": "volume", "source": "files"}]}
                    for name, image in images.items()
                }, "networks": {"database": {"name": self.network}},
                    "volumes": {"files": {"name": self.volume, "external": True}}})

    def setup_mocks(self):
        for name, override in (
            ("run", Mock(side_effect=self.command)), ("inspect", Mock(side_effect=self.docker_inspect)),
            ("http_get", Mock(return_value=b"synthetic mochi")),
            ("sync_repository", Mock(side_effect=lambda _root, revision, _old: setattr(self, "head", revision))),
        ):
            patcher = patch.object(release, name, override)
            patcher.start()
            self.addCleanup(patcher.stop)
        disk = patch.object(release.shutil, "disk_usage", return_value=Mock(free=10 * 1024**3))
        disk.start()
        self.addCleanup(disk.stop)
        self.item.reload_gateway = Mock(side_effect=lambda conf: self.ingress_path.write_text(conf, encoding="utf-8"))
        self.item.verify_live = Mock()

    def test_incomplete_cutover_and_changed_schema_fail_closed(self):
        self.setup_mocks()
        release.write_json(self.journal, {**self.journal_data, "phase": "staged"})
        with self.assertRaisesRegex(RuntimeError, "active, write-open"):
            self.item.preflight()
        self.assertEqual(self.commands, [])
        release.write_json(self.journal, self.journal_data)
        self.item.preflight()
        self.item.target_revision = "v2different"
        with self.assertRaisesRegex(RuntimeError, "active Alembic head"):
            self.item.configure_release()
        self.assertFalse(any("up" in command for command in self.commands))

    def test_publishes_and_preflights_again_on_same_resources(self):
        self.setup_mocks()
        self.item.preflight()
        self.assertNotIn("COMPOSE_PROFILES", self.item.environment)
        self.item.configure_release()
        self.item.activate()
        result = json.loads((self.state / "v2-current.json").read_text())
        self.assertEqual(result["status"], "deployed")
        self.assertEqual(result["attachment_volume"], self.volume)
        self.assertEqual(result["database_after"], self.schema)
        self.assertEqual(self.ingress_path.read_text(encoding="utf-8"), self.new_ingress)
        self.assertEqual(self.installed.read_bytes(), self.maintenance.replace(self.backend.encode(), self.new_backend.encode(), 1))
        backup = Path(result["backup"])
        self.assertEqual((backup / "postgres.dump").read_bytes(), b"synthetic backup")
        dumped = next(command for command in self.commands if "pg_dump" in command)
        self.assertEqual(dumped[-2:], ["-d", self.database])
        archived = next(command for command in self.commands if release.V2_ARCHIVE in command)
        self.assertIn(f"type=volume,src={self.volume},dst=/attachments,readonly", archived)
        self.assertEqual([command[-3:] for command in self.commands if "up" in command], [list(release.V2_SERVICES)])
        self.assertEqual(json.loads(self.journal.read_text()), self.journal_data)
        self.item.preflight()
        self.assertEqual(self.item.previous_images["api"], self.new_backend)
        self.assertEqual(self.item.previous_images["frontend"], self.new_frontend)

    def test_failed_health_restores_v2_images_and_keeps_the_active_clone(self):
        self.setup_mocks()
        self.item.verify_live.side_effect = [RuntimeError("failed app health"), None]
        self.item.preflight()
        self.item.configure_release()
        with self.assertRaisesRegex(RuntimeError, "failed app health"):
            self.item.activate()
        self.assertEqual(self.item.record["status"], "rolled_back")
        self.assertEqual(self.live_backend, self.backend)
        self.assertEqual(self.live_frontend, self.frontend)
        self.assertEqual(self.installed.read_bytes(), self.maintenance)
        self.assertEqual(self.ingress_path.read_text(encoding="utf-8"), self.ingress)
        self.assertFalse((self.state / "v2-current.json").exists())
        self.assertFalse(any("pg_restore" in command or "down" in command for command in self.commands))


if __name__ == "__main__":
    unittest.main()
