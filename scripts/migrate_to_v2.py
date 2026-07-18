import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash
from scripts.upgrade_v2 import apply_upgrades

ROOT = Path(__file__).resolve().parent.parent
CHECKLIST_ITEMS = (
    "headword", "reading", "ipa", "part_of_speech", "verb_details", "tone",
    "meanings", "examples", "translations", "media", "sources", "duplicates",
)


def backup_file(source, backup_dir):
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"{source.stem}-{stamp}{source.suffix}"
    shutil.copy2(source, destination)
    return destination


def quarantine_orphans(db):
    relations = (
        ("example_translations", "examples", "example_id"),
        ("media_files", "examples", "example_id"),
        ("meanings", "entries", "entry_id"),
        ("synonyms", "entries", "entry_id"),
        ("conjugations", "entries", "entry_id"),
        ("examples", "entries", "entry_id"),
        ("media_files", "entries", "entry_id"),
    )
    total = 0
    while True:
        pass_count = 0
        for child, parent, foreign_key in relations:
            rows = db.execute(
                f"SELECT c.* FROM {child} c LEFT JOIN {parent} p ON p.id=c.{foreign_key} "
                f"WHERE c.{foreign_key} IS NOT NULL AND p.id IS NULL"
            ).fetchall()
            for row in rows:
                db.execute(
                    "INSERT INTO quarantine_records(source_table, source_id, reason, record_json) VALUES (?, ?, ?, ?)",
                    (child, row["id"], f"missing parent {parent}.{foreign_key}", json.dumps(dict(row), ensure_ascii=False)),
                )
                db.execute(f"DELETE FROM {child} WHERE id = ?", (row["id"],))
                total += 1
                pass_count += 1
        if pass_count == 0:
            break
    return total


def migrate(source, target, admin_username=None, admin_password=None, admin_name=None):
    if target.exists():
        raise SystemExit(f"Target already exists: {target}")
    backup = backup_file(source, ROOT / "backups")
    shutil.copy2(source, target)
    db = sqlite3.connect(target)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        apply_upgrades(db)
        quarantined = quarantine_orphans(db)
        db.execute("INSERT OR IGNORE INTO entry_workflow(entry_id,publication_status) SELECT id,'published' FROM entries")
        db.execute("INSERT OR IGNORE INTO example_state(example_id) SELECT id FROM examples")
        for entry_id, in db.execute("SELECT id FROM entries"):
            db.executemany(
                "INSERT OR IGNORE INTO entry_checklists(entry_id, item_key) VALUES (?, ?)",
                ((entry_id, item) for item in CHECKLIST_ITEMS),
            )
        if admin_username and admin_password and admin_name:
            db.execute(
                "INSERT INTO users(username, display_name, password_hash, role) VALUES (?, ?, ?, 'admin')",
                (admin_username, admin_name, generate_password_hash(admin_password)),
            )
        db.commit()
        db.execute("PRAGMA foreign_keys = ON")
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    except Exception:
        db.rollback()
        db.close()
        target.unlink(missing_ok=True)
        raise
    db.close()
    print(json.dumps({"backup": str(backup), "target": str(target), "quarantined": quarantined,
                      "integrity": integrity, "foreign_key_violations": len(violations)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copy and migrate the legacy dictionary database to v2")
    parser.add_argument("--source", type=Path, default=ROOT / "v6" / "database" / "yonaguni_dict.db")
    parser.add_argument("--target", type=Path, default=ROOT / "database" / "yonaguni_v2.db")
    parser.add_argument("--admin-username")
    parser.add_argument("--admin-password")
    parser.add_argument("--admin-name")
    args = parser.parse_args()
    migrate(args.source, args.target, args.admin_username, args.admin_password, args.admin_name)
