import json

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from .auth import login_required, role_required
from .db import get_db
from .media import MediaValidationError, save_media_file
from .security import csrf_token
from .workflow import ALLOWED_POS, apply_snapshot, current_entry_snapshot, load_revision_snapshot, snapshot_from_form
from .allocation import CHECKLIST_LABELS
from .search import rebuild_search_index

bp = Blueprint("editorial", __name__, url_prefix="/v2")
FIELD_LABELS = {"headword":"見出し語","kana":"読み方","ipa":"IPA","pos":"品詞","verb_class":"動詞クラス","verb_stem":"語幹","tone":"音調","etymology":"語源","historical_change":"歴史的音変化","supplemental_note":"補足情報の自由記述","meanings":"意味","examples":"例文","synonyms":"同義語","conjugations":"活用形","source_sections":"別の辞典の記述"}
ACTION_LABELS = {
    "create_draft": "新規語彙の下書きを作成",
    "save_draft": "修正内容を下書き保存",
    "request_review": "相互確認を依頼",
    "inspection_save": "点検を途中保存",
    "inspection_start_edit": "修正ありとして編集を開始",
    "inspection_complete_no_change": "修正なしで点検完了",
    "inspection_reopened": "完了した点検を再開",
    "restore_before_edit": "編集前の状態を下書き復元",
    "cancel_review_request": "相互確認依頼を撤回",
    "direct_publish": "相互確認なしで直接公開",
    "attach_source": "出典情報を追加",
    "edit_source_record": "出典情報を編集",
    "archive_source_record": "出典情報を非表示",
    "restore_source_record": "出典情報を再表示",
    "archive_media": "音声・画像を削除",
    "restore_media": "音声・画像を復元",
    "edit_media_description": "画像の説明を編集",
    "approve_review": "相互確認で承認",
    "returned": "コメント付きで差し戻し",
    "escalated": "完全管理者へ判断を依頼",
}


def audit(db, action, entity_type, entity_id, before=None, after=None):
    db.execute(
        "INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,before_json,after_json) VALUES(?,?,?,?,?,?)",
        (session["user_id"], action, entity_type, entity_id,
         json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None),
    )


def next_assignment_entry_id(db, current_entry_id=None):
    row = db.execute(
        "SELECT a.entry_id FROM entry_assignments a JOIN entry_workflow w ON w.entry_id=a.entry_id "
        "WHERE a.assignee_id=? AND a.status!='completed' AND w.workflow_status IN ('unreviewed','verified') "
        "AND (? IS NULL OR a.entry_id!=?) ORDER BY a.assigned_at,a.id LIMIT 1",
        (session["user_id"], current_entry_id, current_entry_id),
    ).fetchone()
    return row["entry_id"] if row else None


def previous_inspection(db, current_entry_id=None):
    entry_id = session.get("previous_inspection_entry_id")
    if not entry_id or entry_id == current_entry_id:
        return None
    return db.execute(
        "SELECT e.id,e.headword,a.status FROM entry_assignments a JOIN entries e ON e.id=a.entry_id "
        "WHERE a.entry_id=? AND a.assignee_id=? ORDER BY a.id DESC LIMIT 1",
        (entry_id, session["user_id"]),
    ).fetchone()


def meaning_cards(snapshot):
    meanings = snapshot.get("meanings", {}) if snapshot else {}
    count = max((len(meanings.get(language, [])) for language in ("ja", "en", "zh-tw")), default=0)
    return [{language: meanings.get(language, [])[index] if index < len(meanings.get(language, [])) else ""
             for language in ("ja", "en", "zh-tw")} for index in range(count)]


def editor_reference_data(db, snapshot, entry_id=None):
    categories = db.execute("SELECT id,name FROM conjugation_categories WHERE is_active=1 ORDER BY sort_order,name").fetchall()
    sources = db.execute("SELECT id,name,abbreviation,is_active FROM sources ORDER BY is_active DESC,name").fetchall()
    media = db.execute("SELECT * FROM media_files WHERE entry_id=? AND example_id IS NULL ORDER BY created_at DESC", (entry_id,)).fetchall() if entry_id else []
    return {"conjugation_categories": categories, "sources": sources, "meaning_cards": meaning_cards(snapshot),
            "entry_media": media, "source_sections": snapshot.get("source_sections", [])}


def editable_revision(db, entry_id):
    return db.execute(
        "SELECT * FROM entry_revisions WHERE entry_id=? AND author_id=? AND status IN ('draft','returned') ORDER BY id DESC LIMIT 1",
        (entry_id, session["user_id"]),
    ).fetchone()


