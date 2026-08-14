"""
Minimal session-based auth: no Flask-Login dependency. `current_user()`
reads the logged-in user (or None) from the Flask session + DB;
`login_required` protects routes; `login_user`/`logout_user` manage the
session cookie. Session cookie itself is signed by Flask's SECRET_KEY,
so this is standard Flask session security (not roll-your-own crypto).
"""
from functools import wraps

from flask import flash, g, redirect, request, session, url_for, jsonify

from database.db import get_user_by_id


def login_user(user_row):
    session.clear()
    session["user_id"] = user_row["id"]
    session.permanent = True


def logout_user():
    session.clear()


def current_user():
    if "user" not in g:
        user_id = session.get("user_id")
        g.user = get_user_by_id(user_id) if user_id else None
    return g.user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


# ---- Role-based access control (server-side enforcement) ------------------
# Roles live in the users.role column ('user' / 'admin' / 'super_admin').
# super_admin is the founder/owner tier and inherits every 'admin'
# capability. These decorators verify the role on *every* request, so
# hiding UI buttons is never the security boundary -- the backend is.

ROLE_RANK = {"user": 0, "admin": 1, "super_admin": 2}


def user_role(user) -> str:
    """Resolve a user row's role, with legacy is_admin fallback so accounts
    created before the role column existed keep working."""
    if user is None:
        return ""
    keys = user.keys() if hasattr(user, "keys") else set()
    role = user["role"] if "role" in keys and user["role"] else ""
    if not role:
        role = "admin" if ("is_admin" in keys and user["is_admin"]) else "user"
    return role


def is_suspended(user) -> bool:
    if user is None:
        return False
    keys = user.keys() if hasattr(user, "keys") else set()
    return "account_status" in keys and user["account_status"] == "suspended"


def _unauthenticated():
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"ok": False, "error": "Authentication required."}), 401
    flash("Please log in to continue.", "error")
    return redirect(url_for("auth.login", next=request.path))


def _forbidden(message: str):
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"ok": False, "error": message}), 403
    flash(message, "error")
    return redirect(url_for("main.dashboard"))


def admin_required(view):
    """Staff tier: role 'admin' or 'super_admin' (legacy is_admin honored)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return _unauthenticated()
        if is_suspended(user):
            return _forbidden("This account has been suspended.")
        if ROLE_RANK.get(user_role(user), 0) < ROLE_RANK["admin"]:
            return _forbidden("Admin access required.")
        return view(*args, **kwargs)
    return wrapped


def super_admin_required(view):
    """Founder/owner tier: role exactly 'super_admin' (highest permission
    level). Used for role management and other owner-only operations."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return _unauthenticated()
        if is_suspended(user):
            return _forbidden("This account has been suspended.")
        if ROLE_RANK.get(user_role(user), 0) < ROLE_RANK["super_admin"]:
            return _forbidden("Super admin access required.")
        return view(*args, **kwargs)
    return wrapped


def role_required(*roles):
    """Generic factory: allow only the given roles (any of them)."""
    allowed = {r for r in roles if r in ROLE_RANK}

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return _unauthenticated()
            if is_suspended(user):
                return _forbidden("This account has been suspended.")
            if user_role(user) not in allowed:
                return _forbidden("Access denied.")
            return view(*args, **kwargs)
        return wrapped
    return decorator
