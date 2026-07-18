"""Build a public deployment seed without accounts or editorial history."""

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


OPERATIONAL_TABLES = (
    "review_comments",
    "review_requests",
    "entry_assignments",
    "entry_checklists",
    "audit_logs",
    "backup_runs",
    "import_batches",
    "entry_revisions",
    "login_attempts",
    "users",
)


def build_seed(source: Path, target: Path) -> None:
    source = source.resolve()
    target = target.resolve()
    if source == target:
        raise SystemExit("The seed target must be different from the live database.")
    if not source.exists():
        raise SystemExit(f"Source database does not exist: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    source_db = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    seed_db = sqlite3.connect(target)
    source_db.backup(seed_db)
    source_db.close()

    seed_db.row_factory = sqlite3.Row
    seed_db.execute("PRAGMA foreign_keys = ON")
    seed_db.execute("UPDATE entry_workflow SET created_by=NULL,current_revision_id=NULL")
    seed_db.execute(
        """UPDATE entry_workflow
           SET workflow_status=CASE publication_status
             WHEN 'published' THEN 'verified' ELSE 'unreviewed' END"""
    )
    seed_db.execute("UPDATE entry_source_records SET created_by=NULL")
    seed_db.execute("UPDATE media_files SET revision_id=NULL,is_pending=0")
    seed_db.execute("UPDATE entry_revisions SET base_revision_id=NULL")
    for table in OPERATIONAL_TABLES:
        seed_db.execute(f"DELETE FROM {table}")
    seed_db.execute(
        "DELETE FROM sqlite_sequence WHERE name IN ({})".format(
            ",".join("?" for _ in OPERATIONAL_TABLES)
        ),
        OPERATIONAL_TABLES,
    )
    seed_db.commit()

    violations = list(seed_db.execute("PRAGMA foreign_key_check"))
    integrity = seed_db.execute("PRAGMA integrity_check").fetchone()[0]
    entries = seed_db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    indexed_entries = seed_db.execute(
        "SELECT COUNT(DISTINCT entry_id) FROM entry_search_index"
    ).fetchone()[0]
    users = seed_db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if violations or integrity != "ok" or users or not indexed_entries:
        seed_db.close()
        target.unlink(missing_ok=True)
        raise SystemExit(
            f"Seed verification failed: integrity={integrity}, "
            f"foreign_keys={len(violations)}, users={users}, indexed={indexed_entries}"
        )
    seed_db.execute("VACUUM")
    seed_db.close()
    print(
        f"seed={target}\nentries={entries}\nindexed_entries={indexed_entries}"
        "\nusers=0\nintegrity=ok"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, default=ROOT / "database" / "yonaguni_v2.db"
    )
    parser.add_argument(
        "--target", type=Path, default=ROOT / "database" / "yonaguni_v2_seed.db"
    )
    args = parser.parse_args()
    build_seed(args.source, args.target)


if __name__ == "__main__":
    main()
