from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template

from auth_utils import current_user, login_required
from database.db import get_latest_risk_snapshot_time
from ml.risk_engine import CATEGORIES, compute_risk_profile, get_risk_trend

risk_bp = Blueprint("risk", __name__)

# Avoid writing a fresh snapshot row on every single page view -- only
# persist once per this interval so the trend chart reflects meaningful
# time gaps, not every refresh.
MIN_SNAPSHOT_INTERVAL_HOURS = 6


def _should_persist_new_snapshot(user_id: int) -> bool:
    last = get_latest_risk_snapshot_time(user_id)
    if last is None:
        return True
    hours_since = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
    return hours_since >= MIN_SNAPSHOT_INTERVAL_HOURS


@risk_bp.route("/risk")
@login_required
def risk_page():
    user_id = current_user()["id"]
    profile = compute_risk_profile(user_id, persist=_should_persist_new_snapshot(user_id))
    return render_template("risk.html", profile=profile, categories=CATEGORIES)


@risk_bp.route("/api/risk/profile")
@login_required
def api_risk_profile():
    user_id = current_user()["id"]
    profile = compute_risk_profile(user_id, persist=_should_persist_new_snapshot(user_id))
    return jsonify({"ok": True, "profile": profile})


@risk_bp.route("/api/risk/trend")
@login_required
def api_risk_trend():
    trend = get_risk_trend(current_user()["id"])
    return jsonify({"ok": True, "trend": trend})
