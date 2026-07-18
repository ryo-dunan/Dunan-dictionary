from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .security import csrf_token

bp = Blueprint("auth", __name__)
MAX_ATTEMPTS = 5
LOCK_MINUTES = 15


def login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        return view(**kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(**kwargs):
            if session.get("role") not in roles:
                return render_template("v2/error.html", message="この操作を行う権限がありません。"), 403
            return view(**kwargs)
        return wrapped
    return decorator


@bp.route("/v2/login", methods=("GET", "POST"))
def login():
    db = get_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        now = datetime.now(timezone.utc)
        window = (now - timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        attempts = db.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE username = ? AND succeeded = 0 AND attempted_at >= ?",
            (username, window),
        ).fetchone()[0]
        if attempts >= MAX_ATTEMPTS:
            flash("ログイン試行回数が上限に達しました。15分後にもう一度お試しください。")
            return render_template("v2/login.html", csrf_token=csrf_token()), 429

        user = db.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
        ).fetchone()
        valid = bool(user and check_password_hash(user["password_hash"], request.form.get("password", "")))
        db.execute(
            "INSERT INTO login_attempts(username, ip_address, succeeded) VALUES (?, ?, ?)",
            (username, request.remote_addr, int(valid)),
        )
        db.commit()
        if valid:
            session.clear()
            session.update(user_id=user["id"], display_name=user["display_name"], role=user["role"])
            session.permanent = True
            db.execute("UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?", (user["id"],)); db.commit()
            csrf_token()
            if "must_change_password" in user.keys() and user["must_change_password"]:
                return redirect(url_for("auth.change_password"))
            return redirect(url_for("dashboard.index"))
        flash("ユーザー名またはパスワードを確認してください。")
    return render_template("v2/login.html", csrf_token=csrf_token())


@bp.post("/v2/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/v2/change-password", methods=("GET", "POST"))
@login_required
def change_password():
    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 12 or password != request.form.get("confirmation"):
            flash("12文字以上の同じパスワードを2回入力してください。")
        else:
            db = get_db(); db.execute("UPDATE users SET password_hash=?,must_change_password=0,updated_at=CURRENT_TIMESTAMP WHERE id=?", (generate_password_hash(password), session["user_id"])); db.commit()
            flash("パスワードを変更しました。")
            return redirect(url_for("dashboard.index"))
    return render_template("v2/change_password.html", csrf_token=csrf_token())