@bp.get("/entries")
@login_required
def entries():
    db=get_db(); query=request.args.get("q","").strip(); pattern=f"%{query}%"
    rows=db.execute("""SELECT e.id,e.headword,e.kana,e.pos,w.publication_status,w.workflow_status,
      GROUP_CONCAT(DISTINCT u.display_name) assignees FROM entries e JOIN entry_workflow w ON w.entry_id=e.id
      LEFT JOIN entry_assignments a ON a.entry_id=e.id AND a.status!='completed' LEFT JOIN users u ON u.id=a.assignee_id
      WHERE (?='' OR e.headword LIKE ? OR e.kana LIKE ?) GROUP BY e.id ORDER BY e.headword LIMIT 300""",(query,pattern,pattern)).fetchall()
    users=db.execute("SELECT id,display_name FROM users WHERE is_active=1 ORDER BY display_name").fetchall() if session.get("role")=="admin" else []
    return render_template("v2/entries.html",entries=rows,users=users,query=query,csrf_token=csrf_token())


@bp.get("/entries/<int:entry_id>/history")
@login_required
def entry_history(entry_id):
    db=get_db(); entry=db.execute("SELECT id,headword FROM entries WHERE id=?",(entry_id,)).fetchone()
    if not entry: abort(404)
    revisions=db.execute("SELECT r.*,u.display_name FROM entry_revisions r JOIN users u ON u.id=r.author_id WHERE r.entry_id=? ORDER BY r.created_at DESC",(entry_id,)).fetchall()
    audits=db.execute("SELECT a.*,u.display_name FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id WHERE a.entity_type IN ('entry','revision') AND (a.entity_id=? OR a.entity_id IN (SELECT id FROM entry_revisions WHERE entry_id=?)) ORDER BY a.created_at DESC",(entry_id,entry_id)).fetchall()
    return render_template("v2/entry_history.html",entry=entry,revisions=revisions,audits=audits,csrf_token=csrf_token())


@bp.route("/entries/new", methods=("GET", "POST"))
@login_required
def new_entry():
    db = get_db()
    reference = editor_reference_data(db, {})
    allowed_conjugations = {row["name"] for row in reference["conjugation_categories"]}
    if request.method == "POST":
        try:
            snapshot = snapshot_from_form(request.form, allowed_conjugation_names=allowed_conjugations,
                                          allowed_source_ids={row["id"] for row in reference["sources"]})
            if snapshot.get("primary_source_id") and not db.execute("SELECT 1 FROM sources WHERE id=? AND is_active=1", (snapshot["primary_source_id"],)).fetchone():
                raise ValueError("出典辞典を選び直してください。")
        except ValueError as error:
            flash(str(error))
            return redirect(url_for("editorial.new_entry"))
        cursor = db.execute("INSERT INTO entries(headword) VALUES(?)", (snapshot["headword"],))
        entry_id = cursor.lastrowid
        revision = db.execute(
            "INSERT INTO entry_revisions(entry_id,author_id,snapshot_json,change_summary) VALUES(?,?,?,?) RETURNING id",
            (entry_id, session["user_id"], json.dumps(snapshot, ensure_ascii=False), "新規語彙の登録"),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO entry_workflow(entry_id,workflow_status,publication_status,created_by,current_revision_id) VALUES(?, 'draft','unpublished',?,?)",
            (entry_id, session["user_id"], revision),
        )
        audit(db, "create_draft", "entry", entry_id, after=snapshot)
        audio_file = request.files.get("audio_file")
        if audio_file and audio_file.filename:
            try:
                save_media_file(db, entry_id, audio_file, "audio", revision_id=revision, pending=True)
                flash("音声を下書きに追加しました。語彙を公開すると音声も公開されます。")
            except MediaValidationError as error:
                flash(str(error))
        image_file = request.files.get("image_file")
        if image_file and image_file.filename:
            try:
                save_media_file(db, entry_id, image_file, "image", revision_id=revision, pending=True,
                                description=request.form.get("image_description", ""))
                flash("画像を下書きに追加しました。語彙を公開すると画像も公開されます。")
            except MediaValidationError as error:
                flash(str(error))
        db.commit()
        flash("下書きを保存しました。そのまま公開するか、判断に迷う場合だけ相互確認を依頼してください。")
        return redirect(url_for("editorial.edit_entry", entry_id=entry_id))
    return render_template("v2/entry_form.html", entry={}, pos_options=ALLOWED_POS, csrf_token=csrf_token(), **reference)


