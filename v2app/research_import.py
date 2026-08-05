import json
from collections import defaultdict
from pathlib import Path

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

from .auth import role_required
from .db import get_db
from .research_sheet import (
    ResearchSheetError,
    duplicate_candidates,
    duplicate_corpus,
    existing_snapshot_for_merge,
    manual_merge_targets,
    merge_imported_for_source,
    parse_research_workbook,
)
from .security import csrf_token


bp = Blueprint("research_import", __name__, url_prefix="/v2/admin-tools/research-sheet")
MAX_IMPORT_ENTRIES = 300


def _batch(db, batch_id):
    row = db.execute(
        "SELECT * FROM import_batches WHERE id=?",
        (batch_id,),
    ).fetchone()
    if not row:
        abort(404)
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        abort(404)
    if not isinstance(payload, dict) or payload.get("kind") != "research_sheet":
        abort(404)
    return row, payload


def _sources(db):
    return db.execute(
        "SELECT id,name,abbreviation,bibliography,show_on_public FROM sources WHERE is_active=1 ORDER BY name,id"
    ).fetchall()


def _selected_source(db):
    raw_source_id = request.form.get("source_id", "").strip()
    if not raw_source_id:
        return None, None
    try:
        source_id = int(raw_source_id)
    except (TypeError, ValueError) as error:
        raise ResearchSheetError("出典を選び直してください。") from error
    source = db.execute(
        "SELECT id,name,abbreviation,show_on_public FROM sources WHERE id=? AND is_active=1",
        (source_id,),
    ).fetchone()
    if not source:
        raise ResearchSheetError("選択した出典を利用できません。出典を選び直してください。")
    return source_id, source


def _reviewers(db):
    return db.execute(
        "SELECT u.id,u.display_name,u.role,COUNT(rr.id) pending_count "
        "FROM users u LEFT JOIN review_requests rr ON rr.reviewer_id=u.id AND rr.status='pending' "
        "WHERE u.is_active=1 AND u.id!=? GROUP BY u.id ORDER BY u.role='editor' DESC,u.display_name",
        (session["user_id"],),
    ).fetchall()


def _snapshot(entry):
    keys = (
        "headword", "kana", "ipa", "pos", "verb_class", "verb_stem", "tone",
        "etymology", "historical_change", "supplemental_note", "meanings",
        "synonyms", "conjugations", "examples", "source_sections", "primary_source_id",
    )
    return {key: entry.get(key) for key in keys}


def _audit(db, action, entity_type, entity_id, after=None):
    db.execute(
        "INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,after_json) VALUES(?,?,?,?,?)",
        (
            session["user_id"], action, entity_type, entity_id,
            json.dumps(after, ensure_ascii=False) if after is not None else None,
        ),
    )


@bp.route("", methods=("GET", "POST"))
@role_required("admin")
def upload():
    if request.method == "POST":
        uploaded = request.files.get("research_sheet")
        filename = Path((uploaded.filename or "").replace("\\", "/")).name if uploaded else ""
        if not uploaded or not filename:
            flash("定期調査のExcelファイルを選んでください。")
            return redirect(url_for("research_import.upload"))
        if Path(filename).suffix.lower() != ".xlsx":
            flash("拡張子が .xlsx の定期調査シートを選んでください。")
            return redirect(url_for("research_import.upload"))
        try:
            payload = parse_research_workbook(uploaded.read(), filename)
            if len(payload["entries"]) > MAX_IMPORT_ENTRIES:
                raise ResearchSheetError(f"一度に取り込める見出し語は{MAX_IMPORT_ENTRIES}語までです。")
        except ResearchSheetError as error:
            flash(str(error))
            return redirect(url_for("research_import.upload"))
        db = get_db()
        batch_id = db.execute(
            "INSERT INTO import_batches(created_by,original_filename,payload_json) VALUES(?,?,?) RETURNING id",
            (session["user_id"], filename[:120], json.dumps(payload, ensure_ascii=False)),
        ).fetchone()[0]
        _audit(db, "research_sheet_preview", "import_batch", batch_id, {
            "filename": filename[:120], "sheet": payload["sheet_name"], "entries": len(payload["entries"]),
        })
        db.commit()
        return redirect(url_for("research_import.preview", batch_id=batch_id))
    return render_template("v2/research_import.html", csrf_token=csrf_token())


@bp.get("/<int:batch_id>")
@role_required("admin")
def preview(batch_id):
    db = get_db()
    batch, payload = _batch(db, batch_id)
    result = None
    entries = []
    if batch["status"] == "preview":
        corpus = duplicate_corpus(db)
        for index, imported in enumerate(payload["entries"]):
            candidates = duplicate_candidates(db, imported, corpus=corpus)
            exact_target = next(
                (item["id"] for item in candidates if item["exact"] and not item["merge_blocked"]),
                None,
            )
            default_target = exact_target or next(
                (item["id"] for item in candidates if not item["merge_blocked"]), None
            )
            entries.append({
                "index": index,
                "imported": imported,
                "candidates": candidates,
                "default_action": "merge" if exact_target else ("skip" if any(item["exact"] for item in candidates) else "new"),
                "default_target": default_target,
                "can_merge": default_target is not None,
            })
    elif batch["result_json"]:
        try:
            result = json.loads(batch["result_json"])
        except (TypeError, ValueError):
            result = {"errors": [{"message": "処理結果を読み取れませんでした。"}]}
    return render_template(
        "v2/research_import.html",
        batch=batch,
        payload=payload,
        entries=entries,
        reviewers=_reviewers(db),
        sources=_sources(db),
        result=result,
        csrf_token=csrf_token(),
    )


