import json


ALLOWED_POS = ("名詞", "動詞", "形容詞", "副詞", "助詞", "感動詞", "連語", "その他")


def lines(value):
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def form_list(form, name):
    """Return repeated form values for both Flask MultiDict and plain test dicts."""
    if hasattr(form, "getlist"):
        return form.getlist(name)
    value = form.get(name, [])
    return value if isinstance(value, (list, tuple)) else ([value] if value != "" else [])


def examples_from_cards(form, base_examples):
    examples = []
    prior_by_id = {str(item.get("id")): item for item in base_examples if item.get("id") is not None}
    indices = form_list(form, "example_indices")
    for position, index in enumerate(indices, 1):
        prefix = f"example_{index}_"
        if form.get(prefix + "remove") == "1":
            continue
        example_id = (form.get(prefix + "id") or "").strip()
        sentence = (form.get(prefix + "yonaguni") or "").strip()
        values = {
            "ja": {
                "word_by_word": (form.get(prefix + "ja_word_by_word") or "").strip(),
                "free_translation": (form.get(prefix + "ja_free_translation") or "").strip(),
            },
            "en": {
                "word_by_word": (form.get(prefix + "en_word_by_word") or "").strip(),
                "free_translation": (form.get(prefix + "en_free_translation") or "").strip(),
            },
            "zh-tw": {
                "word_by_word": (form.get(prefix + "zh_tw_word_by_word") or "").strip(),
                "free_translation": (form.get(prefix + "zh_tw_free_translation") or "").strip(),
            },
        }
        if not sentence and not any(value for translation in values.values() for value in translation.values()):
            if example_id:
                raise ValueError(f"例文{position}の原文が空です。削除する場合は「この例文を削除」を押してください。")
            continue
        if not sentence:
            raise ValueError(f"例文{position}の原文を入力してください。")
        prior = prior_by_id.get(example_id, {})
        translations = dict(prior.get("translations", {}))
        for language, new_translation in values.items():
            if language == "ja" or any(new_translation.values()) or language not in translations:
                translations[language] = new_translation
        examples.append({
            "id": prior.get("id"),
            "yonaguni": sentence,
            "translations": translations,
        })
    return examples


def meanings_from_cards(form):
    meanings = {"ja": [], "en": [], "zh-tw": []}
    for index in form_list(form, "meaning_indices"):
        prefix = f"meaning_{index}_"
        if form.get(prefix + "remove") == "1":
            continue
        values = {
            "ja": (form.get(prefix + "ja") or "").strip(),
            "en": (form.get(prefix + "en") or "").strip(),
            "zh-tw": (form.get(prefix + "zh_tw") or "").strip(),
        }
        if not any(values.values()):
            continue
        for language, value in values.items():
            meanings[language].append(value)
    return meanings