@bp.route("/entries/<int:entry_id>/edit", methods=("GET", "POST"))
@login_required
def edit_entry(entry_id):
    db = get_db()
    revision = editable_revision(db, entry_id)
    if not revision:
        pending = db.execute(
            "SELECT rr.id,rr.requester_id FROM review_requests rr JOIN entry_revisions r ON r.id=rr.revision_id "
            "WHERE r.entry_id=? AND rr.status='pending' ORDER BY rr.id DESC LIMIT 1", (entry_id,),
        ).fetchone()
        if pending:
            flash("この語彙は相互確認中です。修正する場合は、先に確認依頼を撤回してください。")
            if pending["requester_id"] == session["user_id"]:
                return redirect(url_for("editorial.request_status", review_id=pending["id"]))
            return redirect(url_for("editorial.entry_history", entry_id=entry_id))
        assignment = db.execute("SELECT 1 FROM entry_assignments WHERE entry_id=? AND assignee_id=? AND status!='completed'", (entry_id, session["user_id"])).fetchone()
        workflow = db.execute("SELECT workflow_status FROM entry_workflow WHERE entry_id=?", (entry_id,)).fetchone()
        if session.get("role") != "admin" and (not assignment or not workflow or workflow["workflow_status"] not in ("unreviewed", "verified")):
            abort(403)
        snapshot = current_entry_snapshot(db, entry_id)
        revision_id = db.execute(
            "INSERT INTO entry_revisions(entry_id,author_id,snapshot_json,change_summary) VALUES(?,?,?,?) RETURNING id",
            (entry_id, session["user_id"], json.dumps(snapshot, ensure_ascii=False), "既存語彙の点検"),
        ).fetchone()[0]
        db.execute("UPDATE entry_workflow SET workflow_status='draft',current_revision_id=? WHERE entry_id=?", (revision_id, entry_id))
        db.commit()
        revision = db.execute("SELECT * FROM entry_revisions WHERE id=?", (revision_id,)).fetchone()
    if request.method == "POST":
        before = load_revision_snapshot(revision)
        reference = editor_reference_data(db, before, entry_id)
        allowed_conjugations = {row["name"] for row in reference["conjugation_categories"]}
        try:
            snapshot = snapshot_from_form(request.form, before, allowed_conjugations,
                                          {row["id"] for row in reference["sources"]})
            if snapshot.get("primary_source_id") and not db.execute("SELECT 1 FROM sources WHERE id=? AND is_active=1", (snapshot["primary_source_id"],)).fetchone():
                raise ValueError("出典辞典を選び直してください。")
        except ValueError as error:
            flash(str(error))
            return redirect(url_for("editorial.edit_entry", entry_id=entry_id))
        db.execute(
            "UPDATE entry_revisions SET snapshot_json=?,change_summary=?,status='draft',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(snapshot, ensure_ascii=False), request.form.get("change_summary", "").strip(), revision["id"]),
        )
        db.execute("UPDATE entry_workflow SET workflow_status='draft',current_revision_id=? WHERE entry_id=?", (revision["id"], entry_id))
        audit(db, "save_draft", "revision", revision["id"], before=before, after=snapshot)
        audio_file = request.files.get("audio_file")
        if audio_file and audio_file.filename:
            try:
                save_media_file(db, entry_id, audio_file, "audio", revision_id=revision["id"], pending=True)
                flash("音声を下書きに追加しました。語彙を公開すると音声も公開されます。")
            except MediaValidationError as error:
                flash(str(error))
        image_file = request.files.get("image_file")
        if image_file and image_file.filename:
            try:
                save_media_file(db, entry_id, image_file, "image", revision_id=revision["id"], pending=True,
                                description=request.form.get("image_description", ""))
                flash("画像を下書きに追加しました。語彙を公開すると画像も公開されます。")
            except MediaValidationError as error:
                flash(str(error))
        db.commit()
        flash("下書きを保存しました。そのまま公開できます。")
        return redirect(url_for("editorial.edit_entry", entry_id=entry_id))
    snapshot = load_revision_snapshot(revision)
    reviewers = db.execute("SELECT id,display_name FROM users WHERE is_active=1 AND id!=? ORDER BY display_name", (session["user_id"],)).fetchall()
    return_comments = db.execute(
        "SELECT c.body,c.created_at,u.display_name FROM review_comments c "
        "JOIN review_requests rr ON rr.id=c.review_request_id JOIN users u ON u.id=c.author_id "
        "WHERE rr.revision_id=? ORDER BY c.created_at DESC", (revision["id"],),
    ).fetchall()
    reference = editor_reference_data(db, snapshot, entry_id)
    return render_template("v2/entry_form.html", entry=snapshot, revision=revision, reviewers=reviewers,
                           return_comments=return_comments, pos_options=ALLOWED_POS, csrf_token=csrf_token(), **reference)


@bp.post("/conjugation-categories")
@role_required("admin")
def add_conjugation_category():
    db = get_db()
    name = request.form.get("name", "").strip()
    entry_id = request.form.get("entry_id", type=int)
    if not name or len(name) > 40:
        flash("活用形の選択肢は1〜40文字で入力してください。")
    else:
        db.execute("INSERT INTO conjugation_categories(name,sort_order,is_active) VALUES(?,500,1) "
                   "ON CONFLICT(name) DO UPDATE SET is_active=1", (name,))
        db.commit()
        flash(f"活用形の選択肢「{name}」を追加しました。")
    return redirect(url_for("editorial.edit_entry", entry_id=entry_id) if entry_id else url_for("editorial.new_entry"))


