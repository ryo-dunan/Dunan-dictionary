import hashlib
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
source=Path(os.environ.get("YONAGUNI_DATABASE", ROOT/"database"/"yonaguni_v2.db"))
folder=Path(os.environ.get("YONAGUNI_BACKUP_ROOT", ROOT/"backups")); folder.mkdir(parents=True,exist_ok=True)
stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); target=folder/f"yonaguni-v2-{stamp}.db"
db=sqlite3.connect(source); integrity=db.execute("PRAGMA integrity_check").fetchone()[0]
if integrity!="ok": raise SystemExit(f"source database integrity failed: {integrity}")
backup=sqlite3.connect(target); db.backup(backup); backup.close(); db.close()
digest=hashlib.sha256(target.read_bytes()).hexdigest()
print(f"backup={target}\nsha256={digest}\nsize={target.stat().st_size}\nintegrity=ok")