def source_sections_from_form(form, base_sections, allowed_source_ids, allowed_conjugation_names):
    sections = []
    base_by_source = {str(item.get("source_id")): item for item in base_sections}
    seen_sources = set()
    for section_position, section_index in enumerate(form_list(form, "source_section_indices"), 1):
        root = f"source_section_{section_index}_"
        if form.get(root + "remove") == "1":
            continue
        try:
            source_id = int(form.get(root + "source_id") or 0)
        except (TypeError, ValueError):
            source_id = 0
        if not source_id or source_id not in allowed_source_ids:
            raise ValueError(f"辞典{section_position}の出典を選び直してください。")
        if source_id in seen_sources:
            raise ValueError("同じ辞典は一つの記述ブロックにまとめてください。")
        seen_sources.add(source_id)
        meanings = {"ja": [], "en": [], "zh-tw": []}
        for meaning_index in form_list(form, root + "meaning_indices"):
            prefix = root + f"meaning_{meaning_index}_"
            if form.get(prefix + "remove") == "1":
                continue
            values = {
                "ja": (form.get(prefix + "ja") or "").strip(),
                "en": (form.get(prefix + "en") or "").strip(),
                "zh-tw": (form.get(prefix + "zh_tw") or "").strip(),
            }
            if any(values.values()):
                for language, value in values.items():
                    meanings[language].append(value)
        conjugations = []
        for conjugation_index in form_list(form, root + "conjugation_indices"):
            prefix = root + f"conjugation_{conjugation_index}_"
            if form.get(prefix + "remove") == "1":
                continue
            name = (form.get(prefix + "name") or "").strip()
            value = (form.get(prefix + "form") or "").strip()
            if not name and not value:
                continue
            if not name or not value or name not in allowed_conjugation_names:
                raise ValueError(f"辞典{section_position}の活用形は、種類と形を正しく選んでください。")
            conjugations.append({"form": name, "conjugated": value})
        examples = []
        for example_position, example_index in enumerate(form_list(form, root + "example_indices"), 1):
            prefix = root + f"example_{example_index}_"
            if form.get(prefix + "remove") == "1":
                continue
            sentence = (form.get(prefix + "yonaguni") or "").strip()
            translations = {
                "ja": {"word_by_word": (form.get(prefix + "ja_word_by_word") or "").strip(), "free_translation": (form.get(prefix + "ja_free_translation") or "").strip()},
                "en": {"word_by_word": "", "free_translation": (form.get(prefix + "en_free_translation") or "").strip()},
                "zh-tw": {"word_by_word": "", "free_translation": (form.get(prefix + "zh_tw_free_translation") or "").strip()},
            }
            if not sentence and not any(value for translation in translations.values() for value in translation.values()):
                continue
            if not sentence:
                raise ValueError(f"辞典{section_position}の例文{example_position}に原文を入力してください。")
            examples.append({"yonaguni": sentence, "translations": translations})
        prior = base_by_source.get(str(source_id), {})
        sections.append({
            "source_id": source_id,
            "source_headword": (form.get(root + "source_headword") or "").strip(),
            "locator": (form.get(root + "locator") or "").strip(),
            "meanings": meanings,
            "synonyms": lines(form.get(root + "synonyms")),
            "conjugations": conjugations,
            "examples": examples,
            "etymology": (form.get(root + "etymology") or "").strip(),
            "historical_change": (form.get(root + "historical_change") or "").strip(),
            "note": (form.get(root + "note") or "").strip(),
            "legacy_record_ids": prior.get("legacy_record_ids", []),
        })
    return sections


def conjugations_from_rows(form, allowed_names=None):
    conjugations = []
    for position, index in enumerate(form_list(form, "conjugation_indices"), 1):
        prefix = f"conjugation_{index}_"
        if form.get(prefix + "remove") == "1":
            continue
        name = (form.get(prefix + "name") or "").strip()
        value = (form.get(prefix + "form") or "").strip()
        if not name and not value:
            continue
        if not name or not value:
            raise ValueError(f"活用形{position}は、種類と形の両方を入力してください。")
        if allowed_names is not None and name not in allowed_names:
            raise ValueError("活用形の種類を選び直してください。")
        conjugations.append({"form": name, "conjugated": value})
    return conjugations


