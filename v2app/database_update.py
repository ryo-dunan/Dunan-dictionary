"""Safe backup, validation, and replacement helpers for the SQLite database."""

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .search import rebuild_search_index


DATABASE_UPDATE_LOCK = threading.Lock()
SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = {
    "audit_logs",
    "backup_runs",
    "entries",
    "entry_search_index",
    "entry_workflow",
    "examples",
    "meanings",
    "users",
}


class DatabaseUpdateError(Exception):
    """An upload that cannot safely replace the current database."""


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect(path, read_only=False):
    if read_only:
        db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    else:
        db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    return db


def inspect_database(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size < len(SQLITE_HEADER):
        raise DatabaseUpdateError("SQLiteデータベースファイルを選んでください。")
    with path.open("rb") as handle:
        if handle.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
            raise DatabaseUpdateError("選択したファイルはSQLiteデータベースではありません。")
    db = None
    try:
        db = _connect(path, read_only=True)
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise DatabaseUpdateError("データベースの整合性検査に合格しませんでした。")
        foreign_key_errors = db.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise DatabaseUpdateError("関連データに不整合があるため更新できません。")
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = REQUIRED_TABLES - tables
        if missing:
            raise DatabaseUpdateError("この辞書用のDBではないか、必要な構造が不足しています。")
        active_admins = db.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
        ).fetchone()[0]
        if not active_admins:
            raise DatabaseUpdateError("有効な完全管理者がいないDBは使用できません。")
        summary = {
            "entries": db.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
            "meanings": db.execute("SELECT COUNT(*) FROM meanings").fetchone()[0],
            "examples": db.execute("SELECT COUNT(*) FROM examples").fetchone()[0],
            "users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "published": db.execute(
                "SELECT COUNT(*) FROM entry_workflow WHERE publication_status='published'"
            ).fetchone()[0],
            "active_admins": active_admins,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "integrity": integrity,
        }
        return summary
    except DatabaseUpdateError:
        raise
    except sqlite3.DatabaseError as error:
        raise DatabaseUpdateError("データベースを安全に読み取れませんでした。") from error
    finally:
        if db is not None:
            db.close()


def pending_folder(backup_root):
    folder = Path(backup_root) / "pending-database-updates"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def clean_stale_pending(backup_root, max_age_seconds=24 * 60 * 60):
    folder = pending_folder(backup_root)
    cutoff = time.time() - max_age_seconds
    for path in folder.glob("*.db"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def save_pending_upload(file_storage, backup_root):
    clean_stale_pending(backup_root)
    token = secrets.token_urlsafe(24)
    target = pending_folder(backup_root) / f"{token}.db"
    try:
        file_storage.save(target)
        summary = inspect_database(target)
        return token, target, summary
    except Exception:
        target.unlink(missing_ok=True)
        raise


def pending_path(backup_root, token):
    if not token or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in token):
        raise DatabaseUpdateError("更新ファイルの確認情報が無効です。もう一度選び直してください。")
    path = pending_folder(backup_root) / f"{token}.db"
    if not path.is_file():
        raise DatabaseUpdateError("確認待ちのDBが見つかりません。もう一度選び直してください。")
    return path


def create_backup(source_path, backup_root, actor_id=None):
    source_path = Path(source_path)
    folder = Path(backup_root)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = folder / f"yonaguni-v2-{stamp}-{secrets.token_hex(3)}.db"
    source = _connect(source_path)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    summary = inspect_database(target)
    return {
        "path": target,
        "filename": target.name,
        "sha256": summary["sha256"],
        "size_bytes": summary["size_bytes"],
        "integrity": summary["integrity"],
        "actor_id": actor_id,
    }


