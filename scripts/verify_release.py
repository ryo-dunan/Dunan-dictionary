import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
db=sqlite3.connect(ROOT/"database"/"yonaguni_v2.db")
checks={
 "integrity":db.execute("PRAGMA integrity_check").fetchone()[0],
 "foreign_key_violations":len(db.execute("PRAGMA foreign_key_check").fetchall()),
 "entries":db.execute("SELECT COUNT(*) FROM entries").fetchone()[0],
 "workflow_rows":db.execute("SELECT COUNT(*) FROM entry_workflow").fetchone()[0],
 "published":db.execute("SELECT COUNT(*) FROM entry_workflow WHERE publication_status='published'").fetchone()[0],
 "search_rows":db.execute("SELECT COUNT(*) FROM entry_search_index").fetchone()[0],
 "active_users":db.execute("SELECT COUNT(*) FROM users WHERE is_active=1").fetchone()[0],
 "unresolved_quarantine":db.execute("SELECT COUNT(*) FROM quarantine_records WHERE restored_at IS NULL").fetchone()[0],
}
db.close()
for key,value in checks.items(): print(f"{key}: {value}")
if checks["integrity"]!="ok" or checks["foreign_key_violations"]: raise SystemExit(1)
