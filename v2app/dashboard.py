from flask import Blueprint, render_template, session

from .auth import login_required
from .db import get_db
from .security import csrf_token

bp = Blueprint("dashboard", __name__)


@bp.get("/v2/admin")
@login_required
def index():
    db = get_db()
    user_id = session["user_id"]
    counts = {
        "assigned": db.execute("SELECT COUNT(*) FROM entry_assignments WHERE assignee_id = ? AND status != 'completed'", (user_id,)).fetchone()[0],
        "review": db.execute("SELECT COUNT(*) FROM review_requests WHERE reviewer_id = ? AND status = 'pending'", (user_id,)).fetchone()[0],
        "returned": db.execute("SELECT COUNT(*) FROM entry_revisions WHERE author_id = ? AND status = 'returned'", (user_id,)).fetchone()[0],
    }
    return render_template("v2/dashboard.html", counts=counts, csrf_token=csrf_token())
