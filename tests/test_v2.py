import sqlite3
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash
from werkzeug.datastructures import MultiDict

from v2app import create_app
from scripts.upgrade_v2 import apply_upgrades
from v2app.search import normalize, rebuild_search_index, search_entries
from v2app.workflow import snapshot_from_form

ROOT = Path(__file__).resolve().parent.parent


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
            for headword in ("zqstemrun", "zQstem-"):
                entry_id = db.execute(
                    "INSERT INTO entries(headword,kana,ipa,pos) VALUES(?,?,?,?)",
                    (headword, headword, headword, "動詞"),
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
            rebuild_search_index(db)
            db.commit()

            ranked_ids = [
                row["id"]
                for row in search_entries(db, "ZQSTEMRUN", "ja", "headword", "contains")
                if row["id"] in entry_ids
            ]

        self.assertEqual(ranked_ids, entry_ids)

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
                     "/v2/admin-tools/history", "/v2/admin-tools/import", "/v2/admin-tools/quarantine", "/", "/sw.js"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()
        entry_id = self.create_draft()
        self.assertEqual(self.client.get(f"/v2/entries/{entry_id}/edit").status_code, 200)
        self.assertEqual(self.client.get(f"/v2/sources/entry/{entry_id}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
