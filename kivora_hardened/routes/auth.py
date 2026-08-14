"""
Auth routes: email/password signup+login, plus Google OAuth login.

Google OAuth setup (untested here -- no client ID/secret in this sandbox,
and no network to verify the redirect flow live. Code follows Authlib's
standard Flask pattern, which is well-established, but test it yourself
before shipping):

    pip install Authlib

    export GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
    export GOOGLE_CLIENT_SECRET="your-client-secret"

Get these from https://console.cloud.google.com/apis/credentials --
create an OAuth 2.0 Client ID, add http://localhost:5000/auth/google/callback
(and your real domain's equivalent) as an authorized redirect URI.
"""
import os
import re
import secrets
import hashlib
from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from auth_utils import current_user, login_required, login_user, logout_user
from database.db import (
    REFERRAL_PREMIUM_DAYS, create_password_reset_token, create_user,
    get_or_create_google_user, get_user_by_email, consume_reset_token,
    get_valid_reset_token, verify_password,
)
from ml.mailer import send_password_reset_email
from ml.crisis_resources import SUPPORTED_COUNTRIES

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESET_TOKEN_TTL_MINUTES = 30

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

_oauth = None


def _get_oauth(app):
    global _oauth
    if _oauth is None:
        from authlib.integrations.flask_client import OAuth
        _oauth = OAuth(app)
        _oauth.register(
            name="google",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    return _oauth


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user():
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        referral_code = request.form.get("referral_code", "").strip() or None
        consent_given = request.form.get("consent") in ("on", "1", "true", "yes", "True")
        # Region drives which crisis helplines the app shows; only accept
        # known codes so an invalid value can never persist (unknown ->
        # directory links only, per ml/crisis_resources.py).
        country_code = request.form.get("country", "").strip().lower()
        if country_code not in dict(SUPPORTED_COUNTRIES):
            country_code = None

        errors = []
        if len(name) < 2:
            errors.append("Name must be at least 2 characters.")
        if not EMAIL_RE.match(email):
            errors.append("Enter a valid email address.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if not consent_given:
            errors.append("Please agree to the Privacy Policy to create an account.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("auth/signup.html", name=name, email=email,
                                   supported_countries=SUPPORTED_COUNTRIES, country=country_code or "")

        if get_user_by_email(email) is not None:
            flash("An account with that email already exists.", "error")
            return render_template("auth/signup.html", name=name, email=email,
                                   supported_countries=SUPPORTED_COUNTRIES, country=country_code or "")

        user = create_user(name, email, password, referred_by_code=referral_code,
                           consent_given=consent_given, country_code=country_code)
        login_user(user)
        if user.get("referral_rewarded"):
            flash(f"Welcome, {user['name']}! You and your friend each got "
                  f"{REFERRAL_PREMIUM_DAYS} days of Premium free.", "success")
        else:
            flash(f"Welcome, {user['name']} — your account is ready.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/signup.html", referral_code=request.args.get("ref", ""),
                           supported_countries=SUPPORTED_COUNTRIES, country="")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = get_user_by_email(email)
        if user is None or not verify_password(user, password):
            flash("Incorrect email or password.", "error")
            return render_template("auth/login.html", email=email)

        login_user(user)
        flash(f"Welcome back, {user['name']}.", "success")
        next_url = request.args.get("next")
        return redirect(next_url or url_for("main.dashboard"))

    return render_template("auth/login.html", google_enabled=bool(GOOGLE_CLIENT_ID))


@auth_bp.route("/auth/google/login")
def google_login():
    if not GOOGLE_CLIENT_ID:
        flash("Google login isn't configured yet.", "error")
        return redirect(url_for("auth.login"))
    from flask import current_app
    oauth = _get_oauth(current_app)
    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/auth/google/callback")
def google_callback():
    if not GOOGLE_CLIENT_ID:
        return redirect(url_for("auth.login"))
    from flask import current_app
    oauth = _get_oauth(current_app)
    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo") or oauth.google.parse_id_token(token)

    user = get_or_create_google_user(
        google_sub=userinfo["sub"], name=userinfo.get("name", "Google User"), email=userinfo["email"],
    )
    login_user(user)
    flash(f"Welcome, {user['name']}.", "success")
    return redirect(url_for("main.dashboard"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You've been logged out.", "success")
    return redirect(url_for("auth.login"))


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


PASSWORD_STRENGTH_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = get_user_by_email(email)

        # Always show the same message whether or not the account exists --
        # don't let this endpoint leak which emails are registered.
        if user is not None and user["password_hash"] is not None:
            raw_token = secrets.token_urlsafe(32)
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)).isoformat()
            create_password_reset_token(user["id"], _hash_token(raw_token), expires_at)
            reset_url = url_for("auth.reset_password", token=raw_token, _external=True)
            send_password_reset_email(user["email"], reset_url)

        flash("If that email is registered, a reset link has been sent.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    token_row = get_valid_reset_token(_hash_token(token))
    if token_row is None:
        flash("This reset link is invalid or has expired. Request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if not PASSWORD_STRENGTH_RE.match(password):
            errors.append("Password must be at least 8 characters and include a letter and a number.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("auth/reset_password.html", token=token)

        consume_reset_token(_hash_token(token), password)
        flash("Password updated — log in with your new password.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)
