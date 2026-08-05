import json

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from .auth import login_required, role_required
from .db import get_db
from .security import csrf_token

bp = Blueprint("sources", __name__, url_prefix="/v2/sources")


def source_record_values(form):
    return {
        "source_headword": form.get("source_headword", "").strip(),
        "source_description": form.get("source_description", "").strip(),
        "locator": form.get("locator", "").strip(),
        "note": form.get("note", "").strip(),
        "adopted_interpretation": form.get("adopted_interpretation", "").strip(),
    }


def audit_source_record(db, action, entry_id, before=None, after=None):
    db.execute(
        "INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,before_json,after_json) VALUES(?,?,?,?,?,?)",
        (session["user_id"], action, "entry", entry_id,
         json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None),
    )


def can_edit_entry(db, entry_id):
    if session.get("role") == "admin":
        return True
    return bool(db.execute("SELECT 1 FROM entry_assignments WHERE entry_id=? AND assignee_id=? AND status!='completed' UNION SELECT 1 FROM entry_revisions WHERE entry_id=? AND author_id=? AND status IN ('draft','returned')",
                           (entry_id, session["user_id"], entry_id, session["user_id"])).fetchone())


@bp.get("")
@login_required
def index():
    rows = get_db().execute(
        "WITH linked AS (SELECT source_id,entry_id FROM entry_source_sections "
        "UNION SELECT source_id,entry_id FROM entry_primary_sources) "
        "SELECT s.*,COUNT(DISTINCT linked.entry_id) entry_count FROM sources s "
        "LEFT JOIN linked ON linked.source_id=s.id WHERE s.is_active=1 OR ?='admin' "
        "GROUP BY s.id ORDER BY s.is_active DESC,s.name",
        (session.get("role"),),
    ).fetchall()
    return render_template("v2/sources.html", sources=rows, csrf_token=csrf_token())


@bp.post("")
@role_required("admin")
def create():
    name = request.form.get("name", "").strip(); bibliography = request.form.get("bibliography", "").strip()
    if not name or not bibliography:
        flash("資料名と完全な書誌情報を入力してください。")
    else:
        db = get_db(); db.execute("INSERT INTO sources(name,abbreviation,bibliography,url,source_type,show_on_public) VALUES(?,?,?,?,?,?)",
            (name, request.form.get("abbreviation", "").strip(), bibliography, request.form.get("url", "").strip(), request.form.get("source_type", "").strip(), 0 if request.form.get("show_on_public", "1") == "0" else 1)); db.commit(); flash("資料を登録しました。")
    return redirect(url_for("sources.index"))


@bp.route("/<int:source_id>/edit", methods=("GET", "POST"))
@role_required("admin")
def edit_source(source_id):
    db=get_db(); source=db.execute("SELECT * FROM sources WHERE id=?",(source_id,)).fetchone()
    if not source: abort(404)
    if request.method=="POST":
        name=request.form.get("name","").strip(); bibliography=request.form.get("bibliography","").strip()
        if not name or not bibliography: flash("資料名と完全な書誌情報を入力してください。")
        else:
            db.execute("UPDATE sources SET name=?,abbreviation=?,bibliography=?,url=?,source_type=?,show_on_public=? WHERE id=?",(name,request.form.get("abbreviation","").strip(),bibliography,request.form.get("url","").strip(),request.form.get("source_type","").strip(),0 if request.form.get("show_on_public", "1") == "0" else 1,source_id)); db.commit(); flash("資料情報を更新しました。"); return redirect(url_for("sources.index"))
    return render_template("v2/source_edit.html",source=source,csrf_token=csrf_token())


@bp.post("/<int:source_id>/archive")
@role_required("admin")
def archive_source(source_id):
    db=get_db(); db.execute("UPDATE sources SET is_active=1-is_active WHERE id=?",(source_id,)); db.commit(); flash("資料の表示状態を変更しました。関連記述は保持されます。")
    return redirect(url_for("sources.index"))


