import hashlib
import uuid
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, request, session, url_for

from .auth import login_required
from .db import get_db

bp = Blueprint("media_v2", __name__, url_prefix="/v2/media")
SIGNATURES = {
    "png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    "jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    "gif": lambda b: b.startswith((b"GIF87a", b"GIF89a")),
    "wav": lambda b: b.startswith(b"RIFF") and b[8:12] == b"WAVE",
    "mp3": lambda b: b.startswith(b"ID3") or (len(b) > 1 and b[0] == 0xFF and b[1] & 0xE0 == 0xE0),
}


class MediaValidationError(ValueError):
    pass


def save_media_file(db, entry_id, file, file_type="audio", example_id=None, revision_id=None, pending=False, description=""):
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    allowed = ("mp3", "wav") if file_type == "audio" else ("png", "jpg", "jpeg", "gif")
    data = file.read()
    if ext not in allowed or len(data) == 0 or not SIGNATURES.get(ext, lambda _data: False)(data):
        raise MediaValidationError("ファイルの内容と形式が一致しないため保存できませんでした。")
    name = f"{uuid.uuid4().hex}.{ext}"
    relative = f"{'audio' if file_type == 'audio' else 'images'}/{name}"
    root = Path(current_app.config["MEDIA_ROOT"])
    target = (root / relative).resolve()
    if root.resolve() not in target.parents:
        raise MediaValidationError("安全な保存先を作成できませんでした。")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    db.execute("INSERT INTO media_files(entry_id,example_id,file_type,file_path,original_filename,description,sha256,revision_id,is_pending) VALUES(?,?,?,?,?,?,?,?,?)",
               (entry_id, example_id, file_type, relative, Path(file.filename).name, description.strip(), digest, revision_id, int(pending)))
    return relative


def permitted(db, entry_id):
    return session.get("role") == "admin" or bool(db.execute("SELECT 1 FROM entry_assignments WHERE entry_id=? AND assignee_id=? AND status!='completed' UNION SELECT 1 FROM entry_revisions WHERE entry_id=? AND author_id=? AND status IN ('draft','returned')", (entry_id,session["user_id"],entry_id,session["user_id"])).fetchone())


def media_redirect(entry_id):
    if request.form.get("return_to") == "editor":
        return redirect(url_for("editorial.edit_entry", entry_id=entry_id) + "#media-management")
    return redirect(url_for("sources.entry_sources", entry_id=entry_id))


def audit_media(db, action, row, after=None):
    import json
    db.execute(
        "INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,before_json,after_json) VALUES(?,?,?,?,?,?)",
        (session["user_id"], action, "entry", row["owner_entry"], json.dumps(dict(row), ensure_ascii=False),
         json.dumps(after, ensure_ascii=False) if after is not None else None),
    )


@bp.post("/upload")
@login_required
def upload():
    db = get_db(); entry_id = request.form.get("entry_id", type=int); example_id = request.form.get("example_id", type=int)
    file = request.files.get("file"); file_type = request.form.get("file_type")
    if not entry_id or not file or file_type not in ("audio", "image") or not permitted(db, entry_id): abort(400)
    if example_id and not db.execute("SELECT 1 FROM examples WHERE id=? AND entry_id=?", (example_id,entry_id)).fetchone(): abort(400)
    try:
        save_media_file(db, entry_id, file, file_type, example_id)
    except MediaValidationError as error:
        flash(str(error))
        return media_redirect(entry_id)
    db.commit(); flash("メディアを安全な自動ファイル名で保存しました。")
    return media_redirect(entry_id)


@bp.post("/<int:media_id>/archive")
@login_required
def archive(media_id):
    db=get_db(); row=db.execute("SELECT mf.*,COALESCE(mf.entry_id,ex.entry_id) owner_entry FROM media_files mf LEFT JOIN examples ex ON ex.id=mf.example_id WHERE mf.id=?",(media_id,)).fetchone()
    if not row or not permitted(db,row["owner_entry"]): abort(403)
    db.execute("UPDATE media_files SET is_archived=1 WHERE id=?",(media_id,)); audit_media(db,"archive_media",row,{**dict(row),"is_archived":1}); db.commit(); flash("削除しました。ファイルは保持されているため、いつでも復元できます。")
    return media_redirect(row["owner_entry"])


@bp.post("/<int:media_id>/restore")
@login_required
def restore(media_id):
    db=get_db(); row=db.execute("SELECT mf.*,COALESCE(mf.entry_id,ex.entry_id) owner_entry FROM media_files mf LEFT JOIN examples ex ON ex.id=mf.example_id WHERE mf.id=?",(media_id,)).fetchone()
    if not row or not permitted(db,row["owner_entry"]): abort(403)
    db.execute("UPDATE media_files SET is_archived=0 WHERE id=?",(media_id,)); audit_media(db,"restore_media",row,{**dict(row),"is_archived":0}); db.commit(); flash("メディアを復元しました。")
    return media_redirect(row["owner_entry"])


@bp.post("/<int:media_id>/description")
@login_required
def update_description(media_id):
    db=get_db(); row=db.execute("SELECT mf.*,COALESCE(mf.entry_id,ex.entry_id) owner_entry FROM media_files mf LEFT JOIN examples ex ON ex.id=mf.example_id WHERE mf.id=?",(media_id,)).fetchone()
    if not row or row["file_type"]!="image" or not permitted(db,row["owner_entry"]): abort(403)
    description=request.form.get("description","").strip()
    db.execute("UPDATE media_files SET description=? WHERE id=?",(description,media_id)); audit_media(db,"edit_media_description",row,{**dict(row),"description":description}); db.commit(); flash("画像の説明を更新しました。")
    return media_redirect(row["owner_entry"])