@bp.post("/entries/<int:entry_id>/publish-direct")
@login_required
def publish_direct(entry_id):
    db = get_db()
    revision = editable_revision(db, entry_id)
    if not revision:
        abort(403)
    before = current_entry_snapshot(db, entry_id)
    reference = editor_reference_data(db, before or {}, entry_id)
    allowed_conjugations = {row["name"] for row in reference["conjugation_categories"]}
    try:
        snapshot = snapshot_from_form(request.form, load_revision_snapshot(revision), allowed_conjugations,
                                      {row["id"] for row in reference["sources"]})
        if snapshot.get("primary_source_id") and not db.execute("SELECT 1 FROM sources WHERE id=? AND is_active=1", (snapshot["primary_source_id"],)).fetchone():
            raise ValueError("出典辞典を選び直してください。")
    except ValueError as error:
        flash(str(error))
        return redirect(url_for("editorial.edit_entry", entry_id=entry_id))
    db.execute("UPDATE entry_revisions SET snapshot_json=?,change_summary=?,status='approved',updated_at=CURRENT_TIMESTAMP WHERE id=?",
               (json.dumps(snapshot, ensure_ascii=False), request.form.get("change_summary", "").strip(), revision["id"]))
    audio_file = request.files.get("audio_file")
    if audio_file and audio_file.filename:
        try:
            save_media_file(db, entry_id, audio_file, "audio", revision_id=revision["id"], pending=False)
        except MediaValidationError as error:
            flash(str(error))
            db.rollback()
            return redirect(url_for("editorial.edit_entry", entry_id=entry_id))
    image_file = request.files.get("image_file")
    if image_file and image_file.filename:
        try:
            save_media_file(db, entry_id, image_file, "image", revision_id=revision["id"], pending=False,
                            description=request.form.get("image_description", ""))
        except MediaValidationError as error:
            flash(str(error))
            db.rollback()
            return redirect(url_for("editorial.edit_entry", entry_id=entry_id))
    apply_snapshot(db, entry_id, snapshot)
    db.execute("UPDATE media_files SET is_pending=0 WHERE revision_id=?", (revision["id"],))
    db.execute("UPDATE entry_workflow SET workflow_status='verified',publication_status='published',current_revision_id=?,published_at=CURRENT_TIMESTAMP WHERE entry_id=?",
               (revision["id"], entry_id))
    db.execute("UPDATE entry_assignments SET status='completed',completed_at=CURRENT_TIMESTAMP WHERE entry_id=? AND assignee_id=? AND status!='completed'",
               (entry_id, session["user_id"]))
    rebuild_search_index(db, entry_id)
    audit(db, "direct_publish", "revision", revision["id"], before=before, after=snapshot)
    db.commit()
    flash("保存した内容をそのまま公開しました。必要になれば履歴から再編集できます。")
    return redirect(url_for("public.entry", entry_id=entry_id, slug=snapshot["headword"]))


@bp.post("/entries/<int:entry_id>/request-review")
@login_required
def request_review(entry_id):
    db = get_db()
    revision = editable_revision(db, entry_id)
    reviewer_id = request.form.get("reviewer_id", type=int)
    reviewer = db.execute("SELECT id FROM users WHERE id=? AND is_active=1", (reviewer_id,)).fetchone()
    if not revision or not reviewer or reviewer_id == session["user_id"]:
        flash("別の有効な担当者を選んでください。")
        return redirect(url_for("editorial.edit_entry", entry_id=entry_id))
    db.execute("UPDATE entry_revisions SET status='review_requested',updated_at=CURRENT_TIMESTAMP WHERE id=?", (revision["id"],))
    review_id = db.execute(
        "INSERT INTO review_requests(revision_id,requester_id,reviewer_id) VALUES(?,?,?) RETURNING id",
        (revision["id"], session["user_id"], reviewer_id),
    ).fetchone()[0]
    db.execute("UPDATE entry_workflow SET workflow_status='review_requested' WHERE entry_id=?", (entry_id,))
    audit(db, "request_review", "review", review_id)
    db.commit()
    session["previous_inspection_entry_id"] = entry_id
    next_entry_id = next_assignment_entry_id(db, entry_id)
    flash("確認を依頼しました。次の担当語彙へ進みます。" if next_entry_id else "確認を依頼しました。現在の要確認項目は以上です。")
    return redirect(url_for("editorial.inspect_entry", entry_id=next_entry_id) if next_entry_id else url_for("editorial.tasks"))


@bp.get("/tasks")
@login_required
def tasks():
    db = get_db()
    assignments = db.execute(
        "SELECT a.*,e.headword FROM entry_assignments a JOIN entries e ON e.id=a.entry_id JOIN entry_workflow w ON w.entry_id=a.entry_id "
        "WHERE a.assignee_id=? AND a.status!='completed' AND w.workflow_status IN ('unreviewed','verified') ORDER BY a.assigned_at",
        (session["user_id"],),
    ).fetchall()
    drafts = db.execute(
        "SELECT DISTINCT e.id entry_id,e.headword,r.updated_at FROM entry_revisions r JOIN entries e ON e.id=r.entry_id "
        "JOIN entry_assignments a ON a.entry_id=e.id AND a.assignee_id=r.author_id AND a.status!='completed' "
        "WHERE r.author_id=? AND r.status='draft' ORDER BY r.updated_at DESC",
        (session["user_id"],),
    ).fetchall()
    reviews = db.execute(
        "SELECT rr.id review_id,rr.requested_at,e.id entry_id,e.headword,u.display_name requester_name "
        "FROM review_requests rr JOIN entry_revisions r ON r.id=rr.revision_id JOIN entries e ON e.id=r.entry_id "
        "JOIN users u ON u.id=rr.requester_id WHERE rr.reviewer_id=? AND rr.status='pending' ORDER BY rr.requested_at",
        (session["user_id"],),
    ).fetchall()
    returned = db.execute(
        "SELECT r.id revision_id,e.id entry_id,e.headword FROM entry_revisions r JOIN entries e ON e.id=r.entry_id "
        "WHERE r.author_id=? AND r.status='returned' ORDER BY r.updated_at DESC",
        (session["user_id"],),
    ).fetchall()
    return render_template("v2/tasks.html", assignments=assignments, drafts=drafts, reviews=reviews, returned=returned,
                           previous_entry=previous_inspection(db), csrf_token=csrf_token())


