"""Read the recurring fieldwork workbook and prepare safe dictionary drafts.

The workbook is an XLSX (a ZIP of XML files).  The production application keeps
this reader dependency-free because the fixed survey format only needs cell
values; formulas, macros, styling and embedded objects are intentionally ignored.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from collections import OrderedDict, defaultdict
from difflib import SequenceMatcher
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from .search import normalize
from .workflow import ALLOWED_POS, current_entry_snapshot


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"x": MAIN_NS, "r": REL_NS}

MAX_ARCHIVE_FILES = 250
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_SHARED_STRINGS = 100_000
MAX_ROWS = 5_000
MAX_COLUMNS = 100
DITTO_MARKERS = {"〃", "//", "／／", "同上"}

HEADER_ALIASES = {
    "number": ("№", "no", "番号"),
    "headword": ("見出し語", "項目"),
    "meaning": ("意味・内容", "意味内容", "意味", "内容"),
    "pos": ("品詞",),
    "usage": ("その語を今も使うか", "使い方", "使用状況"),
    "example": ("例文",),
    "translation": ("訳文", "翻訳", "自由訳"),
    "source": ("ソース", "出典"),
    "date": ("精査日", "調査日", "日付"),
    "audio": ("音声",),
}

POS_MAP = {
    "名詞": "名詞",
    "動詞": "動詞",
    "形容詞": "形容詞",
    "副詞": "副詞",
    "助詞": "助詞",
    "感動詞": "感動詞",
    "連語": "連語",
    "慣用句": "連語",
    "その他": "その他",
}


class ResearchSheetError(ValueError):
    """A user-facing validation failure for a survey workbook."""


def _safe_xml(zipped, name):
    try:
        return ET.fromstring(zipped.read(name))
    except (KeyError, ET.ParseError, OSError, RuntimeError) as error:
        raise ResearchSheetError("Excelファイルの内部構造を読み取れませんでした。") from error


def _archive(data):
    try:
        zipped = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as error:
        raise ResearchSheetError("正しい .xlsx ファイルを選んでください。") from error
    infos = zipped.infolist()
    if len(infos) > MAX_ARCHIVE_FILES or sum(item.file_size for item in infos) > MAX_UNCOMPRESSED_BYTES:
        zipped.close()
        raise ResearchSheetError("Excelファイルが大きすぎるか、内部の項目が多すぎます。")
    for item in infos:
        path = PurePosixPath(item.filename)
        if path.is_absolute() or ".." in path.parts:
            zipped.close()
            raise ResearchSheetError("安全に読み取れないExcelファイルです。")
    if "xl/workbook.xml" not in zipped.namelist():
        zipped.close()
        raise ResearchSheetError("正しい .xlsx ファイルを選んでください。")
    return zipped


def _shared_strings(zipped):
    if "xl/sharedStrings.xml" not in zipped.namelist():
        return []
    root = _safe_xml(zipped, "xl/sharedStrings.xml")
    strings = []
    for item in root.findall("x:si", NS):
        strings.append(_rich_text(item))
        if len(strings) > MAX_SHARED_STRINGS:
            raise ResearchSheetError("Excelファイル内の文字列が多すぎます。")
    return strings


def _rich_text(item):
    # Excel stores optional pronunciation guides in rPh/t nodes.  They are
    # display metadata, not part of the cell text, so only direct text and
    # rich-text runs are joined here.
    parts = []
    for child in item:
        if child.tag == f"{{{MAIN_NS}}}t":
            parts.append(child.text or "")
        elif child.tag == f"{{{MAIN_NS}}}r":
            parts.extend(node.text or "" for node in child.findall("x:t", NS))
    return "".join(parts)


def _sheet_paths(zipped):
    workbook = _safe_xml(zipped, "xl/workbook.xml")
    rels = _safe_xml(zipped, "xl/_rels/workbook.xml.rels")
    targets = {
        rel.attrib.get("Id"): rel.attrib.get("Target", "")
        for rel in rels.findall(f"{{{PKG_REL_NS}}}Relationship")
    }
    sheets = []
    for sheet in workbook.findall("x:sheets/x:sheet", NS):
        rel_id = sheet.attrib.get(f"{{{REL_NS}}}id")
        target = targets.get(rel_id, "")
        if not target:
            continue
        target = target.lstrip("/")
        if target.startswith("xl/"):
            path = target
        else:
            path = str(PurePosixPath("xl") / target)
        if path in zipped.namelist():
            sheets.append((sheet.attrib.get("name", ""), path))
    if not sheets:
        raise ResearchSheetError("Excelファイル内に読み取れるシートがありません。")
    return sheets


def _column_index(reference):
    letters = re.match(r"[A-Za-z]+", reference or "")
    if not letters:
        return None
    value = 0
    for letter in letters.group(0).upper():
        value = value * 26 + ord(letter) - 64
    return value - 1


def _cell_value(cell, shared):
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        inline = cell.find("x:is", NS)
        return _rich_text(inline) if inline is not None else ""
    value = cell.findtext("x:v", default="", namespaces=NS)
    if not value:
        return ""
    if cell_type == "s":
        try:
            return shared[int(value)]
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        return "はい" if value == "1" else "いいえ"
    if cell_type in ("str", "e"):
        return value
    try:
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    except ValueError:
        return value


def _rows(zipped, path, shared):
    root = _safe_xml(zipped, path)
    rows = []
    for row_node in root.findall("x:sheetData/x:row", NS):
        try:
            row_number = int(row_node.attrib.get("r", len(rows) + 1))
        except ValueError:
            row_number = len(rows) + 1
        if row_number > MAX_ROWS:
            raise ResearchSheetError(f"シートの行数は{MAX_ROWS}行以内にしてください。")
        values = {}
        for cell in row_node.findall("x:c", NS):
            index = _column_index(cell.attrib.get("r"))
            if index is None or index >= MAX_COLUMNS:
                continue
            value = _clean(_cell_value(cell, shared))
            if value:
                values[index] = value
        if values:
            rows.append((row_number, values))
    return rows


def _clean(value):
    # Preserve dictionary orthography such as the spacing handakuten "゜".
    # Compatibility normalization is used only for matching, never for storage.
    value = unicodedata.normalize("NFC", str(value or ""))
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(part.rstrip() for part in value.split("\n")).strip()


def _header_key(value):
    value = unicodedata.normalize("NFKC", _clean(value))
    return re.sub(r"[\s・･:：()（）]", "", value).casefold()


def _match_headers(values):
    found = {}
    for index, value in values.items():
        key = _header_key(value)
        for field, aliases in HEADER_ALIASES.items():
            if any(_header_key(alias) == key or _header_key(alias) in key for alias in aliases):
                found.setdefault(field, index)
    return found


def _pick_data_sheet(zipped, shared):
    best = None
    for sheet_name, path in _sheet_paths(zipped):
        rows = _rows(zipped, path, shared)
        for position, (row_number, values) in enumerate(rows[:20]):
            headers = _match_headers(values)
            required = {"headword", "meaning", "example", "translation"}
            if not required.issubset(headers):
                continue
            score = len(headers) + (4 if _header_key(values.get(headers["headword"], "")) == _header_key("見出し語") else 0)
            candidate = (score, sheet_name, rows, position, row_number, headers)
            if best is None or score > best[0]:
                best = candidate
    if best is None:
        raise ResearchSheetError("「見出し語・意味・例文・訳文」の列がある調査シートを見つけられませんでした。")
    _score, sheet_name, rows, position, header_row, headers = best
    return sheet_name, rows[position + 1 :], header_row, headers


def _value(values, headers, field):
    index = headers.get(field)
    return _clean(values.get(index, "")) if index is not None else ""


def _strip_translation_wrapper(value):
    value = _clean(value)
    if len(value) >= 2 and ((value[0], value[-1]) in {("(", ")"), ("（", "）")}):
        return value[1:-1].strip()
    return value


def _append_unique(items, value):
    value = _clean(value)
    if value and normalize(value) not in {normalize(item) for item in items}:
        items.append(value)


def _normalize_pos(value, warnings, row_number):
    value = _clean(value)
    if not value:
        return ""
    matched = next((label for label in POS_MAP if value == label or value.startswith(label)), None)
    if matched:
        if matched == "慣用句":
            message = f"品詞「慣用句」を辞書の選択肢「連語」として取り込みます。"
            if message not in warnings:
                warnings.append(message)
        return POS_MAP[matched]
    warnings.append(f"行{row_number}: 品詞「{value}」は選択肢にないため「その他」として取り込みます。")
    return "その他"


def parse_research_workbook(data, filename="調査シート.xlsx"):
    """Return grouped entry drafts from the workbook's primary survey sheet."""
    if not data:
        raise ResearchSheetError("Excelファイルを選んでください。")
    zipped = _archive(data)
    try:
        shared = _shared_strings(zipped)
        sheet_name, rows, header_row, headers = _pick_data_sheet(zipped, shared)
    finally:
        zipped.close()

    groups = OrderedDict()
    skipped_rows = []
    previous_headword = ""
    last_meaning_by_headword = {}
    for row_number, values in rows:
        headword = _value(values, headers, "headword")
        if headword in DITTO_MARKERS:
            headword = previous_headword
        if not headword:
            if any(_value(values, headers, field) for field in ("meaning", "example", "translation", "pos")):
                skipped_rows.append(row_number)
            continue
        previous_headword = headword
        key = normalize(headword)
        if not key:
            skipped_rows.append(row_number)
            continue
        group = groups.setdefault(key, {
            "headword": headword,
            "pos": "",
            "meanings": [],
            "examples": [],
            "row_numbers": [],
            "survey_numbers": [],
            "usage_notes": [],
            "source_notes": [],
            "survey_dates": [],
            "audio_notes": [],
            "warnings": [],
        })
        group["row_numbers"].append(row_number)
        _append_unique(group["survey_numbers"], _value(values, headers, "number"))

        row_pos = _normalize_pos(_value(values, headers, "pos"), group["warnings"], row_number)
        if row_pos and not group["pos"]:
            group["pos"] = row_pos
        elif row_pos and group["pos"] != row_pos:
            group["warnings"].append(
                f"行{row_number}: 同じ見出し語に複数の品詞（{group['pos']} / {row_pos}）があります。先頭の品詞を使います。"
            )

        meaning = _value(values, headers, "meaning")
        if meaning in DITTO_MARKERS:
            meaning = last_meaning_by_headword.get(key, "")
        elif meaning:
            last_meaning_by_headword[key] = meaning
        _append_unique(group["meanings"], meaning)

        sentence = _value(values, headers, "example")
        translation = _strip_translation_wrapper(_value(values, headers, "translation"))
        if sentence:
            example = {
                "yonaguni": sentence,
                "translations": {
                    "ja": {"word_by_word": "", "free_translation": translation}
                },
            }
            signature = (normalize(sentence), normalize(translation))
            existing = {
                (normalize(item["yonaguni"]), normalize(item.get("translations", {}).get("ja", {}).get("free_translation", "")))
                for item in group["examples"]
            }
            if signature not in existing:
                group["examples"].append(example)
        elif translation:
            group["warnings"].append(f"行{row_number}: 訳文はありますが例文が空のため、訳文は補足情報に残します。")
            _append_unique(group["usage_notes"], f"例文なしの訳文: {translation}")

        for field, destination in (
            ("usage", "usage_notes"),
            ("source", "source_notes"),
            ("date", "survey_dates"),
            ("audio", "audio_notes"),
        ):
            _append_unique(group[destination], _value(values, headers, field))

    if not groups:
        raise ResearchSheetError("見出し語が入力された行を見つけられませんでした。")

    entries = []
    safe_filename = PurePosixPath(str(filename or "調査シート.xlsx").replace("\\", "/")).name[:120]
    for group in groups.values():
        note_lines = [
            f"定期調査シート: {safe_filename} / {sheet_name} / Excel行 {', '.join(map(str, group['row_numbers']))}"
        ]
        if group["survey_numbers"]:
            note_lines.append("調査番号: " + ", ".join(group["survey_numbers"]))
        for label, field in (
            ("使用状況", "usage_notes"),
            ("シート記載のソース", "source_notes"),
            ("精査日", "survey_dates"),
            ("音声欄", "audio_notes"),
        ):
            if group[field]:
                note_lines.append(f"{label}: " + " / ".join(group[field]))
        entries.append({
            "headword": group["headword"],
            "kana": "",
            "ipa": "",
            "pos": group["pos"] if not group["pos"] or group["pos"] in ALLOWED_POS else "その他",
            "verb_class": "",
            "verb_stem": "",
            "tone": "",
            "etymology": "",
            "historical_change": "",
            "supplemental_note": "\n".join(note_lines),
            "meanings": {"ja": group["meanings"], "en": [], "zh-tw": []},
            "synonyms": [],
            "conjugations": [],
            "examples": group["examples"],
            "source_sections": [],
            "primary_source_id": None,
            "row_numbers": group["row_numbers"],
            "warnings": group["warnings"],
        })
    global_warnings = []
    if skipped_rows:
        global_warnings.append(
            "見出し語が空のため取り込まなかった行: " + ", ".join(map(str, skipped_rows[:30]))
        )
    return {
        "kind": "research_sheet",
        "sheet_name": sheet_name,
        "header_row": header_row,
        "entries": entries,
        "warnings": global_warnings,
    }