def snapshot_from_form(form, base=None, allowed_conjugation_names=None, allowed_source_ids=None):
    base = base or {}
    headword = form.get("headword", "").strip()
    if not headword:
        raise ValueError("見出し語を入力してください。")
    pos = form.get("pos", "").strip()
    if pos and pos not in ALLOWED_POS:
        raise ValueError("品詞を選び直してください。")
    base_examples = base.get("examples", [])
    if form_list(form, "example_indices"):
        examples = examples_from_cards(form, base_examples)
    else:
        # Backwards compatibility for old imports and saved test/form clients.
        examples = []
        yonaguni = lines(form.get("examples_yonaguni"))
        for index, sentence in enumerate(yonaguni):
            prior = base_examples[index] if index < len(base_examples) else {}
            translations = dict(prior.get("translations", {}))
            for language, word_field, free_field in (("ja", "examples_word_by_word", "examples_free_translation"), ("en", "examples_en_word_by_word", "examples_en_free_translation"), ("zh-tw", "examples_zh_tw_word_by_word", "examples_zh_tw_free_translation")):
                words, frees = lines(form.get(word_field)), lines(form.get(free_field))
                new_translation = {"word_by_word": words[index] if index < len(words) else "", "free_translation": frees[index] if index < len(frees) else ""}
                if language == "ja" or any(new_translation.values()) or language not in translations:
                    translations[language] = new_translation
            examples.append({"id": prior.get("id"), "yonaguni": sentence, "translations": translations})
    if form_list(form, "meaning_indices"):
        meanings = meanings_from_cards(form)
    else:
        meanings = dict(base.get("meanings", {}))
        for language, field in (("ja", "meanings_ja"), ("en", "meanings_en"), ("zh-tw", "meanings_zh_tw")):
            if field in form:
                new_meanings = lines(form.get(field))
                if language == "ja" or new_meanings or not meanings.get(language) or form.get(f"clear_{field}"):
                    meanings[language] = new_meanings
    if form_list(form, "conjugation_indices"):
        conjugations = conjugations_from_rows(form, allowed_conjugation_names)
    else:
        conjugation_names = lines(form.get("conjugation_names"))
        conjugation_forms = lines(form.get("conjugation_forms"))
        conjugations = [{"form": name, "conjugated": conjugation_forms[i] if i < len(conjugation_forms) else ""}
                        for i, name in enumerate(conjugation_names)]
    if "source_section_indices" in form:
        source_sections = source_sections_from_form(
            form, base.get("source_sections", []), allowed_source_ids or set(), allowed_conjugation_names or set()
        )
    else:
        source_sections = list(base.get("source_sections", []))
    try:
        source_id = form.get("primary_source_id", type=int)
    except TypeError:
        try:
            source_id = int(form.get("primary_source_id") or 0) or None
        except (TypeError, ValueError):
            source_id = None
    return {
        "headword": headword,
        "kana": form.get("kana", "").strip(),
        "ipa": form.get("ipa", "").strip(),
        "pos": pos,
        "verb_class": form.get("verb_class", "").strip(),
        "verb_stem": form.get("verb_stem", "").strip(),
        "tone": form.get("tone", "").strip(),
        "etymology": form.get("etymology", "").strip(),
        "historical_change": form.get("historical_change", "").strip(),
        "supplemental_note": form.get("supplemental_note", "").strip(),
        "meanings": meanings,
        "synonyms": lines(form.get("synonyms")),
        "conjugations": conjugations,
        "examples": examples,
        "source_sections": source_sections,
        "primary_source_id": source_id,
    }


def current_entry_snapshot(db, entry_id):
    entry = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        return None
    meanings = {}
    for row in db.execute("SELECT language,meaning_number,definition FROM meanings WHERE entry_id=? ORDER BY language,meaning_number", (entry_id,)):
        meanings.setdefault(row["language"], []).append(row["definition"])
    examples = []
    for example in db.execute("SELECT * FROM examples WHERE entry_id=? ORDER BY id", (entry_id,)):
        translations = {}
        for trans in db.execute("SELECT * FROM example_translations WHERE example_id=?", (example["id"],)):
            translations[trans["language"]] = {
                "word_by_word": trans["word_by_word"] or "",
                "free_translation": trans["free_translation"] or "",
            }
        examples.append({"id": example["id"], "yonaguni": example["yonaguni_sentence"], "translations": translations})
    synonyms = [row[0] for row in db.execute("SELECT synonym FROM synonyms WHERE entry_id=? ORDER BY id", (entry_id,))]
    conjugations = [{"form": row[0], "conjugated": row[1]} for row in db.execute("SELECT form_name,conjugated_form FROM conjugations WHERE entry_id=? ORDER BY id", (entry_id,))]
    source = db.execute("SELECT source_id FROM entry_primary_sources WHERE entry_id=?", (entry_id,)).fetchone()
    source_sections = []
    for row in db.execute("SELECT source_id,content_json FROM entry_source_sections WHERE entry_id=? ORDER BY sort_order,id", (entry_id,)):
        content = json.loads(row["content_json"])
        content["source_id"] = row["source_id"]
        source_sections.append(content)
    return {
        "headword": entry["headword"], "kana": entry["kana"] or "", "ipa": entry["ipa"] or "",
        "pos": entry["pos"] or "", "verb_class": entry["verb_class"] or "",
        "verb_stem": entry["verb_stem"] or "", "tone": entry["tone"] or "",
        "etymology": entry["etymology"] or "", "historical_change": entry["historical_change"] or "",
        "supplemental_note": entry["supplemental_note"] or "",
        "meanings": meanings, "examples": examples, "synonyms": synonyms, "conjugations": conjugations,
        "source_sections": source_sections,
        "primary_source_id": source["source_id"] if source else None,
    }


