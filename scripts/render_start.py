"""Initialize the Render persistent disk, then replace this process with Gunicorn."""

import os
import shutil
import sqlite3
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.upgrade_v2 import apply_upgrades


def copy_seed_database(database: Path) -> bool:
    if database.exists():
        return False
    seed = ROOT / "database" / "yonaguni_v2_seed.db"
    if not seed.exists():
        raise SystemExit("Render seed database is missing.")
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_suffix(database.suffix + ".initializing")
    shutil.copy2(seed, temporary)
    temporary.replace(database)
    return True


def copy_seed_media(media_root: Path) -> None:
    media_root.mkdir(parents=True, exist_ok=True)
    source_root = ROOT / "v6" / "static" / "media"
    if not source_root.exists():
        return
    for source in source_root.rglob("*"):
        if not source.is_file() or source.name == ".DS_Store":
            continue
        relative = source.relative_to(source_root)
        target = media_root / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def bootstrap_admin(db: sqlite3.Connection) -> None:
    if db.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
        return
    username = os.environ.get("YONAGUNI_ADMIN_USERNAME", "").strip()
    display_name = os.environ.get("YONAGUNI_ADMIN_DISPLAY_NAME", "").strip()
    password = os.environ.get("YONAGUNI_ADMIN_PASSWORD", "")
    if not username or not display_name or len(password) < 12:
        raise SystemExit(
            "Set YONAGUNI_ADMIN_USERNAME, YONAGUNI_ADMIN_DISPLAY_NAME, and "
            "a YONAGUNI_ADMIN_PASSWORD of at least 12 characters."
        )
    db.execute(
        """INSERT INTO users
           (username,display_name,password_hash,role,must_change_password)
           VALUES(?,?,?,'admin',1)""",
        (username, display_name, generate_password_hash(password)),
    )


def prepare_database(database: Path) -> None:
    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 10000")
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA synchronous = NORMAL")
    apply_upgrades(db)
    bootstrap_admin(db)
    db.commit()
    violations = list(db.execute("PRAGMA foreign_key_check"))
    integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    db.close()
    if violations or integrity != "ok":
        raise SystemExit(
            f"Database verification failed: integrity={integrity}, "
            f"foreign_keys={len(violations)}"
        )


def main() -> None:
    database = Path(os.environ.get("YONAGUNI_DATABASE", "/var/data/yonaguni_v2.db"))
    media_root = Path(os.environ.get("YONAGUNI_MEDIA_ROOT", "/var/data/media"))
    backup_root = Path(os.environ.get("YONAGUNI_BACKUP_ROOT", "/var/data/backups"))
    copy_seed_database(database)
    copy_seed_media(media_root)
    backup_root.mkdir(parents=True, exist_ok=True)
    prepare_database(database)
    os.execvp("gunicorn", ("gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"))


if __name__ == "__main__":
    main()