def _prepare_replacement(path, current_admin):
    # Imported backups can be from an older release. Upgrade the copy, never the live DB.
    from scripts.upgrade_v2 import apply_upgrades

    db = _connect(path)
    try:
        apply_upgrades(db)
        incoming = db.execute(
            "SELECT id FROM users WHERE username=?", (current_admin["username"],)
        ).fetchone()
        if incoming:
            actor_id = incoming["id"]
            db.execute(
                """UPDATE users SET display_name=?,password_hash=?,role='admin',
                   is_active=1,must_change_password=0,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (
                    current_admin["display_name"],
                    current_admin["password_hash"],
                    actor_id,
                ),
            )
        else:
            actor_id = db.execute(
                """INSERT INTO users
                   (username,display_name,password_hash,role,is_active,must_change_password)
                   VALUES(?,?,?,'admin',1,0) RETURNING id""",
                (
                    current_admin["username"],
                    current_admin["display_name"],
                    current_admin["password_hash"],
                ),
            ).fetchone()[0]
        rebuild_search_index(db)
        db.commit()
        errors = db.execute("PRAGMA foreign_key_check").fetchall()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if errors or integrity != "ok":
            raise DatabaseUpdateError("更新準備後のDB検査に合格しませんでした。")
        # A single uploaded file must not depend on a sidecar WAL file.
        db.execute("PRAGMA journal_mode=DELETE").fetchone()
        db.commit()
        return actor_id
    finally:
        db.close()


def replace_database(database, backup_root, pending, current_admin, expected_sha256):
    database = Path(database)
    backup_root = Path(backup_root)
    pending = Path(pending)
    if not DATABASE_UPDATE_LOCK.acquire(blocking=False):
        raise DatabaseUpdateError("別のDB更新処理が進行中です。少し待ってからお試しください。")
    replacement = database.parent / f".{database.name}.replacement-{secrets.token_hex(6)}"
    maintenance = backup_root / ".database-update-in-progress"
    backup = None
    replaced = False
    try:
        before = inspect_database(database)
        uploaded = inspect_database(pending)
        if not secrets.compare_digest(uploaded["sha256"], expected_sha256 or ""):
            raise DatabaseUpdateError("確認後にファイル内容が変化しました。もう一度選び直してください。")
        shutil.copy2(pending, replacement)
        actor_id = _prepare_replacement(replacement, current_admin)
        after = inspect_database(replacement)

        maintenance.parent.mkdir(parents=True, exist_ok=True)
        maintenance.write_text("database update", encoding="utf-8")
        # Let requests that already passed before_request finish before checkpointing.
        time.sleep(0.25)
        backup = create_backup(database, backup_root, current_admin["id"])
        live = _connect(database)
        checkpoint = live.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        live.close()
        if checkpoint and checkpoint[0]:
            raise DatabaseUpdateError("DBが使用中です。数秒待ってからもう一度お試しください。")
        for suffix in ("-wal", "-shm"):
            Path(str(database) + suffix).unlink(missing_ok=True)
        os.replace(replacement, database)
        replaced = True

        new_db = _connect(database)
        try:
            new_db.execute("PRAGMA journal_mode=WAL").fetchone()
            new_db.execute(
                """INSERT INTO backup_runs
                   (actor_id,filename,sha256,size_bytes,integrity_result)
                   VALUES(?,?,?,?,?)""",
                (
                    actor_id,
                    backup["filename"],
                    backup["sha256"],
                    backup["size_bytes"],
                    backup["integrity"],
                ),
            )
            new_db.execute(
                """INSERT INTO audit_logs
                   (actor_id,action,entity_type,before_json,after_json)
                   VALUES(?,'replace_database','database',?,?)""",
                (
                    actor_id,
                    json.dumps(before, ensure_ascii=False, sort_keys=True),
                    json.dumps(after, ensure_ascii=False, sort_keys=True),
                ),
            )
            new_db.commit()
        finally:
            new_db.close()
        pending.unlink(missing_ok=True)
        return {"before": before, "after": after, "backup": backup, "actor_id": actor_id}
    except Exception:
        if replaced and backup and backup["path"].is_file():
            failed = database.parent / f".{database.name}.failed-{secrets.token_hex(4)}"
            try:
                for suffix in ("-wal", "-shm"):
                    Path(str(database) + suffix).unlink(missing_ok=True)
                os.replace(database, failed)
                shutil.copy2(backup["path"], database)
                failed.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        replacement.unlink(missing_ok=True)
        maintenance.unlink(missing_ok=True)
        DATABASE_UPDATE_LOCK.release()