@bp.get("/my-history")
@login_required
def my_history():
    db = get_db()
    rows = db.execute(
        "SELECT a.*,datetime(a.created_at,'+9 hours') local_created_at,e.id entry_id,e.headword FROM audit_logs a "
        "LEFT JOIN entry_revisions r ON a.entity_type='revision' AND r.id=a.entity_id "
        "LEFT JOIN review_requests rr ON a.entity_type='review' AND rr.id=a.entity_id "
        "LEFT JOIN entry_revisions review_revision ON review_revision.id=rr.revision_id "
        "LEFT JOIN entries e ON e.id=CASE WHEN a.entity_type='entry' THEN a.entity_id "
        "WHEN a.entity_type='revision' THEN r.entry_id WHEN a.entity_type='review' THEN review_revision.entry_id END "
        "WHERE a.actor_id=? ORDER BY a.created_at DESC,a.id DESC LIMIT 500",
        (session["user_id"],),
    ).fetchall()
    editable_ids = set()
    if session.get("role") == "admin":
        editable_ids = {row["entry_id"] for row in rows if row["entry_id"]}
    else:
        editable_ids = {row[0] for row in db.execute(
            "SELECT entry_id FROM entry_assignments WHERE assignee_id=? AND status!='completed' "
            "UNION SELECT entry_id FROM entry_revisions WHERE author_id=? AND status IN ('draft','returned')",
            (session["user_id"], session["user_id"]),
        )}
    pending_entry_ids = {row[0] for row in db.execute(
        "SELECT DISTINCT r.entry_id FROM review_requests rr JOIN entry_revisions r ON r.id=rr.revision_id WHERE rr.status='pending'"
    )}
    history = []
    for row in rows:
        detail = ""
        try:
            data = json.loads(row["after_json"]) if row["after_json"] else {}
            if data.get("comment"):
                detail = data["comment"]
            elif data.get("checked_count") is not None:
                detail = f"{data['checked_count']}項目を確認済み"
        except (TypeError, ValueError, AttributeError):
            pass
        history.append({**dict(row), "action_label": ACTION_LABELS.get(row["action"], row["action"]),
                        "detail": detail, "can_edit": row["entry_id"] in editable_ids and row["entry_id"] not in pending_entry_ids,
                        "can_restore": row["action"] == "save_draft" and bool(row["before_json"])})
    requests = db.execute(
        "SELECT rr.id,rr.status,datetime(rr.requested_at,'+9 hours') local_requested_at,"
        "datetime(rr.resolved_at,'+9 hours') local_resolved_at,r.entry_id,r.change_summary,e.headword,"
        "u.display_name reviewer_name FROM review_requests rr JOIN entry_revisions r ON r.id=rr.revision_id "
        "JOIN entries e ON e.id=r.entry_id JOIN users u ON u.id=rr.reviewer_id "
        "WHERE rr.requester_id=? ORDER BY rr.requested_at DESC,rr.id DESC LIMIT 100",
        (session["user_id"],),
    ).fetchall()
    request_status_labels = {"pending":"確認待ち","approved":"承認済み","returned":"差し戻し", "escalated":"管理者判断へ送付","cancelled":"撤回済み"}
    return render_template("v2/my_history.html", history=history, requests=requests,
                           request_status_labels=request_status_labels, csrf_token=csrf_token())


