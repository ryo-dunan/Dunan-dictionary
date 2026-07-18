import json
import secrets
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .allocation import distribute_assignments
from .auth import role_required
from .database_update import (
    DatabaseUpdateError,
    create_backup,
    inspect_database,
    pending_path,
    replace_database,
    save_pending_upload,
)
from .db import close_db, get_db
from .security import csrf_token
from .workflow import ALLOWED_POS
from .search import rebuild_search_index

bp = Blueprint("admin_v2", __name__, url_prefix="/v2/admin-tools")


@bp.get("")
@role_required("admin")
def index():
    db = get_db()
    users = db.execute("SELECT id,username,display_name,role,is_active,created_at FROM users ORDER BY id").fetchall()
    progress = db.execute("SELECT u.display_name,COUNT(a.id) total,SUM(a.status='completed') completed,ROUND(SUM(CASE WHEN a.status!='completed' THEN a.workload_score ELSE 0 END),1) remaining FROM users u LEFT JOIN entry_assignments a ON a.assignee_id=u.id GROUP BY u.id").fetchall()
    quarantine = db.execute("SELECT COUNT(*) FROM quarantine_records WHERE restored_at IS NULL").fetchone()[0]
    return render_template("v2/admin_tools.html", users=users, progress=progress, quarantine=quarantine, csrf_token=csrf_token())


@bp.post("/users")
@role_required("admin")
def create_user():
    db = get_db()
    username = request.form.get("username", "").strip()
    display_name = request.form.get("display_name", "").strip()
    role = request.form.get("role", "editor")
    password = request.form.get("password", "")
    if not username or not display_name or role not in ("admin", "editor") or len(password) < 12:
        flash("名前・ユーザー名と、12文字以上の初期パスワードを入力してください。")
    else:
        try:
            db.execute("INSERT INTO users(username,display_name,password_hash,role,must_change_password) VALUES(?,?,?,?,1)",
                       (username, display_name, generate_password_hash(password), role))
            db.commit(); flash(f"{display_name}さんのアカウントを作成しました。")
        except Exception:
            db.rollback(); flash("そのユーザー名は使用済みです。")
    return redirect(url_for("admin_v2.index"))


@bp.post("/users/<int:user_id>/toggle")
@role_required("admin")
def toggle_user(user_id):
    if user_id == session["user_id"]:
        flash("自分自身のアカウントは停止できません。")
    else:
        db = get_db(); db.execute("UPDATE users SET is_active=1-is_active,updated_at=CURRENT_TIMESTAMP WHERE id=?", (user_id,)); db.commit()
        flash("アカウントの利用状態を変更しました。")
    return redirect(url_for("admin_v2.index"))


