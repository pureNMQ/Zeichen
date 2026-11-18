"""A v2 schema switch must preserve every frozen work item."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1]))
from migrate_v2_release import SchemaRelease, V2Release


class SchemaReleaseTests(unittest.TestCase):
    def setUp(self):
        self.release = SchemaRelease.__new__(SchemaRelease)
        self.release.directory = Path("/private/release")
        self.release.database_name = "zeichen_v2_fixture"
        self.release.record = {"frozen_clone_work_checksum": "snapshot"}
        self.release.save = Mock()
        self.release.prepare_clone = Mock(return_value="zeichen_upgrade_fixture")
        self.release.sql = Mock()

    @patch.object(V2Release, "backup")
    def test_changed_ledger_stops_before_renaming(self, snapshot):
        self.release.ledger = Mock(return_value="changed")
        with self.assertRaisesRegex(RuntimeError, "Work data changed"):
            self.release.backup()
        snapshot.assert_called_once()
        self.release.sql.assert_not_called()

    @patch.object(V2Release, "backup")
    def test_pair_of_renames_is_atomic_and_rollback_name_is_recorded(self, snapshot):
        self.release.ledger = Mock(return_value="snapshot")
        self.release.backup()
        previous = self.release.record["rollback_database"]
        self.release.sql.assert_called_once_with("postgres",
            f'BEGIN; ALTER DATABASE "zeichen_v2_fixture" RENAME TO "{previous}"; '
            'ALTER DATABASE "zeichen_upgrade_fixture" RENAME TO "zeichen_v2_fixture"; COMMIT')
        self.release.save.assert_called_with("switched_database")