@bp.route("/entry/<int:entry_id>", methods=("GET", "POST"))
@login_required
def entry_sources(entry_id):
    db = get_db()
    if not can_edit_entry(db, entry_id): abort(403)
    entry = db.execute("SELECT id,headword FROM entries WHERE id=?", (entry_id,)).fetchone()
    if not entry: abort(404)
    if request.method == "POST":
        source_id = request.form.get("source_id", type=int)
        if not db.execute("SELECT 1 FROM sources WHERE id=? AND is_active=1", (source_id,)).fetchone(): abort(400)
        values = source_record_values(request.form)
        if not any(values.values()):
            flash("資料名だけでは追加できません。資料内の見出し語・説明・掲載箇所・整理した解釈・注記のいずれかを入力してください。")
            return redirect(url_for("sources.entry_sources", entry_id=entry_id) + "#add-source-record")
        db.execute("INSERT INTO entry_source_records(entry_id,source_id,source_headword,source_description,locator,note,adopted_interpretation,created_by) VALUES(?,?,?,?,?,?,?,?)",
            (entry_id, source_id, values["source_headword"], values["source_description"], values["locator"], values["note"], values["adopted_interpretation"], session["user_id"]))
        audit_source_record(db, "attach_source", entry_id, after={"source_id": source_id, **values})
        db.commit(); flash("資料別の出典情報として追加しました。")
        return redirect(url_for("sources.entry_sources", entry_id=entry_id))
    sources = db.execute("SELECT * FROM sources WHERE is_active=1 ORDER BY name").fetchall()
    records = db.execute("SELECT r.*,s.name,s.abbreviation,s.bibliography FROM entry_source_records r JOIN sources s ON s.id=r.source_id WHERE r.entry_id=? ORDER BY r.id", (entry_id,)).fetchall()
    media = db.execute("SELECT mf.* FROM media_files mf LEFT JOIN examples ex ON ex.id=mf.example_id WHERE COALESCE(mf.entry_id,ex.entry_id)=? ORDER BY mf.created_at DESC",(entry_id,)).fetchall()
    return render_template("v2/entry_sources.html", entry=entry, sources=sources, records=records, media=media, csrf_token=csrf_token())


@bp.post("/record/<int:record_id>/toggle")
@login_required
def toggle_record(record_id):
    db=get_db(); row=db.execute("SELECT * FROM entry_source_records WHERE id=?",(record_id,)).fetchone()
    if not row or not can_edit_entry(db,row["entry_id"]): abort(403)
    before=dict(row); new_state=0 if row["is_archived"] else 1
    db.execute("UPDATE entry_source_records SET is_archived=? WHERE id=?",(new_state,record_id))
    audit_source_record(db, "archive_source_record" if new_state else "restore_source_record", row["entry_id"], before=before, after={**before,"is_archived":new_state})
    db.commit(); flash("出典情報の公開状態を変更しました。内容は削除されていません。")
    return redirect(url_for("sources.entry_sources",entry_id=row["entry_id"]))


@bp.route("/record/<int:record_id>/edit", methods=("GET", "POST"))
@login_required
def edit_record(record_id):
    db=get_db(); row=db.execute("SELECT r.*,s.name FROM entry_source_records r JOIN sources s ON s.id=r.source_id WHERE r.id=?",(record_id,)).fetchone()
    if not row or not can_edit_entry(db,row["entry_id"]): abort(403)
    if request.method=="POST":
        values=source_record_values(request.form)
        if not any(values.values()):
            flash("出典情報をすべて空にはできません。不要な場合は一覧画面で非表示にしてください。")
            return render_template("v2/source_record_edit.html",record=row,csrf_token=csrf_token()),400
        before=dict(row)
        db.execute("UPDATE entry_source_records SET source_headword=?,source_description=?,locator=?,note=?,adopted_interpretation=? WHERE id=?",(values["source_headword"],values["source_description"],values["locator"],values["note"],values["adopted_interpretation"],record_id))
        audit_source_record(db, "edit_source_record", row["entry_id"], before=before, after={**before,**values})
        db.commit(); flash("この資料の出典情報だけを更新しました。"); return redirect(url_for("sources.entry_sources",entry_id=row["entry_id"]))
    return render_template("v2/source_record_edit.html",record=row,csrf_token=csrf_token())
