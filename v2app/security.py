import hmac
import secrets

from flask import abort, request, session


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_protect():
    if request.method in SAFE_METHODS:
        return None
    expected = session.get("csrf_token", "")
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not expected or not hmac.compare_digest(expected, supplied):
        abort(400, description="フォームの有効期限が切れました。画面を再読み込みしてください。")


def apply_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; media-src 'self'; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'"
    )
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.path.startswith("/v2/"):
        response.headers["Cache-Control"] = "no-store"
    return response
