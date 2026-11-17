import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rehearse_v2_cutover import LABEL, Rehearsal


class RehearsalCleanupTests(unittest.TestCase):
    def test_removes_only_named_resources_that_still_hold_the_run_label(self):
        with tempfile.TemporaryDirectory() as directory:
            rehearsal = Rehearsal(SimpleNamespace(output=Path(directory)), io.BytesIO())
            rehearsal.evidence.mkdir()
            cutover_token = "f" * 32
            target_volume = f"{rehearsal.target}_files_{cutover_token[:10]}"
            legacy_volume = f"{rehearsal.target}_legacy_ro_{cutover_token[:10]}"
            (rehearsal.evidence / "prepared.json").write_text(json.dumps({
                "target_database": rehearsal.target, "volume_owner_token": cutover_token,
                "created_resources": [
                    {"volume": target_volume}, {"volume": legacy_volume}, {"volume": "zeichen_attachments"},
                ],
            }))
            rehearsal.owned = [
                ("network", rehearsal.network, LABEL, rehearsal.token),
                ("container", rehearsal.database, LABEL, rehearsal.token),
                ("volume", rehearsal.source_volume, LABEL, rehearsal.token),
            ]
            removed = []

            def docker(kind, action, *args, capture=False):
                name = args[-1]
                if action == "inspect":
                    if name == legacy_volume:
                        return "changed-owner"
                    return cutover_token if name == target_volume else rehearsal.token
                removed.append((kind, name))
                return ""

            rehearsal.run = SimpleNamespace(docker=docker)
            rehearsal.cleanup()
            self.assertEqual(removed, [
                ("volume", target_volume), ("volume", rehearsal.source_volume),
                ("container", rehearsal.database), ("network", rehearsal.network),
            ])
            self.assertEqual(rehearsal.record["cleanup_failures"], [{"kind": "volume", "name": legacy_volume}])


if __name__ == "__main__":
    unittest.main()
