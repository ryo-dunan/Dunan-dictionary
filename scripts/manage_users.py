import argparse
import getpass
import os
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="Create an individual v2 dictionary account")
    parser.add_argument("username")
    parser.add_argument("display_name")
    parser.add_argument("--role", choices=("admin", "editor"), default="editor")
    parser.add_argument("--database", type=Path, default=Path(os.environ.get("YONAGUNI_DATABASE", ROOT / "database" / "yonaguni_v2.db")))
    args = parser.parse_args()
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Password again: ")
    if password != confirmation or len(password) < 12:
        raise SystemExit("Passwords must match and contain at least 12 characters.")
    db = sqlite3.connect(args.database)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute(
        "INSERT INTO users(username, display_name, password_hash, role) VALUES (?, ?, ?, ?)",
        (args.username, args.display_name, generate_password_hash(password), args.role),
    )
    db.commit()
    db.close()
    print(f"Created account: {args.username} ({args.role})")


if __name__ == "__main__":
    main()
