from pathlib import Path
import importlib.util
import sqlite3

root = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("yonaguni_search", root / "v2app" / "search.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
rebuild_search_index = module.rebuild_search_index
db = sqlite3.connect(root / "database" / "yonaguni_v2.db"); db.row_factory = sqlite3.Row; db.execute("PRAGMA foreign_keys=ON")
rebuild_search_index(db); db.commit()
print("indexed", db.execute("SELECT COUNT(*) FROM entry_search_index").fetchone()[0], "language records")
db.close()