@bp.post("/my-history/<int:audit_id>/restore")
@login_required
def restore_history(audit_id):
    db = get_db()
    row = db.execute(
        "SELECT a.*,r.entry_id FROM audit_logs a JOIN entry_revisions r ON a.entity_type='revision' AND r.id=a.entity_id "
        "WHERE a.id=? AND a.actor_id=? AND a.action='save_draft'", (audit_id, session["user_id"]),
    ).fetchone()
    if not row or not row["before_json"]:
        abort(404)
    pending = db.execute(
        "SELECT 1 FROM review_requests rr JOIN entry_revisions r ON r.id=rr.revision_id "
        "WHERE r.entry_id=? AND rr.status='pending'", (row["entry_id"],),
    ).fetchone()
    if pending:
        flash("相互確認中のため復元できません。先に確認依頼を撤回してください。")
        return redirect(url_for("editorial.my_history"))
    try:
        snapshot = json.loads(row["before_json"])
        if not isinstance(snapshot, dict) or not snapshot.get("headword"):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError):
        flash("この履歴からは編集前の内容を復元できませんでした。")
        return redirect(url_for("editorial.my_history"))
    revision = editable_revision(db, row["entry_id"])
    current = load_revision_snapshot(revision) if revision else current_entry_snapshot(db, row["entry_id"])
    if revision:
        revision_id = revision["id"]
        db.execute("UPDATE entry_revisions SET snapshot_json=?,change_summary='履歴から編集前の状態を復元',status='draft',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                   (json.dumps(snapshot, ensure_ascii=False), revision_id))
    else:
        revision_id = db.execute(
            "INSERT INTO entry_revisions(entry_id,author_id,snapshot_json,change_summary,status) VALUES(?,?,?,'履歴から編集前の状態を復元','draft') RETURNING id",
            (row["entry_id"], session["user_id"], json.dumps(snapshot, ensure_ascii=False)),
        ).fetchone()[0]
    db.execute("UPDATE entry_workflow SET workflow_status='draft',current_revision_id=? WHERE entry_id=?", (revision_id, row["entry_id"]))
    audit(db, "restore_before_edit", "revision", revision_id, before=current, after=snapshot)
    db.commit()
    flash("編集前の内容を下書きとして復元しました。内容を確認してから保存・確認依頼してください。")
    return redirect(url_for("editorial.edit_entry", entry_id=row["entry_id"]))


@bp.get("/requests/<int:review_id>")
@login_required
def request_status(review_id):
    db = get_db()
    row = db.execute(
        "SELECT rr.*,datetime(rr.requested_at,'+9 hours') local_requested_at,"
        "datetime(rr.resolved_at,'+9 hours') local_resolved_at,r.entry_id,r.snapshot_json,r.change_summary,"
        "e.headword,u.display_name reviewer_name FROM review_requests rr JOIN entry_revisions r ON r.id=rr.revision_id "
        "JOIN entries e ON e.id=r.entry_id JOIN users u ON u.id=rr.reviewer_id WHERE rr.id=? AND rr.requester_id=?",
        (review_id, session["user_id"]),
    ).fetchone()
    if not row:
        abort(404)
    comments = db.execute(
        "SELECT c.body,datetime(c.created_at,'+9 hours') local_created_at,u.display_name FROM review_comments c "
        "JOIN users u ON u.id=c.author_id WHERE c.review_request_id=? ORDER BY c.created_at", (review_id,),
    ).fetchall()
    labels = {"pending":"確認待ち","approved":"承認済み","returned":"差し戻し", "escalated":"管理者判断へ送付","cancelled":"撤回済み"}
    media = db.execute("SELECT * FROM media_files WHERE entry_id=? AND example_id IS NULL AND (revision_id=? OR COALESCE(is_pending,0)=0) AND COALESCE(is_archived,0)=0 ORDER BY created_at DESC",
                       (row["entry_id"], row["revision_id"])).fetchall()
    return render_template("v2/request_status.html", review=row, entry=load_revision_snapshot(row),
                           comments=comments, media=media, status_label=labels.get(row["status"], row["status"]), csrf_token=csrf_token())


@bp.post("/requests/<int:review_id>/withdraw")
@login_required
def withdraw_request(review_id):
    db = get_db()
    row = db.execute(
        "SELECT rr.*,r.entry_id FROM review_requests rr JOIN entry_revisions r ON r.id=rr.revision_id "
        "WHERE rr.id=? AND rr.requester_id=? AND rr.status='pending'", (review_id, session["user_id"]),
    ).fetchone()
    if not row:
        abort(404)
    db.execute("UPDATE review_requests SET status='cancelled',resolved_at=CURRENT_TIMESTAMP WHERE id=?", (review_id,))
    db.execute("UPDATE entry_revisions SET status='draft',updated_at=CURRENT_TIMESTAMP WHERE id=?", (row["revision_id"],))
    db.execute("UPDATE entry_workflow SET workflow_status='draft',current_revision_id=? WHERE entry_id=?", (row["revision_id"], row["entry_id"]))
    audit(db, "cancel_review_request", "review", review_id)
    db.commit()
    flash("相互確認依頼を撤回しました。語彙は再編集できる下書きに戻りました。")
    return redirect(url_for("editorial.edit_entry", entry_id=row["entry_id"]))


@bp.route("/inspect/<int:entry_id>", methods=("GET", "POST"))
@login_required
def inspect_entry(entry_id):
    db = get_db()
    assignment = db.execute(
        "SELECT a.*,e.headword FROM entry_assignments a JOIN entries e ON e.id=a.entry_id "
        "WHERE a.entry_id=? AND a.assignee_id=? ORDER BY (a.status='completed'),a.id DESC LIMIT 1", (entry_id, session["user_id"]),
    ).fetchone()
    if not assignment:
        abort(403)
    if request.method == "POST":
        if assignment["status"] == "completed":
            abort(400)
        checked = set(request.form.getlist("check_item")) & set(CHECKLIST_LABELS)
        for key in CHECKLIST_LABELS:
            db.execute(
                "UPDATE entry_checklists SET checked_by=?,checked_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,note=? WHERE entry_id=? AND item_key=?",
                (session["user_id"] if key in checked else None, int(key in checked), request.form.get(f"note_{key}", "").strip(), entry_id, key),
            )
        action = request.form.get("action")
        if action == "complete_no_changes":
            if checked != set(CHECKLIST_LABELS):
                db.rollback(); flash("完了にする前に、すべての点検項目を確認してください。")
            else:
                db.execute("UPDATE entry_assignments SET status='completed',completed_at=CURRENT_TIMESTAMP WHERE id=?", (assignment["id"],))
                db.execute("UPDATE entry_workflow SET workflow_status='verified' WHERE entry_id=?", (entry_id,))
                audit(db, "inspection_complete_no_change", "entry", entry_id)
                db.commit()
                session["previous_inspection_entry_id"] = entry_id
                next_entry_id = next_assignment_entry_id(db, entry_id)
                flash("修正なしで点検を完了しました。次の担当語彙へ進みます。" if next_entry_id else "修正なしで点検を完了しました。現在の要確認項目は以上です。")
                return redirect(url_for("editorial.inspect_entry", entry_id=next_entry_id) if next_entry_id else url_for("editorial.tasks"))
        else:
            db.execute("UPDATE entry_assignments SET status='in_progress' WHERE id=?", (assignment["id"],))
            audit(db, "inspection_start_edit" if action == "edit" else "inspection_save", "entry", entry_id,
                  after={"checked_count": len(checked)})
            db.commit()
            if action == "edit":
                return redirect(url_for("editorial.edit_entry", entry_id=entry_id))
            flash("点検状況を保存しました。")
        return redirect(url_for("editorial.inspect_entry", entry_id=entry_id))
    entry = current_entry_snapshot(db, entry_id)
    checklist = {row["item_key"]: row for row in db.execute("SELECT * FROM entry_checklists WHERE entry_id=?", (entry_id,))}
    duplicate_candidates = db.execute("SELECT DISTINCT e.id,e.headword,e.kana FROM entry_search_index s JOIN entry_search_index mine ON mine.entry_id=? JOIN entries e ON e.id=s.entry_id WHERE s.entry_id!=? AND (s.normalized_headword=mine.normalized_headword OR (s.normalized_kana!='' AND s.normalized_kana=mine.normalized_kana)) LIMIT 20", (entry_id,entry_id)).fetchall()
    translation_count = db.execute("SELECT COUNT(*) FROM example_translations et JOIN examples ex ON ex.id=et.example_id WHERE ex.entry_id=?", (entry_id,)).fetchone()[0]
    media_count = db.execute("SELECT COUNT(*) FROM media_files mf LEFT JOIN examples ex ON ex.id=mf.example_id WHERE COALESCE(mf.entry_id,ex.entry_id)=? AND COALESCE(mf.is_archived,0)=0", (entry_id,)).fetchone()[0]
    source_names = [row[0] for row in db.execute("SELECT s.name FROM entry_source_records r JOIN sources s ON s.id=r.source_id WHERE r.entry_id=? AND COALESCE(r.is_archived,0)=0", (entry_id,))]
    example_sentences = [item["yonaguni"] for item in entry.get("examples", [])]
    current_values = {
        "headword": entry.get("headword") or "未入力",
        "reading": entry.get("kana") or "未入力",
        "ipa": entry.get("ipa") or "未入力",
        "part_of_speech": entry.get("pos") or "未確認",
        "verb_details": " / ".join(filter(None, (entry.get("verb_class"), entry.get("verb_stem")))) or "該当なし・未入力",
        "tone": entry.get("tone") or "未入力",
        "meanings": " / ".join(entry.get("meanings", {}).get("ja", [])) or "未入力",
        "examples": f"{len(example_sentences)}件" + (f"：{' / '.join(example_sentences[:3])}" if example_sentences else ""),
        "translations": f"{translation_count}件",
        "media": f"{media_count}件",
        "sources": " / ".join(source_names) or "未登録",
        "duplicates": f"{len(duplicate_candidates)}件の候補" if duplicate_candidates else "候補なし",
    }
    return render_template("v2/inspect.html", assignment=assignment, entry=entry, checklist=checklist,
                           labels=CHECKLIST_LABELS, current_values=current_values,
                           duplicate_candidates=duplicate_candidates, previous_entry=previous_inspection(db, entry_id),
                           csrf_token=csrf_token())


@bp.post("/inspect/<int:entry_id>/reopen")
@login_required
def reopen_inspection(entry_id):
    db = get_db()
    assignment = db.execute(
        "SELECT * FROM entry_assignments WHERE entry_id=? AND assignee_id=? AND status='completed' ORDER BY id DESC LIMIT 1",
        (entry_id, session["user_id"]),
    ).fetchone()
    if not assignment:
        abort(403)
    db.execute("UPDATE entry_assignments SET status='in_progress',completed_at=NULL WHERE id=?", (assignment["id"],))
    db.execute("UPDATE entry_workflow SET workflow_status='unreviewed' WHERE entry_id=?", (entry_id,))
    audit(db, "inspection_reopened", "entry", entry_id)
    db.commit()
    flash("直前の点検を再開しました。内容を確認し直せます。")
    return redirect(url_for("editorial.inspect_entry", entry_id=entry_id))


@bp.route("/reviews/<int:review_id>", methods=("GET", "POST"))
@login_required
def review(review_id):
    db = get_db()
    row = db.execute(
        "SELECT rr.*,r.entry_id,r.author_id,r.snapshot_json,r.change_summary,e.headword,u.display_name author_name "
        "FROM review_requests rr JOIN entry_revisions r ON r.id=rr.revision_id JOIN entries e ON e.id=r.entry_id "
        "JOIN users u ON u.id=r.author_id WHERE rr.id=?", (review_id,),
    ).fetchone()
    if not row or row["reviewer_id"] != session["user_id"] or row["status"] != "pending":
        abort(403)
    if row["author_id"] == session["user_id"]:
        abort(403)
    snapshot = load_revision_snapshot(row)
    baseline = current_entry_snapshot(db, row["entry_id"]) or {}
    diffs = [(FIELD_LABELS.get(key,key), baseline.get(key), snapshot.get(key)) for key in FIELD_LABELS if baseline.get(key) != snapshot.get(key)]
    source = db.execute("SELECT * FROM sources WHERE id=?", (snapshot.get("primary_source_id"),)).fetchone() if snapshot.get("primary_source_id") else None
    source_names = {item["id"]: item["name"] for item in db.execute("SELECT id,name FROM sources")}
    media = db.execute("SELECT * FROM media_files WHERE entry_id=? AND example_id IS NULL AND (revision_id=? OR COALESCE(is_pending,0)=0) AND COALESCE(is_archived,0)=0 ORDER BY created_at DESC",
                       (row["entry_id"], row["revision_id"])).fetchall()
    if request.method == "POST":
        decision = request.form.get("decision")
        comment = request.form.get("comment", "").strip()
        if decision in ("returned", "escalated") and not comment:
            flash("差し戻し・管理者判断にはコメントを入力してください。")
            return render_template("v2/review.html", review=row, entry=snapshot, diffs=diffs, source=source, source_names=source_names, media=media, csrf_token=csrf_token()), 400
        if decision == "approved":
            media_count = apply_snapshot(db, row["entry_id"], snapshot)
            db.execute("UPDATE media_files SET is_pending=0 WHERE revision_id=?", (row["revision_id"],))
            db.execute("UPDATE review_requests SET status='approved',resolved_at=CURRENT_TIMESTAMP WHERE id=?", (review_id,))
            db.execute("UPDATE entry_revisions SET status='approved',updated_at=CURRENT_TIMESTAMP WHERE id=?", (row["revision_id"],))
            db.execute("UPDATE entry_workflow SET workflow_status='verified',publication_status='published',published_at=CURRENT_TIMESTAMP WHERE entry_id=?", (row["entry_id"],))
            rebuild_search_index(db, row["entry_id"])
            db.execute("UPDATE entry_assignments SET status='completed',completed_at=CURRENT_TIMESTAMP WHERE entry_id=? AND assignee_id=? AND status!='completed'", (row["entry_id"], row["author_id"]))
            action = "approve_review"
            if media_count:
                comment = (comment + "\n" if comment else "") + "既存音声を保護するため例文の置換は保留されました。"
        elif decision in ("returned", "escalated"):
            admin = None
            if decision == "escalated":
                admin = db.execute(
                    "SELECT id FROM users WHERE role='admin' AND is_active=1 AND id NOT IN (?,?) ORDER BY id LIMIT 1",
                    (row["author_id"], session["user_id"]),
                ).fetchone()
                if not admin:
                    flash("判断を引き継げる別の完全管理者が登録されていません。")
                    return render_template("v2/review.html", review=row, entry=snapshot, diffs=diffs, source=source, source_names=source_names, media=media, csrf_token=csrf_token()), 400
            revision_status = "returned" if decision == "returned" else "admin_review"
            db.execute("UPDATE review_requests SET status=?,resolved_at=CURRENT_TIMESTAMP WHERE id=?", (decision, review_id))
            db.execute("UPDATE entry_revisions SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (revision_status, row["revision_id"]))
            db.execute("UPDATE entry_workflow SET workflow_status=? WHERE entry_id=?", (revision_status, row["entry_id"]))
            if admin:
                db.execute(
                    "INSERT INTO review_requests(revision_id,requester_id,reviewer_id,status) VALUES(?,?,?,'pending')",
                    (row["revision_id"], session["user_id"], admin["id"]),
                )
            action = decision
        else:
            abort(400)
        if comment:
            db.execute("INSERT INTO review_comments(review_request_id,author_id,body) VALUES(?,?,?)", (review_id, session["user_id"], comment))
        audit(db, action, "review", review_id, after={"comment": comment})
        db.commit()
        flash("確認結果を保存しました。")
        return redirect(url_for("editorial.tasks"))
    return render_template("v2/review.html", review=row, entry=snapshot, diffs=diffs, source=source, source_names=source_names, media=media, csrf_token=csrf_token())
