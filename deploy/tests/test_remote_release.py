"""Release safety boundaries; run on the remote build host, not production DB."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

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


if __name__ == "__main__":
    unittest.main()