@bp.get("/search-targets")
@role_required("admin")
def search_targets():
    return jsonify({"results": manual_merge_targets(get_db(), request.args.get("q", ""))})


@bp.get("/history")
@role_required("admin")
def history():
    rows = get_db().execute(
        "SELECT b.*,u.display_name FROM import_batches b "
        "JOIN users u ON u.id=b.created_by ORDER BY b.created_at DESC,b.id DESC LIMIT 100"
    ).fetchall()
    batches = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict) or payload.get("kind") != "research_sheet":
            continue
        try:
            result = json.loads(row["result_json"]) if row["result_json"] else {}
        except (TypeError, ValueError):
            result = {}
        actions = []
        if row["status"] == "applied":
            actions.extend({"headword": item.get("headword", ""), "action": "新規下書き", "entry_id": item.get("entry_id")} for item in result.get("created", []))
            for item in result.get("merged", []):
                for headword in item.get("imported_headwords", []):
                    actions.append({
                        "headword": headword,
                        "action": f"「{item.get('headword', '')}」へ追加",
                        "entry_id": item.get("entry_id"),
                    })
            actions.extend({"headword": item.get("headword", ""), "action": "除外", "entry_id": None} for item in result.get("skipped", []))
            actions.extend({"headword": item.get("headword", ""), "action": "処理できず", "detail": item.get("message", ""), "entry_id": None} for item in result.get("errors", []))
        else:
            label = {
                "cancelled": "取込前に取消",
                "failed": "取込失敗",
            }.get(row["status"], "確認待ち")
            actions = [
                {"headword": item.get("headword", ""), "action": label, "entry_id": None}
                for item in payload.get("entries", [])
            ]
        batches.append({
            "row": row,
            "payload": payload,
            "result": result,
            "actions": actions,
            "source_name": result.get("source_name") or "指定なし（町側の記述）",
            "source_visibility": result.get("source_shown_on_public") if result.get("source_name") else None,
        })
    return render_template(
        "v2/research_import_history.html",
        batches=batches,
        csrf_token=csrf_token(),
    )


def _choose_reviewers(db, mode, revision_count):
    if revision_count == 0:
        return []
    if mode == "none":
        return [None] * revision_count
    reviewers = [dict(row) for row in _reviewers(db)]
    if not reviewers:
        raise ResearchSheetError("精査を依頼できる別の有効なアカウントがありません。")
    if mode != "balanced":
        try:
            reviewer_id = int(mode)
        except (TypeError, ValueError) as error:
            raise ResearchSheetError("精査の依頼先を選び直してください。") from error
        if reviewer_id not in {item["id"] for item in reviewers}:
            raise ResearchSheetError("精査の依頼先を選び直してください。")
        return [reviewer_id] * revision_count
    loads = {item["id"]: item["pending_count"] for item in reviewers}
    assignments = []
    for _ in range(revision_count):
        reviewer_id = min(loads, key=lambda value: (loads[value], value))
        assignments.append(reviewer_id)
        loads[reviewer_id] += 1
    return assignments


