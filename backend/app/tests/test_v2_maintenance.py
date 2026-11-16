import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiKey
from app.v2 import file_storage
from app.v2.file_models import FileGrant, FileUploadGrant, ProjectFile
from app.workers import maintenance


def test_expiration_is_bounded_for_both_grants_and_preserves_files(db, world):
    cutoff = datetime.now(UTC)
    project_id, actor_id = world["project"].id, world["agent"].id
    key = ApiKey(user_id=actor_id, token_hash="fixture-key")
    project_file = ProjectFile(project_id=project_id, id=uuid4(), name="retain.txt", size=7,
                               media_type="text/plain", sha256="e" * 64, deleted_at=cutoff)
    db.add_all([key, project_file])
    db.flush()
    expiries = [cutoff - timedelta(hours=1), cutoff, cutoff + timedelta(hours=1)]
    for offset, expiry in enumerate(expiries):
        db.add_all([
            FileGrant(digest=f"read-{offset}", project_id=project_id, file_id=project_file.id,
                      actor_id=actor_id, api_key_id=key.id, expires_at=expiry, inline=False),
            FileUploadGrant(id=uuid4(), digest=f"upload-{offset}", project_id=project_id, actor_id=actor_id,
                            api_key_id=key.id, name="retain.txt", expected_size=7, expires_at=expiry),
        ])
    db.commit()
    for grant, prefix in ((FileGrant, "read"), (FileUploadGrant, "upload")):
        assert maintenance.delete_expired_grants(db, grant, cutoff, 1) == 1
        assert set(db.scalars(select(grant.digest))) == {f"{prefix}-1", f"{prefix}-2"}
        assert maintenance.delete_expired_grants(db, grant, cutoff, 5) == 1
        assert maintenance.delete_expired_grants(db, grant, cutoff, 5) == 0
        assert set(db.scalars(select(grant.digest))) == {f"{prefix}-2"}
    assert db.get(ProjectFile, (project_id, project_file.id)).deleted_at is not None


@pytest.mark.skipif(os.name != "posix", reason="production stage locking uses POSIX flock")
def test_staging_ignores_active_fresh_and_unrelated_paths(tmp_path, monkeypatch):
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    old = cutoff.timestamp() - 3600
    monkeypatch.setattr(file_storage.get_settings(), "attachment_storage_dir", str(tmp_path))
    root = file_storage.library_root()
    stage = root / ".staging"
    stage.mkdir(parents=True)
    committed = root / "retain.bin"
    committed.write_bytes(b"published bytes")
    abandoned = stage / "tmpdisused0.part"
    happened_to_be_a_hardlink = stage / "tmplink0000.part"
    fresh = stage / "tmpfresh000.part"
    unrelated = stage / "backup.part"
    symlink = stage / "tmpsym00000.part"
    os.link(committed, happened_to_be_a_hardlink)
    symlink.symlink_to(committed)
    for path in (abandoned, fresh, unrelated):
        path.write_bytes(b"incomplete")
    for path in (abandoned, unrelated, happened_to_be_a_hardlink):
        os.utime(path, (old, old))

    with file_storage.stage_file() as upload:
        active, = set(stage.iterdir()) - {abandoned, fresh, unrelated, happened_to_be_a_hardlink, symlink}
        assert maintenance._PART_NAME.fullmatch(active.name)
        upload.write(b"in-flight data")
        os.utime(active, (old, old))
        counts = maintenance.Counts()
        maintenance.prune_staging(root, cutoff, limit=10, scan_limit=20, counts=counts)
        assert counts.stale_parts_deleted == 2 and counts.locked_parts_skipped == 1
        assert active.is_file()
        assert not abandoned.exists() and not happened_to_be_a_hardlink.exists()
        assert all(path.exists() for path in (fresh, unrelated, symlink))
        project_id, file_id = uuid4(), uuid4()
        upload.publish(project_id, file_id)
        os.utime(active, (old, old))
        maintenance.prune_staging(root, cutoff, limit=10, scan_limit=20, counts=counts)
        assert counts.locked_parts_skipped == 2
        assert active.is_file()
    assert not active.exists()
    assert committed.read_bytes() == b"published bytes"
    assert file_storage.file_path(project_id, file_id).read_bytes() == b"in-flight data"


@pytest.mark.skipif(os.name != "posix", reason="production stage locking uses POSIX flock")
def test_staging_enforces_bounds_and_rejects_symlink_root(tmp_path):
    root = tmp_path / "library-v2"
    stage = root / ".staging"
    stage.mkdir(parents=True)
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    old = cutoff.timestamp() - 3600
    for index in range(3):
        part = stage / f"tmp{index:08d}.part"
        part.touch()
        os.utime(part, (old, old))
    counts = maintenance.Counts()
    maintenance.prune_staging(root, cutoff, limit=1, scan_limit=2, counts=counts)
    assert counts.stale_parts_deleted == 1 and counts.staging_limit_reached
    alias = tmp_path / "symlink-root"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        maintenance.prune_staging(alias, cutoff, limit=1, scan_limit=2, counts=maintenance.Counts())


def test_one_shot_reports_busy_and_failure_without_secrets(db, monkeypatch, capsys):
    monkeypatch.setattr(maintenance, "_session", lambda: Session(db.get_bind()))
    monkeypatch.setattr(maintenance, "_try_lock", lambda session: False)
    assert maintenance.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "skipped_locked"

    monkeypatch.setattr(maintenance, "_try_lock", lambda session: True)
    monkeypatch.setattr(maintenance, "delete_expired_grants", lambda *args: 2)

    def unavailable(*args, **kwargs):
        raise RuntimeError("private connection details")

    monkeypatch.setattr(maintenance, "prune_staging", unavailable)
    assert maintenance.main([]) == 1
    output = capsys.readouterr().out
    evidence = json.loads(output)
    assert evidence["status"] == "failed" and evidence["phase"] == "staging"
    assert evidence["error_type"] == "RuntimeError"
    assert evidence["expired_read_grants_deleted"] == evidence["expired_upload_grants_deleted"] == 0
    assert "private connection details" not in output
