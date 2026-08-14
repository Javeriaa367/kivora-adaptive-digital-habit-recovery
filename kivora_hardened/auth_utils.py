"""
Minimal session-based auth: no Flask-Login dependency. `current_user()`
reads the logged-in user (or None) from the Flask session + DB;
`login_required` protects routes; `login_user`/`logout_user` manage the
session cookie. Session cookie itself is signed by Flask's SECRET_KEY,
so this is standard Flask session security (not roll-your-own crypto).
"""
from functools import wraps

from flask import flash, g, redirect, request, session, url_for

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


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login", next=request.path))
        if not user["is_admin"]:
            flash("Admin access required.", "error")
            return redirect(url_for("main.dashboard"))
        return view(*args, **kwargs)
    return wrapped