@bp.post("/<int:batch_id>/apply")
@role_required("admin")
def apply(batch_id):
    db = get_db()
    batch, payload = _batch(db, batch_id)
    if batch["status"] != "preview":
        flash("この調査シートは処理済みです。")
        return redirect(url_for("research_import.preview", batch_id=batch_id))

    try:
        source_id, source = _selected_source(db)
    except ResearchSheetError as error:
        flash(str(error))
        return redirect(url_for("research_import.preview", batch_id=batch_id))

    new_entries = []
    merge_groups = defaultdict(list)
    skipped = []
    errors = []
    for index, imported in enumerate(payload["entries"]):
        action = request.form.get(f"action_{index}", "skip")
        if action == "skip":
            skipped.append({"headword": imported["headword"], "reason": "画面で除外"})
        elif action == "new":
            new_entries.append((index, imported))
        elif action == "merge":
            try:
                target_id = int(request.form.get(f"target_{index}", ""))
            except (TypeError, ValueError):
                errors.append({"headword": imported["headword"], "message": "統合先が選ばれていません。"})
                continue
            merge_groups[target_id].append((index, imported))
        else:
            errors.append({"headword": imported["headword"], "message": "処理方法を選び直してください。"})

    prepared_merges = []
    for target_id, items in merge_groups.items():
        try:
            combined = existing_snapshot_for_merge(db, target_id)
            for _index, imported in items:
                combined = merge_imported_for_source(combined, imported, source_id)
            prepared_merges.append((target_id, items, combined))
        except ResearchSheetError as error:
            for _index, imported in items:
                errors.append({"headword": imported["headword"], "message": str(error)})

    revision_total = len(new_entries) + len(prepared_merges)
    try:
        reviewers = _choose_reviewers(db, request.form.get("reviewer_mode", "none"), revision_total)
    except ResearchSheetError as error:
        flash(str(error))
        return redirect(url_for("research_import.preview", batch_id=batch_id))

    created = []
    merged = []
    revisions = []
    try:
        for _index, imported in new_entries:
            snapshot = _snapshot(imported)
            snapshot["primary_source_id"] = source_id
            entry_id = db.execute("INSERT INTO entries(headword) VALUES(?)", (snapshot["headword"],)).lastrowid
            revision_id = db.execute(
                "INSERT INTO entry_revisions(entry_id,author_id,snapshot_json,change_summary) "
                "VALUES(?,?,?,'定期調査シートから新規登録') RETURNING id",
                (entry_id, session["user_id"], json.dumps(snapshot, ensure_ascii=False)),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO entry_workflow(entry_id,publication_status,workflow_status,created_by,current_revision_id) "
                "VALUES(?,'unpublished','draft',?,?)",
                (entry_id, session["user_id"], revision_id),
            )
            created.append({"entry_id": entry_id, "headword": snapshot["headword"]})
            revisions.append((entry_id, revision_id, snapshot["headword"]))
            _audit(db, "research_sheet_create_draft", "entry", entry_id, {
                "batch_id": batch_id, "source_id": source_id,
            })

        for target_id, items, snapshot in prepared_merges:
            revision_id = db.execute(
                "INSERT INTO entry_revisions(entry_id,author_id,snapshot_json,change_summary) "
                "VALUES(?,?,?,'定期調査シートの内容を追加') RETURNING id",
                (target_id, session["user_id"], json.dumps(snapshot, ensure_ascii=False)),
            ).fetchone()[0]
            db.execute(
                "UPDATE entry_workflow SET workflow_status='draft',current_revision_id=? WHERE entry_id=?",
                (revision_id, target_id),
            )
            imported_headwords = [item["headword"] for _index, item in items]
            merged.append({
                "entry_id": target_id, "headword": snapshot["headword"],
                "imported_headwords": imported_headwords,
            })
            revisions.append((target_id, revision_id, snapshot["headword"]))
            _audit(db, "research_sheet_merge_draft", "revision", revision_id, {
                "batch_id": batch_id, "entry_id": target_id, "imported_headwords": imported_headwords,
                "source_id": source_id,
            })

        requests = []
        reviewer_names = {row["id"]: row["display_name"] for row in _reviewers(db)}
        for (entry_id, revision_id, headword), reviewer_id in zip(revisions, reviewers):
            if reviewer_id is None:
                continue
            db.execute(
                "UPDATE entry_revisions SET status='review_requested',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (revision_id,),
            )
            review_id = db.execute(
                "INSERT INTO review_requests(revision_id,requester_id,reviewer_id) VALUES(?,?,?) RETURNING id",
                (revision_id, session["user_id"], reviewer_id),
            ).fetchone()[0]
            db.execute(
                "UPDATE entry_workflow SET workflow_status='review_requested' WHERE entry_id=?",
                (entry_id,),
            )
            requests.append({
                "review_id": review_id, "entry_id": entry_id, "headword": headword,
                "reviewer_id": reviewer_id, "reviewer_name": reviewer_names.get(reviewer_id, "確認担当者"),
            })
            _audit(db, "request_review", "review", review_id, {"batch_id": batch_id})

        result = {
            "created": created,
            "merged": merged,
            "skipped": skipped,
            "errors": errors,
            "review_requests": requests,
            "source_id": source_id,
            "source_name": source["name"] if source else None,
            "source_shown_on_public": bool(source["show_on_public"]) if source else False,
        }
        db.execute(
            "UPDATE import_batches SET status='applied',result_json=?,applied_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(result, ensure_ascii=False), batch_id),
        )
        _audit(db, "research_sheet_import", "import_batch", batch_id, {
            "created": len(created), "merged": len(merged), "skipped": len(skipped),
            "errors": len(errors), "review_requests": len(requests),
            "source_id": source_id, "source_name": source["name"] if source else None,
        })
        db.commit()
    except Exception:
        db.rollback()
        raise

    flash(
        f"新規{len(created)}語、既存語への追加{len(merged)}件を下書きにしました。"
        + (f" {len(requests)}件の精査依頼を送りました。" if requests else "")
        + (f" 処理できなかった項目は{len(errors)}件です。" if errors else "")
    )
    return redirect(url_for("research_import.preview", batch_id=batch_id))


@bp.post("/<int:batch_id>/cancel")
@role_required("admin")
def cancel(batch_id):
    db = get_db()
    batch, _payload = _batch(db, batch_id)
    if batch["status"] == "preview":
        db.execute("UPDATE import_batches SET status='cancelled' WHERE id=?", (batch_id,))
        _audit(db, "research_sheet_cancel", "import_batch", batch_id)
        db.commit()
        flash("この取込を取り消しました。辞書データは変更されていません。")
    return redirect(url_for("research_import.upload"))