def load_revision_snapshot(row):
    return json.loads(row["snapshot_json"])


def apply_snapshot(db, entry_id, snapshot):
    db.execute(
        "UPDATE entries SET headword=?,kana=?,ipa=?,pos=?,verb_class=?,verb_stem=?,tone=?,etymology=?,historical_change=?,supplemental_note=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (snapshot["headword"], snapshot.get("kana"), snapshot.get("ipa"), snapshot.get("pos"),
         snapshot.get("verb_class"), snapshot.get("verb_stem"), snapshot.get("tone"),
         snapshot.get("etymology"), snapshot.get("historical_change"), snapshot.get("supplemental_note"), entry_id),
    )
    db.execute("DELETE FROM meanings WHERE entry_id=?", (entry_id,))
    for language, meanings in snapshot.get("meanings", {}).items():
        db.executemany(
            "INSERT INTO meanings(entry_id,language,meaning_number,definition) VALUES(?,?,?,?)",
            ((entry_id, language, index, definition) for index, definition in enumerate(meanings, 1)),
        )
    db.execute("DELETE FROM synonyms WHERE entry_id=?", (entry_id,))
    db.executemany("INSERT INTO synonyms(entry_id,synonym) VALUES(?,?)", ((entry_id, value) for value in snapshot.get("synonyms", [])))
    db.execute("DELETE FROM conjugations WHERE entry_id=?", (entry_id,))
    db.executemany("INSERT INTO conjugations(entry_id,form_name,conjugated_form) VALUES(?,?,?)",
                   ((entry_id, item["form"], item["conjugated"]) for item in snapshot.get("conjugations", [])))
    source_id = snapshot.get("primary_source_id")
    if source_id:
        db.execute("INSERT INTO entry_primary_sources(entry_id,source_id,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
                   "ON CONFLICT(entry_id) DO UPDATE SET source_id=excluded.source_id,updated_at=CURRENT_TIMESTAMP", (entry_id, source_id))
    else:
        db.execute("DELETE FROM entry_primary_sources WHERE entry_id=?", (entry_id,))
    db.execute("DELETE FROM entry_source_sections WHERE entry_id=?", (entry_id,))
    for sort_order, section in enumerate(snapshot.get("source_sections", []), 1):
        content = {key: value for key, value in section.items() if key != "source_id"}
        db.execute(
            "INSERT INTO entry_source_sections(entry_id,source_id,sort_order,content_json) VALUES(?,?,?,?)",
            (entry_id, section["source_id"], sort_order, json.dumps(content, ensure_ascii=False)),
        )
    kept_ids = []
    for example in snapshot.get("examples", []):
        example_id = example.get("id")
        exists = example_id and db.execute("SELECT 1 FROM examples WHERE id=? AND entry_id=?", (example_id, entry_id)).fetchone()
        if exists:
            db.execute("UPDATE examples SET yonaguni_sentence=? WHERE id=?", (example["yonaguni"], example_id))
        else:
            example_id = db.execute("INSERT INTO examples(entry_id,yonaguni_sentence) VALUES(?,?)", (entry_id, example["yonaguni"])).lastrowid
        kept_ids.append(example_id)
        db.execute("INSERT INTO example_state(example_id,is_archived,archived_at) VALUES(?,0,NULL) ON CONFLICT(example_id) DO UPDATE SET is_archived=0,archived_at=NULL", (example_id,))
        for language, trans in example.get("translations", {}).items():
            db.execute("DELETE FROM example_translations WHERE example_id=? AND language=?", (example_id, language))
            db.execute("INSERT INTO example_translations(example_id,language,word_by_word,free_translation) VALUES(?,?,?,?)",
                       (example_id, language, trans.get("word_by_word"), trans.get("free_translation")))
    for row in db.execute("SELECT id FROM examples WHERE entry_id=?", (entry_id,)):
        if row["id"] not in kept_ids:
            db.execute("INSERT INTO example_state(example_id,is_archived,archived_at) VALUES(?,1,CURRENT_TIMESTAMP) ON CONFLICT(example_id) DO UPDATE SET is_archived=1,archived_at=CURRENT_TIMESTAMP", (row["id"],))
    return 0
