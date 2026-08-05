import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from werkzeug.security import generate_password_hash
from werkzeug.datastructures import MultiDict

from v2app import create_app
from scripts.upgrade_v2 import apply_upgrades
from v2app.search import normalize, rebuild_search_index, search_entries
from v2app.research_sheet import merge_imported_for_source, parse_research_workbook
from v2app.workflow import snapshot_from_form

ROOT = Path(__file__).resolve().parent.parent


def research_workbook(rows):
    """Build the small, fixed-format XLSX used by importer tests."""
    all_rows = [["№", "見出し語", "意味・内容", "品詞", "その語を今も使うか", "例文", "訳文", "ソース", "精査日", "音声"]] + rows
    row_xml = []
    shared_strings = []
    for row_number, values in enumerate(all_rows, 1):
        cells = []
        for index, value in enumerate(values):
            if value in (None, ""):
                continue
            column = chr(ord("A") + index)
            if isinstance(value, tuple) and value[0] == "phonetic":
                shared_index = len(shared_strings)
                shared_strings.append(
                    f'<si><t>{escape(value[1])}</t><rPh sb="0" eb="1"><t>{escape(value[2])}</t></rPh></si>'
                )
                cells.append(f'<c r="{column}{row_number}" t="s"><v>{shared_index}</v></c>')
            else:
                cells.append(
                    f'<c r="{column}{row_number}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                )
        row_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="№3" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
        if shared_strings:
            archive.writestr(
                "xl/sharedStrings.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                + "".join(shared_strings) + "</sst>",
            )
    return output.getvalue()


class V2AppTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "test.db"
        source = sqlite3.connect(ROOT / "v6" / "database" / "yonaguni_dict.db")
        target = sqlite3.connect(self.database)
        source.backup(target)
        source.close()
        apply_upgrades(target)
        target.execute(
            "INSERT INTO users(username, display_name, password_hash, role) VALUES (?, ?, ?, ?)",
            ("admin", "管理者", generate_password_hash("correct horse battery staple", method="pbkdf2:sha256:1000"), "admin"),
        )
        target.execute(
            "INSERT INTO users(username, display_name, password_hash, role) VALUES (?, ?, ?, ?)",
            ("reviewer", "確認担当", generate_password_hash("reviewer password long", method="pbkdf2:sha256:1000"), "editor"),
        )
        target.commit()
        target.close()
        self.app = create_app({"TESTING": True, "DATABASE": str(self.database)})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def csrf(self):
        self.client.get("/v2/login")
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def login(self, username="admin", password="correct horse battery staple"):
        return self.client.post("/v2/login", data={
            "csrf_token": self.csrf(), "username": username, "password": password
        })

    def create_draft(self):
        self.login()
        token = self.csrf()
        response = self.client.post("/v2/entries/new", data={
            "csrf_token": token, "headword": "てすとぅ", "kana": "てすとぅ", "ipa": "tesutu",
            "pos": "名詞", "meanings_ja": "試験\n確認",
            "examples_yonaguni": "てすとぅぬ あん",
            "examples_word_by_word": "試験-が ある", "examples_free_translation": "試験がある",
        })
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.database) as db:
            return db.execute("SELECT MAX(id) FROM entries").fetchone()[0]

    def test_foreign_keys_are_enabled(self):
        with self.app.app_context():
            from v2app.db import get_db
            self.assertEqual(get_db().execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_login_requires_csrf(self):
        response = self.client.post("/v2/login", data={"username": "admin", "password": "x"})
        self.assertEqual(response.status_code, 400)

    def test_hashed_login_and_dashboard(self):
        self.login()
        response = self.client.get("/v2/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn("管理者さん".encode(), response.data)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("Content-Security-Policy", response.headers)

    def test_wrong_password_is_not_logged_in(self):
        response = self.client.post("/v2/login", data={
            "csrf_token": self.csrf(), "username": "admin", "password": "wrong"
        }, follow_redirects=True)
        self.assertNotIn("管理者さん".encode(), response.data)

    def test_database_rejects_self_review(self):
        db = sqlite3.connect(self.database)
        user_id = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        entry_id = db.execute("SELECT id FROM entries LIMIT 1").fetchone()[0]
        revision_id = db.execute(
            "INSERT INTO entry_revisions(entry_id, author_id, snapshot_json) VALUES (?, ?, '{}') RETURNING id",
            (entry_id, user_id),
        ).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO review_requests(revision_id, requester_id, reviewer_id) VALUES (?, ?, ?)",
                (revision_id, user_id, user_id),
            )
        db.close()

    def test_complete_review_flow_publishes_snapshot(self):
        entry_id = self.create_draft()
        with sqlite3.connect(self.database) as db:
            reviewer_id = db.execute("SELECT id FROM users WHERE username='reviewer'").fetchone()[0]
        response = self.client.post(f"/v2/entries/{entry_id}/request-review", data={
            "csrf_token": self.csrf(), "reviewer_id": reviewer_id,
        })
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.database) as db:
            review_id = db.execute("SELECT MAX(id) FROM review_requests").fetchone()[0]
        with self.client.session_transaction() as session:
            session.clear()
        self.login("reviewer", "reviewer password long")
        response = self.client.post(f"/v2/reviews/{review_id}", data={
            "csrf_token": self.csrf(), "decision": "approved", "comment": "確認しました",
        })
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.database) as db:
            state = db.execute("SELECT workflow_status,publication_status FROM entry_workflow WHERE entry_id=?", (entry_id,)).fetchone()
            definitions = db.execute("SELECT definition FROM meanings WHERE entry_id=? ORDER BY meaning_number", (entry_id,)).fetchall()
            audit_count = db.execute("SELECT COUNT(*) FROM audit_logs WHERE entity_type='review'").fetchone()[0]
        self.assertEqual(state, ("verified", "published"))
        self.assertEqual(definitions, [("試験",), ("確認",)])
        self.assertGreaterEqual(audit_count, 2)

    def test_return_requires_comment(self):
        entry_id = self.create_draft()
        with sqlite3.connect(self.database) as db:
            reviewer_id = db.execute("SELECT id FROM users WHERE username='reviewer'").fetchone()[0]
        self.client.post(f"/v2/entries/{entry_id}/request-review", data={"csrf_token": self.csrf(), "reviewer_id": reviewer_id})
        with sqlite3.connect(self.database) as db:
            review_id = db.execute("SELECT MAX(id) FROM review_requests").fetchone()[0]
        with self.client.session_transaction() as session:
            session.clear()
        self.login("reviewer", "reviewer password long")
        response = self.client.post(f"/v2/reviews/{review_id}", data={"csrf_token": self.csrf(), "decision": "returned", "comment": ""})
        self.assertEqual(response.status_code, 400)
        with sqlite3.connect(self.database) as db:
            status = db.execute("SELECT status FROM review_requests WHERE id=?", (review_id,)).fetchone()[0]
        self.assertEqual(status, "pending")

    def test_unicode_normalization(self):
        self.assertEqual(normalize("ＡＩＧＵＮＧ　’TEST’"), normalize("aigung 'test'"))

    def test_blank_translation_field_does_not_erase_existing_language(self):
        base={"meanings":{"ja":["日本語"],"en":["existing English"]},"examples":[]}
        form={"headword":"語","pos":"名詞","meanings_ja":"日本語","meanings_en":""}
        self.assertEqual(snapshot_from_form(form,base)["meanings"]["en"],["existing English"])
        form["clear_meanings_en"]="1"
        self.assertEqual(snapshot_from_form(form,base)["meanings"]["en"],[])

    def test_example_cards_keep_each_translation_with_its_sentence(self):
        form = MultiDict([
            ("headword", "語"), ("pos", "名詞"), ("example_indices", "0"), ("example_indices", "1"),
            ("example_0_yonaguni", "例文一"), ("example_0_ja_word_by_word", "一-逐語"),
            ("example_0_ja_free_translation", "一の意訳"), ("example_0_en_free_translation", "first"),
            ("example_1_yonaguni", "例文二"), ("example_1_ja_word_by_word", "二-逐語"),
            ("example_1_ja_free_translation", "二の意訳"), ("example_1_zh_tw_free_translation", "第二句"),
        ])
        examples = snapshot_from_form(form)["examples"]
        self.assertEqual(examples[0]["translations"]["ja"]["free_translation"], "一の意訳")
        self.assertEqual(examples[0]["translations"]["en"]["free_translation"], "first")
        self.assertEqual(examples[1]["translations"]["ja"]["word_by_word"], "二-逐語")
        self.assertEqual(examples[1]["translations"]["zh-tw"]["free_translation"], "第二句")

    def test_research_workbook_groups_repeated_headwords_and_ditto_meaning(self):
        workbook = research_workbook([
            [1, "すい", ("phonetic", "水", "ミズ"), "名詞メイシ", "使う", "例文一", "（一つ目の訳）", "調査", "2026-08-01", ""],
            [2, "すい", "〃", "名詞メイシ", "", "例文二", "二つ目の訳", "", "", ""],
            [3, "すーあったに", "急に゜", "慣用句カンヨウク", "", "", "", "", "", ""],
        ])
        parsed = parse_research_workbook(workbook, "毎週調査.xlsx")
        self.assertEqual(parsed["sheet_name"], "№3")
        self.assertEqual(len(parsed["entries"]), 2)
        entry = parsed["entries"][0]
        self.assertEqual(entry["headword"], "すい")
        self.assertEqual(entry["pos"], "名詞")
        self.assertEqual(entry["meanings"]["ja"], ["水"])
        self.assertEqual(len(entry["examples"]), 2)
        self.assertEqual(entry["examples"][0]["translations"]["ja"]["free_translation"], "一つ目の訳")
        self.assertIn("毎週調査.xlsx", entry["supplemental_note"])
        self.assertEqual(parsed["entries"][1]["pos"], "連語")
        self.assertEqual(parsed["entries"][1]["meanings"]["ja"], ["急に゜"])

    def test_repeated_import_appends_to_the_same_dictionary_section(self):
        base = {
            "headword": "統合語", "meanings": {"ja": ["町の意味"]}, "examples": [],
            "source_sections": [{
                "source_id": 7, "source_headword": "統合語", "locator": "",
                "meanings": {"ja": ["以前の辞典記述"]}, "synonyms": [], "conjugations": [],
                "examples": [], "etymology": "", "historical_change": "", "note": "", "legacy_record_ids": [],
            }],
            "primary_source_id": None,
        }
        imported = {
            "headword": "統合語", "pos": "名詞", "meanings": {"ja": ["今回の辞典記述"]},
            "examples": [{"yonaguni": "辞典例文", "translations": {"ja": {"word_by_word": "", "free_translation": "訳"}}}],
            "supplemental_note": "月例調査",
        }
        merged = merge_imported_for_source(base, imported, 7)
        self.assertEqual(merged["meanings"]["ja"], ["町の意味"])
        self.assertEqual(merged["source_sections"][0]["meanings"]["ja"], ["以前の辞典記述", "今回の辞典記述"])
        self.assertEqual(merged["source_sections"][0]["examples"][0]["yonaguni"], "辞典例文")
        self.assertEqual(merged["source_sections"][0]["note"], "月例調査")

    def test_research_sheet_import_can_merge_create_and_send_batch_review(self):
        self.login()
        with sqlite3.connect(self.database) as db:
            admin_id = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            reviewer_id = db.execute("SELECT id FROM users WHERE username='reviewer'").fetchone()[0]
            source_id = db.execute(
                "INSERT INTO sources(name,abbreviation,bibliography) VALUES('zz調査辞典','zz調査','調査辞典の書誌') RETURNING id"
            ).fetchone()[0]
            existing_id = db.execute(
                "INSERT INTO entries(headword,pos) VALUES('zz調査','名詞') RETURNING id"
            ).fetchone()[0]
            db.execute(
                "INSERT INTO meanings(entry_id,language,meaning_number,definition) VALUES(?,'ja',1,'既存の意味')",
                (existing_id,),
            )
            db.execute(
                "INSERT INTO entry_workflow(entry_id,publication_status,workflow_status,created_by) "
                "VALUES(?,'published','verified',?)",
                (existing_id, admin_id),
            )
            db.commit()
        workbook = research_workbook([
            [1, "zz調査", "追加する意味", "名詞", "", "zz例文", "追加の訳", "", "", ""],
            [2, "zz新語", "新しい意味", "動詞", "", "zz新語ぬ例文", "新語の訳", "", "", ""],
        ])
        response = self.client.post(
            "/v2/admin-tools/research-sheet",
            data={
                "csrf_token": self.csrf(),
                "research_sheet": (io.BytesIO(workbook), "weekly.xlsx"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        batch_id = int(response.location.rstrip("/").split("/")[-1])
        preview = self.client.get(response.location)
        self.assertEqual(preview.status_code, 200)
        self.assertIn("見出し語が完全一致".encode(), preview.data)
        self.assertIn("一括で精査依頼".encode(), preview.data)

        applied = self.client.post(
            f"/v2/admin-tools/research-sheet/{batch_id}/apply",
            data={
                "csrf_token": self.csrf(),
                "action_0": "merge",
                "target_0": str(existing_id),
                "action_1": "new",
                "source_id": str(source_id),
                "reviewer_mode": str(reviewer_id),
            },
        )
        self.assertEqual(applied.status_code, 302)
        result_page = self.client.get(applied.location)
        self.assertEqual(result_page.status_code, 200)
        self.assertIn("処理完了".encode(), result_page.data)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(
                db.execute(
                    "SELECT definition FROM meanings WHERE entry_id=? ORDER BY meaning_number", (existing_id,)
                ).fetchall(),
                [("既存の意味",)],
            )
            merge_revision = db.execute(
                "SELECT snapshot_json,status FROM entry_revisions WHERE entry_id=? ORDER BY id DESC LIMIT 1",
                (existing_id,),
            ).fetchone()
            merged_snapshot = json.loads(merge_revision[0])
            self.assertEqual(merged_snapshot["meanings"]["ja"], ["既存の意味"])
            self.assertEqual(merged_snapshot["source_sections"][0]["source_id"], source_id)
            self.assertEqual(merged_snapshot["source_sections"][0]["meanings"]["ja"], ["追加する意味"])
            self.assertEqual(merged_snapshot["source_sections"][0]["examples"][0]["yonaguni"], "zz例文")
            self.assertEqual(merge_revision[1], "review_requested")
            new_entry = db.execute("SELECT id FROM entries WHERE headword='zz新語' ORDER BY id DESC LIMIT 1").fetchone()
            new_revision = json.loads(db.execute(
                "SELECT snapshot_json FROM entry_revisions WHERE entry_id=? ORDER BY id DESC LIMIT 1", new_entry
            ).fetchone()[0])
            self.assertEqual(new_revision["primary_source_id"], source_id)
            new_state = db.execute(
                "SELECT publication_status,workflow_status FROM entry_workflow WHERE entry_id=?", new_entry
            ).fetchone()
            self.assertEqual(new_state, ("unpublished", "review_requested"))
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM review_requests WHERE requester_id=? AND reviewer_id=? AND status='pending'",
                    (admin_id, reviewer_id),
                ).fetchone()[0],
                2,
            )
            result = json.loads(
                db.execute("SELECT result_json FROM import_batches WHERE id=?", (batch_id,)).fetchone()[0]
            )
            self.assertEqual(len(result["created"]), 1)
            self.assertEqual(len(result["merged"]), 1)
            self.assertEqual(len(result["review_requests"]), 2)
            self.assertEqual(result["source_id"], source_id)
            self.assertEqual(result["source_name"], "zz調査辞典")
        history = self.client.get("/v2/admin-tools/research-sheet/history")
        self.assertEqual(history.status_code, 200)
        self.assertIn("weekly.xlsx".encode(), history.data)
        self.assertIn("zz調査辞典".encode(), history.data)
        self.assertIn("zz調査".encode(), history.data)

    def test_research_sheet_manual_merge_target_searches_headword_and_meaning(self):
        self.login()
        with sqlite3.connect(self.database) as db:
            admin_id = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            entry_id = db.execute(
                "INSERT INTO entries(headword,kana,ipa,pos) VALUES('zz手動合併先','てどう','tedou','名詞') RETURNING id"
            ).fetchone()[0]
            db.execute(
                "INSERT INTO meanings(entry_id,language,meaning_number,definition) VALUES(?,'ja',1,'特別な手動検索の意味')",
                (entry_id,),
            )
            db.execute(
                "INSERT INTO entry_workflow(entry_id,publication_status,workflow_status,created_by) VALUES(?,'published','verified',?)",
                (entry_id, admin_id),
            )
            db.commit()
        response = self.client.get("/v2/admin-tools/research-sheet/search-targets?q=特別な手動検索")
        self.assertEqual(response.status_code, 200)
        result = response.get_json()["results"]
        self.assertEqual(result[0]["id"], entry_id)
        self.assertIn("意味", result[0]["matched_fields"])
        response = self.client.get("/v2/admin-tools/research-sheet/search-targets?q=zz手動")
        self.assertEqual(response.get_json()["results"][0]["id"], entry_id)

    def test_public_entry_labels_primary_dictionary_source(self):
        with sqlite3.connect(self.database) as db:
            admin_id = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            entry_id = db.execute("INSERT INTO entries(headword,pos) VALUES('zz公開語','名詞') RETURNING id").fetchone()[0]
            db.execute(
                "INSERT INTO entry_workflow(entry_id,publication_status,workflow_status,created_by) VALUES(?,'published','verified',?)",
                (entry_id, admin_id),
            )
            source_id = db.execute(
                "INSERT INTO sources(name,abbreviation,bibliography,url) VALUES('zz公開出典','公開','公開書誌','https://example.test/source') RETURNING id"
            ).fetchone()[0]
            db.execute(
                "INSERT INTO entry_primary_sources(entry_id,source_id) VALUES(?,?) ON CONFLICT(entry_id) DO UPDATE SET source_id=excluded.source_id",
                (entry_id, source_id),
            )
            db.commit()
        response = self.client.get(f"/word/{entry_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("zz公開出典".encode(), response.data)
        self.assertIn("公開書誌".encode(), response.data)

    def test_hidden_town_source_stays_separate_but_reads_as_regular_content(self):
        with sqlite3.connect(self.database) as db:
            admin_id = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            entry_id = db.execute("INSERT INTO entries(headword,pos) VALUES('zz例会語','名詞') RETURNING id").fetchone()[0]
            db.execute(
                "INSERT INTO meanings(entry_id,language,meaning_number,definition) VALUES(?,'ja',1,'既存の町辞典の意味')",
                (entry_id,),
            )
            db.execute(
                "INSERT INTO entry_workflow(entry_id,publication_status,workflow_status,created_by) VALUES(?,'published','verified',?)",
                (entry_id, admin_id),
            )
            source_id = db.execute(
                "INSERT INTO sources(name,bibliography,show_on_public) VALUES('zz町例会2026','町例会内部記録',0) RETURNING id"
            ).fetchone()[0]
            content = {
                "source_headword": "zz例会語", "locator": "第3回", "meanings": {"ja": ["例会で追加した意味"]},
                "synonyms": ["例会同義語"], "conjugations": [{"form": "基本形", "conjugated": "例会形"}],
                "examples": [{"yonaguni": "例会ぬ例文", "translations": {"ja": {"word_by_word": "", "free_translation": "例会の訳"}}}],
                "etymology": "", "historical_change": "", "note": "例会で確認した補足",
            }
            db.execute(
                "INSERT INTO entry_source_sections(entry_id,source_id,sort_order,content_json) VALUES(?,?,1,?)",
                (entry_id, source_id, json.dumps(content, ensure_ascii=False)),
            )
            db.commit()
        response = self.client.get(f"/word/{entry_id}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("zz町例会2026".encode(), response.data)
        self.assertNotIn("町例会内部記録".encode(), response.data)
        self.assertIn("既存の町辞典の意味".encode(), response.data)
        self.assertIn("例会で追加した意味".encode(), response.data)
        self.assertIn("例会ぬ例文".encode(), response.data)
        self.assertIn("例会形".encode(), response.data)
        self.assertIn("例会で確認した補足".encode(), response.data)

    def test_source_manager_can_mark_a_source_as_internal_only(self):
        self.login()
        response = self.client.post("/v2/sources", data={
            "csrf_token": self.csrf(), "name": "zz内部例会", "bibliography": "内部の完全情報",
            "source_type": "例会", "show_on_public": "0",
        })
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT show_on_public FROM sources WHERE name='zz内部例会'").fetchone()
        self.assertEqual(row, (0,))
        page = self.client.get("/v2/sources")
        self.assertIn("出典名は非表示（町側データ）".encode(), page.data)

    def test_approved_entry_is_publicly_searchable(self):
        entry_id = self.create_draft()
        with sqlite3.connect(self.database) as db:
            reviewer_id = db.execute("SELECT id FROM users WHERE username='reviewer'").fetchone()[0]
        self.client.post(f"/v2/entries/{entry_id}/request-review", data={"csrf_token":self.csrf(),"reviewer_id":reviewer_id})
        with sqlite3.connect(self.database) as db: review_id=db.execute("SELECT MAX(id) FROM review_requests").fetchone()[0]
        with self.client.session_transaction() as session: session.clear()
        self.login("reviewer","reviewer password long")
        self.client.post(f"/v2/reviews/{review_id}",data={"csrf_token":self.csrf(),"decision":"approved"})
        response=self.client.get("/?q=ＴＥＳＵＴＵ&type=headword&match=contains")
        self.assertEqual(response.status_code,200)
        self.assertIn("てすとぅ".encode(),response.data)

    def test_public_search_ranks_best_match_and_preserves_return_url(self):
        with self.app.app_context():
            from v2app.db import get_db

            db = get_db()
            entry_ids = {}
            for label, headword in (
                ("exact", "zqx"),
                ("prefix", "zqxabc"),
                ("suffix", "abczqx"),
                ("contains", "abczqxdef"),
            ):
                entry_id = db.execute(
                    "INSERT INTO entries(headword,kana,ipa,pos) VALUES(?,?,?,?)",
                    (headword, headword, headword, "名詞"),
                ).lastrowid
                db.execute(
                    "INSERT INTO meanings(entry_id,language,meaning_number,definition) VALUES(?, 'ja', 1, ?)",
                    (entry_id, f"{label} match"),
                )
                db.execute(
                    "INSERT INTO entry_workflow(entry_id,publication_status) VALUES(?,'published')",
                    (entry_id,),
                )
                entry_ids[label] = entry_id
            rebuild_search_index(db)
            db.commit()

            ranked_ids = [
                row["id"]
                for row in search_entries(db, "zqx", "ja", "headword", "contains")
                if row["id"] in entry_ids.values()
            ]

        self.assertEqual(ranked_ids, [
            entry_ids["exact"],
            entry_ids["prefix"],
            entry_ids["suffix"],
            entry_ids["contains"],
        ])

        response = self.client.get("/?language=ja&q=zqx&type=headword&match=contains")
        self.assertEqual(response.status_code, 200)
        result_positions = [
            response.data.index(f"/word/{entry_ids[label]}-".encode())
            for label in ("exact", "prefix", "suffix", "contains")
        ]
        self.assertEqual(result_positions, sorted(result_positions))

        detail = self.client.get(
            f"/word/{entry_ids['exact']}?language=ja&q=zqx&type=headword&match=contains"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertIn(
            b'href="/?language=ja&amp;q=zqx&amp;type=headword&amp;match=contains#results"',
            detail.data,
        )

    def test_hyphenated_stem_matches_inflected_query_after_direct_match(self):
        with self.app.app_context():
            from v2app.db import get_db

            db = get_db()
            entry_ids = []
            for headword, kana, ipa in (
                ("zqstemrun", "直接一致", "[direct]"),
                ("語幹の項目", "ごかんのこうもく", "[zQstem-]"),
            ):
                entry_id = db.execute(
                    "INSERT INTO entries(headword,kana,ipa,pos) VALUES(?,?,?,?)",
                    (headword, kana, ipa, "動詞"),
                ).lastrowid
                db.execute(
                    "INSERT INTO meanings(entry_id,language,meaning_number,definition) VALUES(?, 'ja', 1, '語幹検索テスト')",
                    (entry_id,),
                )
                db.execute(
                    "INSERT INTO entry_workflow(entry_id,publication_status) VALUES(?,'published')",
                    (entry_id,),
                )
                entry_ids.append(entry_id)
            actual_stem_id = db.execute(
                "SELECT id FROM entries WHERE ipa='[uTir-]' ORDER BY id LIMIT 1"
            ).fetchone()["id"]
            db.execute(
                "INSERT OR IGNORE INTO entry_workflow(entry_id,publication_status) VALUES(?,'published')",
                (actual_stem_id,),
            )
            rebuild_search_index(db)
            db.commit()

            ranked_ids = [
                row["id"]
                for row in search_entries(db, "ZQSTEMRUN", "ja", "headword", "contains")
                if row["id"] in entry_ids
            ]
            actual_result_ids = [
                row["id"]
                for row in search_entries(db, "utirun", "ja", "headword", "contains")
            ]

        self.assertEqual(ranked_ids, entry_ids)
        self.assertIn(actual_stem_id, actual_result_ids)

    def test_unpublished_draft_has_no_public_url(self):
        entry_id=self.create_draft()
        self.assertEqual(self.client.get(f"/word/{entry_id}").status_code,404)

    def test_no_change_inspection_completes_without_review(self):
        self.login()
        with sqlite3.connect(self.database) as db:
            db.row_factory=sqlite3.Row
            user_id=db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            entry_id=db.execute("SELECT id FROM entries LIMIT 1").fetchone()[0]
            db.execute("INSERT OR IGNORE INTO entry_workflow(entry_id,publication_status) VALUES(?,'published')",(entry_id,))
            db.execute("INSERT INTO entry_assignments(entry_id,assignee_id,assigned_by) VALUES(?,?,?)",(entry_id,user_id,user_id))
            keys=("headword","reading","ipa","part_of_speech","verb_details","tone","meanings","examples","translations","media","sources","duplicates")
            db.executemany("INSERT OR IGNORE INTO entry_checklists(entry_id,item_key) VALUES(?,?)",((entry_id,key) for key in keys)); db.commit()
        data={"csrf_token":self.csrf(),"action":"complete_no_changes","check_item":list(keys)}
        response=self.client.post(f"/v2/inspect/{entry_id}",data=data)
        self.assertEqual(response.status_code,302)
        with sqlite3.connect(self.database) as db: status=db.execute("SELECT status FROM entry_assignments WHERE entry_id=?",(entry_id,)).fetchone()[0]
        self.assertEqual(status,"completed")
        self.assertEqual(self.client.get("/v2/my-history").status_code, 200)

    def test_completed_inspection_moves_to_next_and_can_be_reopened(self):
        self.login()
        keys=("headword","reading","ipa","part_of_speech","verb_details","tone","meanings","examples","translations","media","sources","duplicates")
        with sqlite3.connect(self.database) as db:
            user_id=db.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
            entries=[row[0] for row in db.execute("SELECT id FROM entries ORDER BY id LIMIT 2")]
            for entry_id in entries:
                db.execute("INSERT OR IGNORE INTO entry_workflow(entry_id,publication_status) VALUES(?,'published')",(entry_id,))
                db.execute("INSERT INTO entry_assignments(entry_id,assignee_id,assigned_by) VALUES(?,?,?)",(entry_id,user_id,user_id))
                db.executemany("INSERT OR IGNORE INTO entry_checklists(entry_id,item_key) VALUES(?,?)",((entry_id,key) for key in keys))
            db.commit()
        response=self.client.post(f"/v2/inspect/{entries[0]}",data={"csrf_token":self.csrf(),"action":"complete_no_changes","check_item":list(keys)})
        self.assertEqual(response.location, f"/v2/inspect/{entries[1]}")
        previous=self.client.get(response.location)
        self.assertIn("直前の点検へ戻る".encode(), previous.data)
        reopened=self.client.post(f"/v2/inspect/{entries[0]}/reopen",data={"csrf_token":self.csrf()})
        self.assertEqual(reopened.location, f"/v2/inspect/{entries[0]}")
        with sqlite3.connect(self.database) as db:
            status=db.execute("SELECT status FROM entry_assignments WHERE entry_id=?",(entries[0],)).fetchone()[0]
        self.assertEqual(status,"in_progress")

    def test_main_pages_render_without_internal_errors(self):
        self.login()
        for path in ("/v2/admin", "/v2/entries", "/v2/tasks", "/v2/sources", "/v2/admin-tools",
                     "/v2/admin-tools/history", "/v2/admin-tools/import", "/v2/admin-tools/quarantine",
                     "/", "/about", "/sw.js"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()
        entry_id = self.create_draft()
        self.assertEqual(self.client.get(f"/v2/entries/{entry_id}/edit").status_code, 200)
        self.assertEqual(self.client.get(f"/v2/sources/entry/{entry_id}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
