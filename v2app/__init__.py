import os
from datetime import timedelta
from pathlib import Path

from flask import Flask, render_template

from .db import close_db
from .security import apply_security_headers, csrf_protect


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    base_dir = Path(__file__).resolve().parent.parent
    trusted_hosts = [host.strip() for host in os.environ.get(
        "YONAGUNI_TRUSTED_HOSTS", "localhost,127.0.0.1"
    ).split(",") if host.strip()]
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("YONAGUNI_SECRET_KEY"),
        DATABASE=os.environ.get("YONAGUNI_DATABASE", str(base_dir / "database" / "yonaguni_v2.db")),
        MEDIA_ROOT=os.environ.get("YONAGUNI_MEDIA_ROOT", str(base_dir / "v6" / "static" / "media")),
        BACKUP_ROOT=os.environ.get("YONAGUNI_BACKUP_ROOT", str(base_dir / "backups")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("YONAGUNI_HTTPS", "0") == "1",
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        TRUSTED_HOSTS=trusted_hosts,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        if app.config.get("TESTING"):
            app.config["SECRET_KEY"] = "test-only-key"
        else:
            raise RuntimeError("YONAGUNI_SECRET_KEY must be set")

    from .auth import bp as auth_bp
    from .dashboard import bp as dashboard_bp
    from .editorial import bp as editorial_bp
    from .admin import bp as admin_bp
    from .sources import bp as sources_bp
    from .media import bp as media_bp
    from .public import bp as public_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(editorial_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(sources_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(public_bp)
    app.teardown_appcontext(close_db)
    app.before_request(csrf_protect)
    app.after_request(apply_security_headers)

    @app.errorhandler(400)
    def bad_request(_error):
        return render_template("v2/error.html", message="入力内容を確認して、もう一度お試しください。"), 400

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("v2/error.html", message="この操作を行う権限がありません。"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("v2/error.html", message="お探しのページは見つかりませんでした。"), 404

    @app.errorhandler(500)
    def server_error(_error):
        return render_template("v2/error.html", message="処理を完了できませんでした。時間をおいてもう一度お試しください。"), 500

    @app.get("/healthz")
    def healthz():
        from .db import get_db
        get_db().execute("SELECT 1").fetchone()
        return {"status": "ok"}
    return app
