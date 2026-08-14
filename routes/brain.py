"""
Adaptive Brain Exercises -- API.

Three read/write endpoints over the engine in ml/brain_exercises.py. Like
the activity engine, every call re-derives the logged-in user server-side
(a user_id is never taken from the request), and exercise answers are
stored server-side so the client only ever sees redacted prompts.
"""
from flask import Blueprint, jsonify, request

from auth_utils import current_user, login_required
from ml.brain_exercises import (
    BrainError,
    get_or_create_today_exercise,
    get_progress,
    submit_attempt,
)
from ml.recovery_plans import get_or_create_active_plan

brain_bp = Blueprint("brain", __name__)


def _brain_error_response(e: BrainError):
    return jsonify({"ok": False, "error": str(e)}), e.status


def _active_plan(user_id: int):
    """Same behavior as the recovery page: an active plan exists (or is
    auto-created), and the brain layer follows the same plan."""
    return get_or_create_active_plan(user_id)


@brain_bp.route("/api/brain/today")
@login_required
def api_brain_today():
    user = current_user()
    plan = _active_plan(user["id"])
    day_number = request.args.get("day_number", type=int) or plan["progress"]["current_day"]
    try:
        exercise = get_or_create_today_exercise(user["id"], plan["id"], day_number)
    except BrainError as e:
        return _brain_error_response(e)
    return jsonify({"ok": True, "exercise": exercise})


@brain_bp.route("/api/brain/attempts/<int:attempt_id>/submit", methods=["POST"])
@login_required
def api_brain_submit(attempt_id):
    user = current_user()
    data = request.get_json(silent=True) or {}
    try:
        result = submit_attempt(user["id"], attempt_id, data.get("response"))
    except BrainError as e:
        return _brain_error_response(e)
    return jsonify({"ok": True, "result": result})


@brain_bp.route("/api/brain/progress")
@login_required
def api_brain_progress():
    user = current_user()
    plan = _active_plan(user["id"])
    progress = get_progress(user["id"], plan["id"])
    return jsonify({
        "ok": True,
        "progress": progress,
        "plan_id": plan["id"],
        "plan_type": plan["plan_type"],
    })
