import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cutover_ingress import FALLBACK, MOCHI, ZEICHEN, gate
from cutover_v2 import ACCEPTANCE_IDS, Cutover, GATEWAY, POSTGRES, WRITERS, fingerprint, validate_acceptance


INGRESS = (Path(__file__).parents[1] / "nginx.conf").read_text(encoding="utf-8")
OLD = "sha256:" + "0" * 64
BACKEND = "sha256:" + "1" * 64
FRONTEND = "sha256:" + "2" * 64
SHA = "a" * 40
V1 = "postgresql+psycopg://zeichen:fixture@postgres/zeichen"


class CutoverTests(unittest.TestCase):
    def state(self, directory):
        root = Path(directory)
        (root / ".release").mkdir()
        working = root / ".release" / "cutover-fixture"
        working.mkdir()
        (root / "deploy").mkdir()
        (root / "deploy" / "nginx.conf").write_text(INGRESS, encoding="utf-8")
        return Cutover(root, working, Mock(), io.BytesIO())

    def frozen(self, deployment):
        deployment.snapshot.mkdir()
        original = deployment.ingress.read_bytes()
        (deployment.snapshot / "nginx.conf").write_bytes(original)
        (deployment.snapshot / "compose.json").write_text(json.dumps({
            "services": {
                name: {"environment": {"DATABASE_URL": V1}, "image": OLD}
                for name in ("api", "mcp", "worker", "frontend")
            },
        }))
        deployment.marker.write_text(json.dumps({"state": str(deployment.working)}))
        deployment.ingress.write_text(gate(INGRESS, probes=False), encoding="utf-8")
        identity = deployment.ingress.stat()
        deployment.save(
            "frozen", writes_may_exist=False, legacy_volume="legacy-files",
            legacy_images={name: OLD for name in ("api", "mcp", "worker", "frontend")},
            legacy_worker_was_running=True,
            old_ingress_sha256=fingerprint(deployment.snapshot / "nginx.conf"),
            ingress_identity=[identity.st_dev, identity.st_ino],
            closed_ingress_sha256=fingerprint(deployment.ingress),
            rollback_compose_sha256=fingerprint(deployment.snapshot / "compose.json"),
        )

    def fake_runtime(self, deployment):
        deployment.compose = Mock()
        deployment.stopped = Mock()
        deployment.check_shared = Mock()
        deployment.pinned_services = Mock()
        deployment.require_closed = Mock()
        deployment.verify_routes = Mock()
        deployment.verify_maintenance = Mock(return_value=(deployment.working / "maintenance.env", {"status": "success"}))
        deployment.install_ingress = Mock(side_effect=deployment.ingress.write_bytes)

    def test_gate_blocks_tls_and_cleartext_but_preserves_shared_routes(self):
        closed = gate(INGRESS, probes=False)
        probes = gate(INGRESS, probes=True)
        for variant in (closed, probes):
            http = variant.split(MOCHI)[0]
            self.assertNotIn("proxy_pass http://api:8000", http)
            self.assertNotIn("proxy_pass http://mcp:8000", http)
            self.assertEqual(http.count("return 503;"), 2)
            self.assertIn("location ^~ /.well-known/acme-challenge/", http)
            self.assertEqual(variant.split(MOCHI)[1].split(ZEICHEN)[0], INGRESS.split(MOCHI)[1].split(ZEICHEN)[0])
            self.assertEqual(variant.split(FALLBACK)[1], INGRESS.split(FALLBACK)[1])
        tls = closed.split(ZEICHEN)[1].split(FALLBACK)[0]
        self.assertNotIn("proxy_pass", tls)
        self.assertIn("return 503;", tls)
        self.assertIn('if ($request_method !~ "^(GET|HEAD)$") { return 503; }', probes)
        self.assertIn('^(/|/api/health|/[.]well-known/oauth-protected-resource/mcp)$', probes)
        with self.assertRaises(RuntimeError):
            gate(INGRESS.replace("proxy_pass http://mcp:8000/mcp;", "", 1), probes=False)

    def test_freeze_protects_ingress_stops_and_drains_before_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            item = self.state(directory)
            events = []
            compose = item.root / "legacy.json"
            compose.write_text(json.dumps({
                "services": {name: {"image": OLD, "environment": {"DATABASE_URL": V1}}
                             for name in ("api", "mcp", "worker", "frontend")},
            }))
            item.inspect = Mock(side_effect=lambda name: (
                {"Id": "proxy", "Mounts": [{"Destination": "/etc/nginx/conf.d/default.conf",
                                           "Source": str(item.ingress), "Type": "bind"}]}
                if name == GATEWAY else
                {"Id": "postgres", "NetworkSettings": {"Networks": {"net": {"Aliases": ["postgres"]}}}}
            ))
            item.app = Mock(return_value={
                "Mounts": [{"Destination": "/srv/zeichen/storage/attachments", "Name": "fixture-volume"}],
                "NetworkSettings": {"Networks": {"net": {}}}, "State": {"Running": True},
            })
            item.pinned_services = Mock()
            item.pg = Mock(return_value="1007wikimerge")
            item.worker_pids = Mock(return_value={"414"})
            item.require_closed = Mock()
            item.check_shared = Mock()
            item.compose = Mock(side_effect=lambda *args: events.append(args))
            item.stopped = Mock()
            item.wait_drain = Mock(side_effect=lambda _: events.append(("drain",)))
            def capture(path, *args):
                path.write_bytes(b"synthetic capture")
                events.append(("capture", path.name))

            item.capture = Mock(side_effect=capture)

            def install(gated):
                self.assertTrue(item.marker.exists())
                self.assertEqual(item.record["phase"], "freezing")
                item.ingress.write_bytes(gated)
                events.append(("close",))

            item.install_ingress = Mock(side_effect=install)
            with patch("cutover_v2.http_get", return_value=b"synthetic Mochi"):
                item.freeze(compose)
            self.assertEqual(events, [
                ("close",), ("stop", *WRITERS), ("drain",),
                ("capture", "postgres.dump"), ("capture", "attachments.tar.gz"),
            ])
            self.assertEqual(item.record["phase"], "frozen")
            self.assertFalse(item.record["writes_may_exist"])

    def test_acceptance_must_bind_all_checks_and_exact_candidate_rehearsal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = root / "prepared.json"
            prepared.write_text("{}")
            proof = root / "rehearsal.json"
            rehearsal = {"status": "verified", "mode": "synthetic_only", "candidate_commit": SHA}
            proof.write_text(json.dumps(rehearsal))
            accepted = {
                "candidate_commit": SHA, "prepared_manifest_sha256": fingerprint(prepared),
                "checks": {check: {"passed": True, "evidence": "synthetic result"} for check in ACCEPTANCE_IDS},
                "migration_exceptions_reviewed": True,
                "restore_rehearsal": {"path": str(proof), "sha256": fingerprint(proof)},
            }
            with self.assertRaisesRegex(RuntimeError, "effective Agent authorization"):
                validate_acceptance(accepted, prepared, {"candidate_commit": SHA})
            rehearsal["authentication"] = {
                "active_key": "accepted", "revoked_key": "rejected", "suspended_agent": "rejected",
                "owner_permissions": "inherited_and_rechecked",
            }
            proof.write_text(json.dumps(rehearsal))
            accepted["restore_rehearsal"]["sha256"] = fingerprint(proof)
            validate_acceptance(accepted, prepared, {"candidate_commit": SHA})
            accepted["checks"].pop("AC-31")
            with self.assertRaises(RuntimeError):
                validate_acceptance(accepted, prepared, {"candidate_commit": SHA})

    def test_gate_stages_only_app_services_then_records_write_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            item = self.state(directory)
            self.frozen(item)
            self.fake_runtime(item)
            prepared = item.working / "prepared.json"
            acceptance = item.working / "acceptance.json"
            candidate = item.working / "nginx.candidate.conf"
            candidate.write_text(INGRESS, encoding="utf-8")
            item.validate_prepared = Mock(return_value={
                "backend_image": BACKEND, "frontend_image": FRONTEND,
                "target_database": "zeichen_v2_fixture", "target_attachment_volume": "frozen-clone",
            })
            item.stage(prepared, acceptance)
            self.assertEqual(item.record["phase"], "staged")
            self.assertEqual(item.compose.call_args.args[-3:], ("api", "mcp", "frontend"))
            self.assertFalse(item.record["writes_may_exist"])

            def release_gate(configuration):
                self.assertTrue(item.record["writes_may_exist"])
                self.assertEqual(item.record["phase"], "opening")
                item.ingress.write_bytes(configuration)

            item.install_ingress.side_effect = release_gate
            item.open()
            self.assertEqual(item.record["phase"], "active")
            self.assertTrue(item.record["maintenance_timer_pending"])
            with self.assertRaisesRegex(RuntimeError, "after writes"):
                item.rollback()

    def test_rollback_keeps_legacy_database_volume_and_gateway_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            item = self.state(directory)
            self.frozen(item)
            self.fake_runtime(item)
            item.pg = Mock(return_value="1007wikimerge")
            inode = item.ingress.stat().st_ino
            item.install_ingress.side_effect = item.write_ingress
            item.rollback()
            self.assertEqual(item.record["phase"], "rolled_back")
            self.assertFalse(item.marker.exists())
            self.assertEqual(item.ingress.stat().st_ino, inode)
            self.assertEqual(item.ingress.read_bytes(), (item.snapshot / "nginx.conf").read_bytes())
            for call in item.compose.call_args_list:
                self.assertNotIn("web", call.args)
                self.assertNotIn("postgres", call.args)
            self.assertEqual(item.pinned_services.call_args.args[1:], ("zeichen", "legacy-files"))

    def test_failed_open_reinstalls_gate_without_reactivating_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            item = self.state(directory)
            self.frozen(item)
            self.fake_runtime(item)
            prepared = item.working / "prepared.json"
            (item.working / "nginx.candidate.conf").write_text(INGRESS, encoding="utf-8")
            item.validate_prepared = Mock(return_value={
                "backend_image": BACKEND, "frontend_image": FRONTEND,
                "target_database": "zeichen_v2_fixture", "target_attachment_volume": "frozen-clone",
            })
            item.stage(prepared, item.working / "acceptance.json")
            staged = item.ingress.read_bytes()
            item.staged_health = Mock()
            item.verify_routes = Mock(side_effect=RuntimeError("external health failed"))
            item.install_ingress.side_effect = lambda data, **kwargs: item.ingress.write_bytes(data)
            with self.assertRaisesRegex(RuntimeError, "external health failed"):
                item.open()
            self.assertEqual(item.record["phase"], "v2_refrozen")
            self.assertTrue(item.record["writes_may_exist"])
            self.assertEqual(item.ingress.read_bytes(), staged)
            self.assertEqual(item.compose.call_count, 1)


if __name__ == "__main__":
    unittest.main()