def _similarity_text(value):
    return re.sub(r"[\s\-‐‑–—'’‘\[\]()（）・･.,、。]", "", normalize(value))


def _prepared_ratio(left, right):
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _content_ratio(left, right):
    """Avoid expensive fuzzy comparison for clearly unrelated long text."""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    shorter = min(len(left), len(right))
    if shorter < 4:
        return 0.0
    left_pairs = {left[index : index + 2] for index in range(len(left) - 1)}
    right_pairs = {right[index : index + 2] for index in range(len(right) - 1)}
    overlap = len(left_pairs & right_pairs) / max(1, min(len(left_pairs), len(right_pairs)))
    if overlap < 0.3:
        return 0.0
    return _prepared_ratio(left, right)


def duplicate_corpus(db):
    """Load existing comparison data once for a whole workbook preview."""
    rows = db.execute(
        "SELECT e.id,e.headword,e.kana,e.pos,w.publication_status,w.workflow_status,"
        "EXISTS(SELECT 1 FROM review_requests rr JOIN entry_revisions r ON r.id=rr.revision_id "
        "WHERE r.entry_id=e.id AND rr.status='pending') has_pending_review,"
        "EXISTS(SELECT 1 FROM entry_revisions r WHERE r.entry_id=e.id AND r.status IN ('draft','returned','admin_review')) has_open_draft "
        "FROM entries e LEFT JOIN entry_workflow w ON w.entry_id=e.id "
        "WHERE COALESCE(w.publication_status,'unpublished')!='archived' ORDER BY e.id"
    ).fetchall()
    meanings_by_entry = defaultdict(list)
    for row in db.execute(
        "SELECT entry_id,definition FROM meanings WHERE language='ja' ORDER BY entry_id,meaning_number"
    ):
        if len(meanings_by_entry[row["entry_id"]]) < 5:
            meanings_by_entry[row["entry_id"]].append(row["definition"])
    examples_by_entry = defaultdict(list)
    for row in db.execute(
        "SELECT ex.entry_id,ex.yonaguni_sentence FROM examples ex "
        "LEFT JOIN example_state es ON es.example_id=ex.id "
        "WHERE COALESCE(es.is_archived,0)=0 ORDER BY ex.entry_id,ex.id"
    ):
        if len(examples_by_entry[row["entry_id"]]) < 5:
            examples_by_entry[row["entry_id"]].append(row["yonaguni_sentence"])
    return [{
        "row": dict(row),
        "meanings": meanings_by_entry[row["id"]],
        "examples": examples_by_entry[row["id"]],
        "headword_key": _similarity_text(row["headword"]),
        "meaning_keys": [_similarity_text(value) for value in meanings_by_entry[row["id"]]],
        "example_keys": [_similarity_text(value) for value in examples_by_entry[row["id"]]],
    } for row in rows]


