"""
Account Settings (privacy floor): data export + account deletion.

- GET  /settings              -- account management page
- GET  /api/account/export    -- full data export as a downloadable JSON file
- POST /api/account/delete    -- permanent account deletion (needs the user
                                 to type DELETE to confirm; CSRF-protected
                                 like every other state-changing route)
"""
import io
import json

from flask import Blueprint, current_app, jsonify, render_template, request

from auth_utils import current_user, login_required, logout_user
from database.db import delete_user, export_user_data, get_referral_stats, update_country_code
from ml.crisis_resources import COUNTRY_LABELS

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/settings")
@login_required
def settings_page():
    user = current_user()
    try:
        referral = get_referral_stats(user["id"])
    except Exception:
        referral = {"referral_code": None, "total_referred": 0, "referred_users": []}
    return render_template("settings.html", user=user, referral=referral,
                           country_labels=COUNTRY_LABELS)


@settings_bp.route("/api/account/country", methods=["POST"])
@login_required
def update_country():
    """Set the user's region for crisis-resource localization. Only known
    ISO codes are accepted; anything else clears the value (which falls
    back to directory-only resources, never a wrong phone number)."""
    data = request.get_json(silent=True) or {}
    code = str(data.get("country_code") or "").strip().lower()
    if code and code not in COUNTRY_LABELS:
        return jsonify({"ok": False, "error": "Unknown country code."}), 400
    user = update_country_code(current_user()["id"], code or None)
    return jsonify({"ok": True, "country_code": user["country_code"] or ""})


@settings_bp.route("/api/account/export")
@login_required
def export_account():
    data = export_user_data(current_user()["id"])
    if data is None:
        return jsonify({"ok": False, "error": "Account not found."}), 404
    payload = json.dumps(data, indent=2, default=str).encode("utf-8")
    return current_app.response_class(
        payload,
        mimetype="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="kivora-my-data.json"',
            "Content-Type": "application/json; charset=utf-8",
        },
    )


@settings_bp.route("/api/account/delete", methods=["POST"])
@login_required
def delete_account():
    confirm = (request.get_json(silent=True) or {}).get("confirm", "") or request.form.get("confirm", "")
    if confirm != "DELETE":
        return jsonify({"ok": False, "error": "Type DELETE to confirm account deletion."}), 400

    user = current_user()
    if not delete_user(user["id"]):
        return jsonify({"ok": False, "error": "Account not found."}), 404
    logout_user()  # clear the session cookie for the now-deleted account
    return jsonify({"ok": True})
