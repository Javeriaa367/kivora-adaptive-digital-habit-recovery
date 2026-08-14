"""
Lightweight session-based CSRF protection (no flask-wtf dependency).

Token lives in the Flask session; every state-changing request (POST/PUT/
PATCH/DELETE) must echo it back via one of:
  - hidden form field  `csrf_token`
  - JSON body key      `csrf_token`
  - request header     `X-CSRF-Token`

Combined with SameSite=Lax cookies this gives two independent layers: a
cross-site POST can't read the token (no CORS), and its cookie wouldn't
be sent anyway. Templates get the token via `csrf_token()` (exposed by a
context processor in app.py); a small fetch() patch in base.html attaches
the `X-CSRF-Token` header to every non-GET request automatically, so the
app's JS-driven forms don't each need an edit.
"""
import hmac
import secrets

from flask import current_app, flash, jsonify, redirect, request, session, url_for

CSRF_SESSION_KEY = "csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Server-to-server, signature-authenticated endpoints with no browser
# session -- the Stripe webhook is the canonical case. Exempted because a
# session token can't exist for a request that never loaded the app.
CSRF_EXEMPT_PATHS = {
    "/api/billing/webhook",
}


def generate_csrf_token() -> str:
    token = secrets.token_urlsafe(32)
    session[CSRF_SESSION_KEY] = token
    return token


def get_csrf_token() -> str:
    """Template helper -- ensures a token exists in the session and returns
    it, so both the hidden-field forms and the JS meta tag can render it."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = generate_csrf_token()
    return token


def validate_csrf():
    """before_request handler. Returns None to allow the request, or a
    Flask response (400 for APIs, redirect for HTML) to block it."""
    if not current_app.config.get("CSRF_ENABLED", True):
        return None
    if request.method in SAFE_METHODS:
        return None
    if request.path in CSRF_EXEMPT_PATHS:
        return None

    expected = session.get(CSRF_SESSION_KEY)
    if not expected:
        generate_csrf_token()  # so the user gets a token on retry
        return _reject()

    body = request.get_json(silent=True) or {}
    candidate = (
        request.form.get("csrf_token")
        or body.get("csrf_token")
        or request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
    )
    if not candidate or not hmac.compare_digest(str(candidate), str(expected)):
        return _reject()
    return None


def _reject():
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Your session expired — please reload and try again."}), 400
    flash("Your session expired — please try again.", "error")
    return redirect(request.referrer or url_for("main.index"))