def duplicate_candidates(db, imported, limit=5, corpus=None):
    """Find exact and plausible existing-entry matches for a parsed draft."""
    imported_headword = imported.get("headword", "")
    imported_meanings = imported.get("meanings", {}).get("ja", [])
    imported_examples = [item.get("yonaguni", "") for item in imported.get("examples", [])]
    imported_headword_key = _similarity_text(imported_headword)
    imported_meaning_keys = [_similarity_text(value) for value in imported_meanings]
    imported_example_keys = [_similarity_text(value) for value in imported_examples]
    corpus = corpus if corpus is not None else duplicate_corpus(db)
    candidates = []
    imported_normalized = normalize(imported_headword)
    for existing in corpus:
        row = existing["row"]
        meanings = existing["meanings"]
        exact = normalize(row["headword"]) == imported_normalized
        headword_score = _prepared_ratio(imported_headword_key, existing["headword_key"])
        meaning_score = max(
            (_content_ratio(incoming, current) for incoming in imported_meaning_keys for current in existing["meaning_keys"]),
            default=0.0,
        )
        example_score = max(
            (_content_ratio(incoming, current) for incoming in imported_example_keys for current in existing["example_keys"]),
            default=0.0,
        )
        exact_example = any(
            incoming and incoming == current
            for incoming in imported_example_keys for current in existing["example_keys"]
        )
        if not exact and headword_score < 0.62 and meaning_score < 0.72 and example_score < 0.78:
            continue
        score = 1.0 if exact else max(headword_score, meaning_score * 0.92, example_score * 0.9)
        reasons = []
        if exact:
            reasons.append("見出し語が完全一致")
        elif headword_score >= 0.62:
            reasons.append(f"見出し語が{round(headword_score * 100)}%類似")
        if meaning_score >= 0.72:
            reasons.append(f"意味が{round(meaning_score * 100)}%類似")
        if exact_example:
            reasons.append("例文が完全一致")
        elif example_score >= 0.78:
            reasons.append(f"例文が{round(example_score * 100)}%類似")
        blocked = bool(row["has_pending_review"] or row["has_open_draft"] or row["workflow_status"] in ("draft", "review_requested", "returned", "admin_review"))
        candidates.append({
            "id": row["id"],
            "headword": row["headword"],
            "kana": row["kana"] or "",
            "pos": row["pos"] or "",
            "meanings": meanings,
            "examples": existing["examples"],
            "publication_status": row["publication_status"] or "unpublished",
            "workflow_status": row["workflow_status"] or "unreviewed",
            "exact": exact,
            "score": score,
            "reasons": reasons,
            "merge_blocked": blocked,
            "blocked_reason": "この語彙は下書き・相互確認中です" if blocked else "",
        })
    return sorted(candidates, key=lambda item: (-int(item["exact"]), -item["score"], item["id"]))[:limit]


