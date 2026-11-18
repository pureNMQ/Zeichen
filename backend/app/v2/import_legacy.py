"""Run the v2 history import against a migrated, write-frozen database clone."""

import argparse
import json
import os
import re
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from ..config import get_settings
from .import_legacy_references import migrate_references
from .import_legacy_files import import_files
from .import_legacy_timeline import import_timeline
from .import_legacy_wiki import import_wiki


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="The name of the v2 clone database")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--legacy-storage", type=Path, required=True)
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url or not re.fullmatch(r"zeichen_v2_[a-z0-9_]+", args.target):
        parser.error("Set DATABASE_URL and pass the name of a zeichen_v2_* database clone")
    target = make_url(url)
    if target.get_backend_name() != "postgresql" or target.database != args.target:
        parser.error("DATABASE_URL must point to the specified PostgreSQL clone")
    legacy_storage = args.legacy_storage.resolve()
    if not legacy_storage.is_dir() or legacy_storage == Path(get_settings().attachment_storage_dir).resolve():
        parser.error("Supply the existing legacy volume and a separate target attachment directory")
    # Create the report privately before starting any writes. On failure the
    # importer transaction rolls back and the caller can retry with a new report.
    descriptor = os.open(args.report, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    engine = create_engine(target)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as report:
            with Session(engine) as db, db.begin():
                file_counts, file_exceptions = import_files(db, legacy_storage)
                timeline_counts, timeline_exceptions = import_timeline(db)
                wiki_counts, wiki_exceptions = import_wiki(db)
                ref_counts, ref_exceptions = migrate_references(db)
            json.dump({
                "target": args.target,
                "references": ref_counts,
                "timeline": timeline_counts,
                "wiki": wiki_counts,
                "files": file_counts,
                "exceptions": {
                    "references": ref_exceptions,
                    "timeline": [asdict(exception) for exception in timeline_exceptions],
                    "wiki": wiki_exceptions,
                    "files": file_exceptions,
                },
            }, report, ensure_ascii=False, indent=2)
            report.write("\n")
            report.flush()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
