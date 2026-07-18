import json
import re
import unicodedata


def normalize(value):
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = value.translate(str.maketrans({"’": "'", "‘": "'", "‐": "-", "‑": "-", "–": "-"}))
    return re.sub(r"\s+", " ", value).strip()


def rebuild_search_index(db, entry_id=None):
    if entry_id is None:
        db.execute("DELETE FROM entry_search_index")
        entry_ids = [row[0] for row in db.execute("SELECT entry_id FROM entry_workflow WHERE publication_status='published'")]
    else:
        db.execute("DELETE FROM entry_search_index WHERE entry_id=?", (entry_id,)); entry_ids = [entry_id]
    for eid in entry_ids:
        entry = db.execute("SELECT headword,kana,ipa,supplemental_note FROM entries WHERE id=?", (eid,)).fetchone()
        if not entry: continue
        examples = " ".join(row[0] or "" for row in db.execute("SELECT ex.yonaguni_sentence FROM examples ex LEFT JOIN example_state es ON es.example_id=ex.id WHERE ex.entry_id=? AND COALESCE(es.is_archived,0)=0", (eid,)))
        conjugations = " ".join(row[0] or "" for row in db.execute("SELECT conjugated_form FROM conjugations WHERE entry_id=?", (eid,)))
        languages = {row[0] for row in db.execute("SELECT DISTINCT language FROM meanings WHERE entry_id=?", (eid,))} | {"ja","en","zh-tw"}
        source_sections = [json.loads(row[0]) for row in db.execute("SELECT content_json FROM entry_source_sections WHERE entry_id=? ORDER BY sort_order,id", (eid,))]
        for section in source_sections:
            languages.update(section.get("meanings", {}).keys())
            examples += " " + " ".join(item.get("yonaguni", "") for item in section.get("examples", []))
            conjugations += " " + " ".join(item.get("conjugated", "") for item in section.get("conjugations", []))
        for language in languages:
            definitions = " ".join(row[0] for row in db.execute("SELECT definition FROM meanings WHERE entry_id=? AND language=? ORDER BY meaning_number", (eid,language)))
            definitions += " " + (entry["supplemental_note"] or "")
            translations = " ".join(" ".join(filter(None,row)) for row in db.execute("SELECT et.word_by_word,et.free_translation FROM example_translations et JOIN examples ex ON ex.id=et.example_id LEFT JOIN example_state es ON es.example_id=ex.id WHERE ex.entry_id=? AND et.language=? AND COALESCE(es.is_archived,0)=0", (eid,language)))
            definitions += " " + " ".join(value for section in source_sections for value in section.get("meanings", {}).get(language, []) if value)
            translations += " " + " ".join(
                " ".join(filter(None, (item.get("translations", {}).get(language, {}).get("word_by_word"), item.get("translations", {}).get(language, {}).get("free_translation"))))
                for section in source_sections for item in section.get("examples", [])
            )
            db.execute("INSERT INTO entry_search_index VALUES(?,?,?,?,?,?,?,?)", (eid,language,normalize(entry["headword"]),normalize(entry["kana"]),normalize(entry["ipa"]),normalize(definitions),normalize(examples+" "+translations),normalize(conjugations)))


def search_entries(db, query, language="ja", search_type="headword", match="contains", limit=100):
    q = normalize(query)
    if not q: return []
    pattern = {"prefix": q+"%", "suffix": "%"+q, "contains": "%"+q+"%"}.get(match, "%"+q+"%")
    columns = {
        "headword": ("s.normalized_headword","s.normalized_kana","s.normalized_ipa","s.normalized_definition"),
        "examples": ("s.normalized_examples",), "conjugation": ("s.normalized_conjugations",),
    }.get(search_type, ("s.normalized_headword","s.normalized_kana","s.normalized_definition","s.normalized_examples"))
    where = " OR ".join(f"{column} LIKE ?" for column in columns)
    params = [language, *([pattern] * len(columns)), limit]
    return db.execute(f"""
      SELECT DISTINCT e.id,e.headword,e.kana,e.ipa,e.pos,
        COALESCE((SELECT definition FROM meanings WHERE entry_id=e.id AND language=? ORDER BY meaning_number LIMIT 1),
                 (SELECT definition FROM meanings WHERE entry_id=e.id AND language='ja' ORDER BY meaning_number LIMIT 1)) definition
      FROM entry_search_index s JOIN entries e ON e.id=s.entry_id JOIN entry_workflow w ON w.entry_id=e.id
      WHERE s.language=? AND w.publication_status='published' AND ({where}) ORDER BY e.headword LIMIT ?
    """, [language, *params]).fetchall()
