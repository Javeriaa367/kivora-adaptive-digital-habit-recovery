from flask import Blueprint, jsonify, render_template, request, session

from auth_utils import current_user, login_required
from ml.recovery_plans import (
    PLAN_LIBRARY,
    ActivityError,
    complete_ai_conversation_activity,
    complete_assessment_activity,
    complete_breathing_activity,
    complete_checkin_activity,
    complete_habit_activity,
    complete_journal_activity,
    complete_progress_review_activity,
    complete_quiz_activity,
    complete_reflection_activity,
    complete_timer_activity,
    get_activity,
    get_assessment_defaults,
    get_history,
    get_or_create_active_plan,
    get_progress_review,
    get_quiz_template,
    get_reflection_template,
    skip_activity,
    start_activity,
    start_plan,
    toggle_task,
)

recovery_bp = Blueprint("recovery", __name__)


def _activity_error_response(e: ActivityError):
    return jsonify({"ok": False, "error": str(e)}), e.status


@recovery_bp.route("/recovery")
@login_required
def recovery_page():
    user_id = current_user()["id"]
    plan = get_or_create_active_plan(user_id)
    history = get_history(user_id)
    return render_template(
        "recovery.html", plan=plan, history=history,
        plan_library=PLAN_LIBRARY, plan_types=list(PLAN_LIBRARY.keys()),
    )


@recovery_bp.route("/api/recovery/active")
@login_required
def api_active_plan():
    plan = get_or_create_active_plan(current_user()["id"])
    return jsonify({"ok": True, "plan": plan})


@recovery_bp.route("/api/recovery/tasks/<int:task_id>/toggle", methods=["POST"])
@login_required
def api_toggle_task(task_id):
    user_id = current_user()["id"]
    data = request.get_json(silent=True) or {}
    plan_id = data.get("plan_id")
    completed = bool(data.get("completed", True))
    if not plan_id:
        return jsonify({"ok": False, "error": "plan_id is required"}), 400
    try:
        plan = toggle_task(user_id, int(plan_id), task_id, completed)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    return jsonify({"ok": True, "plan": plan})


@recovery_bp.route("/api/recovery/start", methods=["POST"])
@login_required
def api_start_plan():
    user_id = current_user()["id"]
    data = request.get_json(silent=True) or {}
    plan_type = (data.get("plan_type") or "").strip()
    if plan_type not in PLAN_LIBRARY:
        return jsonify({"ok": False, "error": "Unknown plan type."}), 400
    plan = start_plan(user_id, plan_type)
    return jsonify({"ok": True, "plan": plan})


# ==========================================================================
# ACTIVITY ENGINE ROUTES
#
# Every route below identifies the activity purely by task_id and the
# logged-in session user -- ownership is re-verified server-side on every
# call (see get_recovery_task_for_user / ml.recovery_plans._load_task).
# Nothing here trusts a plan_id, activity_type, or completion flag sent
# by the client.
# ==========================================================================

@recovery_bp.route("/api/recovery/activities/<int:task_id>")
@login_required
def api_get_activity(task_id):
    try:
        activity = get_activity(current_user()["id"], task_id)
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({
        "ok": True, "activity": activity,
        "reflection_template": get_reflection_template(),
        "quiz_template": get_quiz_template(),
        "assessment_defaults": get_assessment_defaults(),
    })


@recovery_bp.route("/api/recovery/activities/<int:task_id>/start", methods=["POST"])
@login_required
def api_start_activity(task_id):
    try:
        activity = start_activity(current_user()["id"], task_id)
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@recovery_bp.route("/api/recovery/activities/<int:task_id>/skip", methods=["POST"])
@login_required
def api_skip_activity(task_id):
    try:
        activity = skip_activity(current_user()["id"], task_id)
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@recovery_bp.route("/api/recovery/activities/<int:task_id>/journal", methods=["POST"])
@login_required
def api_activity_journal(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_journal_activity(current_user()["id"], task_id, {
            "worry": data.get("worry", ""), "control": data.get("control", ""),
        })
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@recovery_bp.route("/api/recovery/activities/<int:task_id>/reflection", methods=["POST"])
@login_required
def api_activity_reflection(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_reflection_activity(current_user()["id"], task_id, data.get("responses") or [])
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@recovery_bp.route("/api/recovery/activities/<int:task_id>/breathing", methods=["POST"])
@login_required
def api_activity_breathing(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_breathing_activity(
            current_user()["id"], task_id,
            data.get("rounds_completed", 0), data.get("duration_seconds", 0), data.get("mood_after"),
        )
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@recovery_bp.route("/api/recovery/activities/<int:task_id>/timer", methods=["POST"])
@login_required
def api_activity_timer(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_timer_activity(
            current_user()["id"], task_id, data.get("planned_seconds", 600), data.get("mood_after"),
        )
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@recovery_bp.route("/api/recovery/activities/<int:task_id>/checkin", methods=["POST"])
@login_required
def api_activity_checkin(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_checkin_activity(
            current_user()["id"], task_id, data.get("anxiety"), data.get("energy"), data.get("mood"),
        )
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@recovery_bp.route("/api/recovery/activities/<int:task_id>/habit", methods=["POST"])
@login_required
def api_activity_habit(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_habit_activity(current_user()["id"], task_id, data.get("habit_name"))
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@recovery_bp.route("/api/recovery/activities/<int:task_id>/ai-conversation", methods=["POST"])
@login_required
def api_activity_ai_conversation(task_id):
    # turn_count comes from the server-side session history the companion
    # blueprint itself maintains -- never from the request body -- so
    # completion can't be claimed without a real exchange happening.
    turn_count = len(session.get("companion_history", []))
    try:
        activity = complete_ai_conversation_activity(current_user()["id"], task_id, turn_count)
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@recovery_bp.route("/api/recovery/activities/<int:task_id>/quiz", methods=["POST"])
@login_required
def api_activity_quiz(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_quiz_activity(current_user()["id"], task_id, data.get("responses") or [])
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@recovery_bp.route("/api/recovery/activities/<int:task_id>/assessment", methods=["POST"])
@login_required
def api_activity_assessment(task_id):
    user = current_user()
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_assessment_activity(user["id"], task_id, data, user["plan"])
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@recovery_bp.route("/api/recovery/plans/<int:plan_id>/progress-review")
@login_required
def api_progress_review(plan_id):
    try:
        review = get_progress_review(current_user()["id"], plan_id)
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "review": review})


@recovery_bp.route("/api/recovery/activities/<int:task_id>/progress-review", methods=["POST"])
@login_required
def api_activity_progress_review(task_id):
    try:
        activity = complete_progress_review_activity(current_user()["id"], task_id)
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})