@bp.post("/users/<int:user_id>/reset-password")
@role_required("admin")
def reset_password(user_id):
    password=request.form.get("password","")
    if len(password)<12:
        flash("初期パスワードは12文字以上にしてください。")
    else:
        db=get_db(); db.execute("UPDATE users SET password_hash=?,must_change_password=1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(generate_password_hash(password),user_id)); db.commit(); flash("初期パスワードを設定しました。本人は次回ログイン時に変更します。")
    return redirect(url_for("admin_v2.index"))


@bp.post("/users/<int:user_id>/role")
@role_required("admin")
def change_role(user_id):
    role=request.form.get("role")
    if role not in ("admin","editor") or user_id==session["user_id"]:
        flash("自分自身以外の有効な権限を選んでください。")
    else:
        db=get_db(); db.execute("UPDATE users SET role=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(role,user_id)); db.commit(); flash("権限を変更しました。")
    return redirect(url_for("admin_v2.index"))


@bp.post("/assign/<int:entry_id>")
@role_required("admin")
def manual_assign(entry_id):
    db=get_db(); assignee_id=request.form.get("assignee_id",type=int)
    if not db.execute("SELECT 1 FROM users WHERE id=? AND is_active=1",(assignee_id,)).fetchone():
        flash("有効な担当者を選んでください。")
    else:
        old=[dict(row) for row in db.execute("SELECT * FROM entry_assignments WHERE entry_id=? AND status!='completed'",(entry_id,))]
        db.execute("DELETE FROM entry_assignments WHERE entry_id=? AND status!='completed'",(entry_id,))
        db.execute("INSERT INTO entry_assignments(entry_id,assignee_id,assigned_by,workload_score) VALUES(?,?,?,COALESCE((SELECT workload_score FROM entry_assignments WHERE entry_id=? ORDER BY id DESC LIMIT 1),1))",(entry_id,assignee_id,session["user_id"],entry_id))
        db.execute("INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,before_json,after_json) VALUES(?,'manual_assign','entry',?,?,?)",(session["user_id"],entry_id,json.dumps(old,ensure_ascii=False),json.dumps({"assignee_id":assignee_id})))
        db.commit(); flash("担当者を変更しました。")
    return redirect(url_for("editorial.entries",q=request.form.get("q","")))


@bp.post("/assign")
@role_required("admin")
def auto_assign():
    db = get_db()
    try:
        created, loads = distribute_assignments(db, session["user_id"])
        db.execute("INSERT INTO audit_logs(actor_id,action,entity_type,after_json) VALUES(?, 'auto_assign','assignments',?)",
                   (session["user_id"], json.dumps(loads)))
        db.commit(); flash(f"作業量を計算し、{created}語を均等に割り当てました。")
    except ValueError as error:
        flash(str(error))
    return redirect(url_for("admin_v2.index"))


@bp.post("/entries/<int:entry_id>/<action>")
@role_required("admin")
def publication(entry_id, action):
    statuses = {"publish": "published", "unpublish": "unpublished", "archive": "archived", "restore": "unpublished"}
    if action not in statuses:
        return ("", 404)
    db = get_db(); status = statuses[action]
    db.execute("UPDATE entry_workflow SET publication_status=?,archived_at=CASE WHEN ?='archived' THEN CURRENT_TIMESTAMP ELSE NULL END WHERE entry_id=?", (status, status, entry_id))
    db.execute("INSERT INTO audit_logs(actor_id,action,entity_type,entity_id) VALUES(?,?, 'entry',?)", (session["user_id"], action, entry_id))
    if status == "published": rebuild_search_index(db, entry_id)
    else: db.execute("DELETE FROM entry_search_index WHERE entry_id=?", (entry_id,))
    db.commit(); flash("公開状態を変更しました。")
    return redirect(request.referrer or url_for("dashboard.index"))


@bp.post("/backup")
@role_required("admin")
def backup():
    result = create_backup(
        current_app.config["DATABASE"],
        current_app.config["BACKUP_ROOT"],
        session["user_id"],
    )
    db = get_db()
    db.execute("INSERT INTO backup_runs(actor_id,filename,sha256,size_bytes,integrity_result) VALUES(?,?,?,?,?)",
               (session["user_id"], result["filename"], result["sha256"], result["size_bytes"], result["integrity"])); db.commit()
    flash(f"検証済みバックアップを作成しました：{result['filename']}")
    return redirect(url_for("admin_v2.index"))


@bp.route("/database-update", methods=("GET", "POST"))
@role_required("admin")
def database_update():
    preview = None
    live_summary = None
    token = session.get("database_update_token")
    if request.method == "POST":
        upload = request.files.get("database_file")
        filename = Path(upload.filename or "").name if upload else ""
        if not upload or not filename:
            flash("更新に使うDBファイルを選んでください。")
            return redirect(url_for("admin_v2.database_update"))
        if Path(filename).suffix.lower() not in (".db", ".sqlite", ".sqlite3"):
            flash("拡張子が .db、.sqlite、.sqlite3 のファイルを選んでください。")
            return redirect(url_for("admin_v2.database_update"))
        old_token = session.pop("database_update_token", None)
        if old_token:
            try:
                pending_path(current_app.config["BACKUP_ROOT"], old_token).unlink(missing_ok=True)
            except DatabaseUpdateError:
                pass
        try:
            token, _path, preview = save_pending_upload(
                upload, current_app.config["BACKUP_ROOT"]
            )
            session["database_update_token"] = token
            session["database_update_filename"] = filename[:120]
            session["database_update_sha256"] = preview["sha256"]
            flash("DBを安全に読み取りました。件数を確認してから更新を実行してください。")
            return redirect(url_for("admin_v2.database_update"))
        except DatabaseUpdateError as error:
            flash(str(error))
            return redirect(url_for("admin_v2.database_update"))
    if token:
        try:
            preview = inspect_database(
                pending_path(current_app.config["BACKUP_ROOT"], token)
            )
            live_summary = inspect_database(current_app.config["DATABASE"])
        except DatabaseUpdateError as error:
            session.pop("database_update_token", None)
            session.pop("database_update_filename", None)
            session.pop("database_update_sha256", None)
            flash(str(error))
    return render_template(
        "v2/database_update.html",
        preview=preview,
        live=live_summary,
        filename=session.get("database_update_filename"),
        token=token,
        csrf_token=csrf_token(),
    )


@bp.post("/database-update/cancel")
@role_required("admin")
def cancel_database_update():
    token = session.pop("database_update_token", None)
    session.pop("database_update_filename", None)
    session.pop("database_update_sha256", None)
    if token:
        try:
            pending_path(current_app.config["BACKUP_ROOT"], token).unlink(missing_ok=True)
        except DatabaseUpdateError:
            pass
    flash("DB更新を取り消しました。現在の辞書データは変更されていません。")
    return redirect(url_for("admin_v2.database_update"))


@bp.post("/database-update/apply")
@role_required("admin")
def apply_database_update():
    token = request.form.get("token", "")
    expected_token = session.get("database_update_token", "")
    if not expected_token or not secrets.compare_digest(token, expected_token):
        flash("確認情報の有効期限が切れました。DBファイルを選び直してください。")
        return redirect(url_for("admin_v2.database_update"))
    if request.form.get("confirm") != "yes":
        flash("注意事項を確認し、確認欄にチェックを入れてください。")
        return redirect(url_for("admin_v2.database_update"))
    db = get_db()
    current_user = db.execute(
        """SELECT id,username,display_name,password_hash FROM users
           WHERE id=? AND role='admin' AND is_active=1""",
        (session["user_id"],),
    ).fetchone()
    if not current_user or not check_password_hash(
        current_user["password_hash"], request.form.get("password", "")
    ):
        flash("現在の完全管理者パスワードが正しくありません。")
        return redirect(url_for("admin_v2.database_update"))
    current_admin = dict(current_user)
    try:
        uploaded = pending_path(current_app.config["BACKUP_ROOT"], token)
        close_db()
        result = replace_database(
            current_app.config["DATABASE"],
            current_app.config["BACKUP_ROOT"],
            uploaded,
            current_admin,
            session.get("database_update_sha256", ""),
        )
        session["user_id"] = result["actor_id"]
        session.pop("database_update_token", None)
        session.pop("database_update_filename", None)
        session.pop("database_update_sha256", None)
        flash(
            f"DBを更新しました。更新前のデータは {result['backup']['filename']} に保存されています。"
        )
        return redirect(url_for("admin_v2.index"))
    except DatabaseUpdateError as error:
        flash(str(error))
    except Exception:
        flash("DB更新を完了できませんでした。現在のDBは維持または自動復元されています。")
    return redirect(url_for("admin_v2.database_update"))


@bp.get("/history")
@role_required("admin")
def history():
    rows = get_db().execute("SELECT a.*,u.display_name FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.created_at DESC LIMIT 300").fetchall()
    return render_template("v2/history.html", rows=rows, csrf_token=csrf_token())


@bp.route("/import", methods=("GET", "POST"))
@role_required("admin")
def import_entries():
    db = get_db(); preview = None
    if request.method == "POST":
        file = request.files.get("file")
        try:
            payload = json.loads(file.read().decode("utf-8-sig")) if file else None
            if not isinstance(payload, list) or len(payload) > 10000: raise ValueError
            errors = []
            for index,item in enumerate(payload,1):
                if not isinstance(item,dict) or not str(item.get("headword","")).strip(): errors.append(f"{index}行目：見出し語がありません")
                if item.get("pos") and item["pos"] not in ALLOWED_POS: errors.append(f"{index}行目：品詞を確認してください")
            batch_id = db.execute("INSERT INTO import_batches(created_by,original_filename,payload_json) VALUES(?,?,?) RETURNING id",
                (session["user_id"], Path(file.filename or "import.json").name, json.dumps(payload,ensure_ascii=False))).fetchone()[0]
            db.commit(); preview={"id":batch_id,"count":len(payload),"errors":errors,"samples":payload[:10]}
        except Exception:
            flash("ファイルを読み込めませんでした。指定された一括登録形式のファイルを選んでください。")
    return render_template("v2/import.html", preview=preview, csrf_token=csrf_token())


@bp.post("/import/<int:batch_id>/apply")
@role_required("admin")
def apply_import(batch_id):
    db=get_db(); batch=db.execute("SELECT * FROM import_batches WHERE id=? AND status='preview'",(batch_id,)).fetchone()
    if not batch: return ("",404)
    payload=json.loads(batch["payload_json"]); created=[]; errors=[]
    for index,item in enumerate(payload,1):
        try:
            headword=str(item.get("headword","")).strip()
            if not headword: raise ValueError("見出し語がありません")
            snapshot={key:item.get(key,"") for key in ("headword","kana","ipa","pos","verb_class","verb_stem","tone","etymology","historical_change","supplemental_note")}
            snapshot.update(meanings=item.get("meanings",{}),synonyms=item.get("synonyms",[]),conjugations=item.get("conjugations",[]),examples=item.get("examples",[]))
            entry_id=db.execute("INSERT INTO entries(headword) VALUES(?)",(headword,)).lastrowid
            revision_id=db.execute("INSERT INTO entry_revisions(entry_id,author_id,snapshot_json,change_summary) VALUES(?,?,?,'一括インポート') RETURNING id",(entry_id,session["user_id"],json.dumps(snapshot,ensure_ascii=False))).fetchone()[0]
            db.execute("INSERT INTO entry_workflow(entry_id,publication_status,workflow_status,created_by,current_revision_id) VALUES(?,'unpublished','draft',?,?)",(entry_id,session["user_id"],revision_id))
            created.append(entry_id)
        except Exception as error:
            errors.append({"row":index,"message":str(error)})
    db.execute("UPDATE import_batches SET status='applied',result_json=?,applied_at=CURRENT_TIMESTAMP WHERE id=?",(json.dumps({"created":len(created),"errors":errors},ensure_ascii=False),batch_id))
    db.execute("INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,after_json) VALUES(?,'bulk_import','import_batch',?,?)",(session["user_id"],batch_id,json.dumps({"created":len(created),"errors":len(errors)})))
    db.commit(); flash(f"{len(created)}語を非公開の下書きとして取り込みました。エラーは{len(errors)}件です。")
    return redirect(url_for("admin_v2.index"))


@bp.get("/quarantine")
@role_required("admin")
def quarantine():
    rows=get_db().execute("SELECT * FROM quarantine_records WHERE restored_at IS NULL ORDER BY source_table,source_id").fetchall()
    records=[{"id":row["id"],"table":row["source_table"],"reason":row["reason"],"data":json.loads(row["record_json"])} for row in rows]
    return render_template("v2/quarantine.html",records=records,csrf_token=csrf_token())


@bp.post("/quarantine/<int:record_id>/restore")
@role_required("admin")
def restore_quarantine(record_id):
    db=get_db(); row=db.execute("SELECT * FROM quarantine_records WHERE id=? AND restored_at IS NULL",(record_id,)).fetchone()
    allowed={"meanings","synonyms","conjugations","examples","example_translations","media_files"}
    if not row or row["source_table"] not in allowed: return ("",404)
    data=json.loads(row["record_json"]); columns={item[1] for item in db.execute(f"PRAGMA table_info({row['source_table']})")}; clean={k:v for k,v in data.items() if k in columns}
    try:
        names=",".join(clean); placeholders=",".join("?" for _ in clean)
        db.execute(f"INSERT INTO {row['source_table']}({names}) VALUES({placeholders})",tuple(clean.values()))
        db.execute("UPDATE quarantine_records SET restored_at=CURRENT_TIMESTAMP WHERE id=?",(record_id,)); db.commit(); flash("関連先を確認し、データを復元しました。")
    except Exception:
        db.rollback(); flash("関連する語彙・例文が存在しないため、まだ復元できません。先に親データを復元してください。")
    return redirect(url_for("admin_v2.quarantine"))
