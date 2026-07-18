import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATABASE = Path(os.environ.get("YONAGUNI_DATABASE", ROOT / "database" / "yonaguni_v2.db"))


def column_names(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def add_column(db, table, definition):
    name = definition.split()[0]
    if name not in column_names(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def apply_upgrades(db):
    db.executescript((ROOT / "database" / "v2_schema.sql").read_text(encoding="utf-8"))
    add_column(db, "users", "must_change_password INTEGER NOT NULL DEFAULT 0")
    add_column(db, "users", "last_login_at TEXT")
    add_column(db, "entry_assignments", "assignment_kind TEXT NOT NULL DEFAULT 'inspection'")
    add_column(db, "media_files", "is_archived INTEGER NOT NULL DEFAULT 0")
    add_column(db, "media_files", "sha256 TEXT")
    add_column(db, "media_files", "revision_id INTEGER")
    add_column(db, "media_files", "is_pending INTEGER NOT NULL DEFAULT 0")
    add_column(db, "entry_source_records", "is_archived INTEGER NOT NULL DEFAULT 0")
    add_column(db, "entries", "supplemental_note TEXT")
    db.execute("UPDATE entry_workflow SET publication_status='published' WHERE created_by IS NULL AND workflow_status='unreviewed' AND publication_status='unpublished'")
    db.execute("INSERT OR IGNORE INTO example_state(example_id) SELECT id FROM examples")
    default_categories = ("基本形", "未然形", "連用形", "終止形", "連体形", "仮定形", "命令形", "否定形", "過去形", "テ形", "条件形", "意向形", "可能形", "受身形", "使役形")
    db.executemany("INSERT OR IGNORE INTO conjugation_categories(name,sort_order) VALUES(?,?)",
                   ((name, index * 10) for index, name in enumerate(default_categories, 1)))
    db.execute("INSERT OR IGNORE INTO conjugation_categories(name,sort_order) SELECT DISTINCT TRIM(form_name),500 FROM conjugations WHERE TRIM(COALESCE(form_name,''))!=''")


def upgrade(database=DATABASE):
    db = sqlite3.connect(database)
    db.execute("PRAGMA foreign_keys=ON")
    apply_upgrades(db)
    db.commit()
    violations = list(db.execute("PRAGMA foreign_key_check"))
    integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    db.close()
    if violations or integrity != "ok":
        raise SystemExit(f"upgrade verification failed: integrity={integrity}, foreign_keys={len(violations)}")
    print(f"upgrade complete: {database}")


if __name__ == "__main__":
    upgrade()
