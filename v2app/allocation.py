CHECKLIST_LABELS = {
    "headword": "見出し語", "reading": "読み方", "ipa": "IPA", "part_of_speech": "品詞",
    "verb_details": "動詞クラス・語幹", "tone": "音調", "meanings": "意味と語義区分",
    "examples": "例文", "translations": "逐語訳・自由訳", "media": "音声・画像",
    "sources": "出典・資料", "duplicates": "重複候補",
}


def calculate_workloads(db):
    rows = db.execute("""
        SELECT e.id,e.headword,e.kana,e.ipa,e.pos,e.tone,e.verb_class,e.verb_stem,
          COUNT(DISTINCT ex.id) example_count,COUNT(DISTINCT m.id) meaning_count,
          COUNT(DISTINCT mf.id) media_count,COUNT(DISTINCT sr.id) source_count
        FROM entries e JOIN entry_workflow w ON w.entry_id=e.id
        LEFT JOIN examples ex ON ex.entry_id=e.id LEFT JOIN meanings m ON m.entry_id=e.id
        LEFT JOIN media_files mf ON mf.entry_id=e.id OR mf.example_id=ex.id
        LEFT JOIN entry_source_records sr ON sr.entry_id=e.id
        WHERE w.publication_status!='archived'
        GROUP BY e.id
    """).fetchall()
    result = []
    for row in rows:
        missing = sum(not row[key] for key in ("kana", "ipa", "pos", "tone"))
        if row["pos"] == "動詞":
            missing += sum(not row[key] for key in ("verb_class", "verb_stem"))
        score = 1 + row["example_count"] * .35 + row["meaning_count"] * .12 + missing * .3
        score += .15 if not row["media_count"] else 0
        score += .2 if not row["source_count"] else 0
        result.append((row["id"], round(score, 2)))
    return result


def distribute_assignments(db, assigned_by, replace=False):
    users = db.execute("SELECT id FROM users WHERE is_active=1 ORDER BY id").fetchall()
    if len(users) < 2:
        raise ValueError("割り当てには2人以上の有効なメンバーが必要です。")
    if replace:
        db.execute("DELETE FROM entry_assignments WHERE status='assigned'")
    already = {row[0] for row in db.execute("SELECT DISTINCT entry_id FROM entry_assignments WHERE status!='completed'")}
    loads = {row["id"]: 0.0 for row in users}
    for row in db.execute("SELECT assignee_id,SUM(workload_score) total FROM entry_assignments WHERE status!='completed' GROUP BY assignee_id"):
        loads[row["assignee_id"]] = row["total"] or 0
    created = 0
    for entry_id, score in sorted(calculate_workloads(db), key=lambda item: item[1], reverse=True):
        if entry_id in already:
            continue
        assignee = min(loads, key=loads.get)
        db.execute("INSERT INTO entry_assignments(entry_id,assignee_id,assigned_by,workload_score) VALUES(?,?,?,?)",
                   (entry_id, assignee, assigned_by, score))
        loads[assignee] += score
        created += 1
    return created, loads