def merge_imported_snapshot(base, imported):
    """Append workbook data without deleting or overwriting existing content."""
    merged = {
        "headword": base.get("headword", imported.get("headword", "")),
        "kana": base.get("kana", ""),
        "ipa": base.get("ipa", ""),
        "pos": base.get("pos", "") or imported.get("pos", ""),
        "verb_class": base.get("verb_class", ""),
        "verb_stem": base.get("verb_stem", ""),
        "tone": base.get("tone", ""),
        "etymology": base.get("etymology", ""),
        "historical_change": base.get("historical_change", ""),
        "supplemental_note": base.get("supplemental_note", ""),
        "meanings": {language: list(values) for language, values in base.get("meanings", {}).items()},
        "synonyms": list(base.get("synonyms", [])),
        "conjugations": list(base.get("conjugations", [])),
        "examples": list(base.get("examples", [])),
        "source_sections": list(base.get("source_sections", [])),
        "primary_source_id": base.get("primary_source_id"),
    }
    for language, values in imported.get("meanings", {}).items():
        merged["meanings"].setdefault(language, [])
        for value in values:
            _append_unique(merged["meanings"][language], value)

    example_by_sentence = {normalize(item.get("yonaguni", "")): item for item in merged["examples"]}
    for incoming in imported.get("examples", []):
        sentence_key = normalize(incoming.get("yonaguni", ""))
        existing = example_by_sentence.get(sentence_key)
        if not existing:
            copied = {
                "yonaguni": incoming.get("yonaguni", ""),
                "translations": {
                    language: dict(translation)
                    for language, translation in incoming.get("translations", {}).items()
                },
            }
            merged["examples"].append(copied)
            example_by_sentence[sentence_key] = copied
            continue
        existing.setdefault("translations", {})
        for language, translation in incoming.get("translations", {}).items():
            target = existing["translations"].setdefault(language, {"word_by_word": "", "free_translation": ""})
            for field in ("word_by_word", "free_translation"):
                if not target.get(field) and translation.get(field):
                    target[field] = translation[field]

    note = imported.get("supplemental_note", "").strip()
    if note and note not in merged["supplemental_note"]:
        merged["supplemental_note"] = "\n\n".join(filter(None, (merged["supplemental_note"].strip(), note)))
    return merged


def existing_snapshot_for_merge(db, entry_id):
    row = db.execute(
        "SELECT e.id,w.workflow_status,"
        "EXISTS(SELECT 1 FROM review_requests rr JOIN entry_revisions r ON r.id=rr.revision_id "
        "WHERE r.entry_id=e.id AND rr.status='pending') has_pending_review,"
        "EXISTS(SELECT 1 FROM entry_revisions r WHERE r.entry_id=e.id AND r.status IN ('draft','returned','admin_review')) has_open_draft "
        "FROM entries e LEFT JOIN entry_workflow w ON w.entry_id=e.id WHERE e.id=?",
        (entry_id,),
    ).fetchone()
    if not row:
        raise ResearchSheetError("統合先の語彙が見つかりません。")
    if row["has_pending_review"] or row["has_open_draft"] or row["workflow_status"] in ("draft", "review_requested", "returned", "admin_review"):
        raise ResearchSheetError("統合先の語彙は下書き・相互確認中です。先にその作業を完了してください。")
    return current_entry_snapshot(db, entry_id)
