"""Interactive Demo Mode -- admin-only sandbox.

Renders a fully interactive copy of the recovery plan at
/admin/recovery/demo and runs every activity through the REAL activity
engine (ml/recovery_plans.py) and brain engine (ml/brain_exercises.py),
but against an isolated throwaway "demo user" account instead of the
admin's own account (see database/db.py get_or_create_demo_user).

Because every engine function is scoped by user_id, performing activities
here can never touch the real admin's recovery state, journal, habits,
memory, predictions or analytics -- those are excluded from admin
aggregates via the demo_owner_user_id column. "Reset Demo" deletes the
demo user (all demo rows cascade), so a fresh judge demo starts clean.

Every route resolves the demo user server-side from the logged-in admin's
session (never from the request) and is gated by @admin_required. The demo
page is served by the same recovery.js/brain.js used by players, with
window.KIVORA_DEMO_BASE set so their hardcoded /api/recovery/... and
/api/brain/... calls resolve to the admin-prefixed mirrors below.
"""
from flask import Blueprint, jsonify, render_template, request, session

from auth_utils import admin_required, current_user
from database.db import (
    delete_demo_user,
    get_active_recovery_plan,
    get_demo_user,
    get_or_create_demo_user,
)
from ml.brain_exercises import (
    BrainError,
    get_or_create_today_exercise,
    get_progress,
    submit_attempt,
)
from ml.recovery_plans import (
    ActivityError,
    admin_plan_preview,
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
    get_or_create_active_plan,
    get_progress_review,
    get_quiz_template,
    get_reflection_template,
    skip_activity,
    start_activity,
    start_plan,
)

demo_bp = Blueprint("recovery_demo", __name__)

DEMO_PAGE = "/admin/recovery/demo"
DEMO_API = f"{DEMO_PAGE}/api"


def _activity_error_response(e: ActivityError):
    return jsonify({"ok": False, "error": str(e)}), e.status


def _brain_error_response(e: BrainError):
    return jsonify({"ok": False, "error": str(e)}), e.status


def _demo_plan_type(admin_user_id: int) -> str:
    """Mirror the admin's own active plan so a judge previews and then
    experiences the same plan; fall back to the anxiety plan when the
    admin has none yet."""
    preview = admin_plan_preview(admin_user_id)
    if preview and preview.get("plan_type"):
        return preview["plan_type"]
    return "anxiety"


def _ensure_demo_plan() -> dict:
    """The demo user's active plan (created once on first demo visit with
    the admin's plan type). Scoped entirely to the demo user."""
    admin_id = current_user()["id"]
    demo_user = get_or_create_demo_user(admin_id)
    if get_active_recovery_plan(demo_user["id"]) is None:
        start_plan(demo_user["id"], _demo_plan_type(admin_id))
    return get_or_create_active_plan(demo_user["id"])


def _demo_user_id() -> int:
    return get_or_create_demo_user(current_user()["id"])["id"]


@demo_bp.route(DEMO_PAGE)
@admin_required
def demo_page():
    """The interactive demo page: same rendering as the player recovery
    page, but every day is unlocked and JS is pointed at the demo API."""
    plan = _ensure_demo_plan()
    return render_template("recovery_demo.html", plan=plan)


@demo_bp.route(f"{DEMO_PAGE}/state")
@admin_required
def demo_state():
    demo_user = get_or_create_demo_user(current_user()["id"])
    plan = _ensure_demo_plan()
    return jsonify({"ok": True, "plan": plan, "demo_user_id": demo_user["id"]})


@demo_bp.route(f"{DEMO_PAGE}/reset", methods=["POST"])
@admin_required
def demo_reset():
    """Wipe the demo sandbox (deletes the demo user; all demo rows
    cascade). The next demo page visit rebuilds a fresh plan."""
    delete_demo_user(current_user()["id"])
    return jsonify({"ok": True})


# ---- Activity engine mirrors (see routes/recovery.py) ---------------------
# Identical request/response shapes; user_id is always the demo user.

@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>")
@admin_required
def demo_get_activity(task_id):
    try:
        activity = get_activity(_demo_user_id(), task_id)
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({
        "ok": True, "activity": activity,
        "reflection_template": get_reflection_template(),
        "quiz_template": get_quiz_template(),
        "assessment_defaults": get_assessment_defaults(),
    })


@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>/start", methods=["POST"])
@admin_required
def demo_start_activity(task_id):
    try:
        activity = start_activity(_demo_user_id(), task_id)
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>/skip", methods=["POST"])
@admin_required
def demo_skip_activity(task_id):
    try:
        activity = skip_activity(_demo_user_id(), task_id)
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>/journal", methods=["POST"])
@admin_required
def demo_activity_journal(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_journal_activity(_demo_user_id(), task_id, {
            "worry": data.get("worry", ""), "control": data.get("control", ""),
        })
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>/reflection", methods=["POST"])
@admin_required
def demo_activity_reflection(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_reflection_activity(_demo_user_id(), task_id, data.get("responses") or [])
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>/breathing", methods=["POST"])
@admin_required
def demo_activity_breathing(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_breathing_activity(
            _demo_user_id(), task_id,
            data.get("rounds_completed", 0), data.get("duration_seconds", 0), data.get("mood_after"),
        )
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>/timer", methods=["POST"])
@admin_required
def demo_activity_timer(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_timer_activity(
            _demo_user_id(), task_id, data.get("planned_seconds", 600), data.get("mood_after"),
        )
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>/checkin", methods=["POST"])
@admin_required
def demo_activity_checkin(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_checkin_activity(
            _demo_user_id(), task_id, data.get("anxiety"), data.get("energy"), data.get("mood"),
            data.get("usefulness"),
        )
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>/habit", methods=["POST"])
@admin_required
def demo_activity_habit(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_habit_activity(_demo_user_id(), task_id, data.get("habit_name"))
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>/ai-conversation", methods=["POST"])
@admin_required
def demo_activity_ai_conversation(task_id):
    # Same server-side session turn-count as the player route: completion
    # can't be claimed without a real companion exchange happening first.
    turn_count = len(session.get("companion_history", []))
    try:
        activity = complete_ai_conversation_activity(_demo_user_id(), task_id, turn_count)
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>/quiz", methods=["POST"])
@admin_required
def demo_activity_quiz(task_id):
    data = request.get_json(silent=True) or {}
    try:
        activity = complete_quiz_activity(_demo_user_id(), task_id, data.get("responses") or [])
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>/assessment", methods=["POST"])
@admin_required
def demo_activity_assessment(task_id):
    demo_user = get_or_create_demo_user(current_user()["id"])
    data = request.get_json(silent=True) or {}
    try:
        # demo_user.plan == 'premium', so the free-plan daily assessment
        # limit can never block a judge mid-demo.
        activity = complete_assessment_activity(demo_user["id"], task_id, data, demo_user["plan"])
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


@demo_bp.route(f"{DEMO_API}/recovery/plans/<int:plan_id>/progress-review")
@admin_required
def demo_progress_review(plan_id):
    try:
        review = get_progress_review(_demo_user_id(), plan_id)
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "review": review})


@demo_bp.route(f"{DEMO_API}/recovery/activities/<int:task_id>/progress-review", methods=["POST"])
@admin_required
def demo_activity_progress_review(task_id):
    try:
        activity = complete_progress_review_activity(_demo_user_id(), task_id)
    except ActivityError as e:
        return _activity_error_response(e)
    return jsonify({"ok": True, "activity": activity})


# ---- Brain exercise mirrors (see routes/brain.py) --------------------------
# The one demo difference: every day is marked available, matching the
# "all days unlocked" rule of the demo page.

@demo_bp.route(f"{DEMO_API}/brain/today")
@admin_required
def demo_brain_today():
    demo_user = get_or_create_demo_user(current_user()["id"])
    plan = _ensure_demo_plan()
    day_number = request.args.get("day_number", type=int) or 1
    try:
        exercise = get_or_create_today_exercise(demo_user["id"], plan["id"], day_number)
    except BrainError as e:
        return _brain_error_response(e)
    return jsonify({"ok": True, "exercise": exercise})


@demo_bp.route(f"{DEMO_API}/brain/attempts/<int:attempt_id>/submit", methods=["POST"])
@admin_required
def demo_brain_submit(attempt_id):
    demo_user = get_or_create_demo_user(current_user()["id"])
    data = request.get_json(silent=True) or {}
    try:
        result = submit_attempt(demo_user["id"], attempt_id, data.get("response"))
    except BrainError as e:
        return _brain_error_response(e)
    return jsonify({"ok": True, "result": result})


@demo_bp.route(f"{DEMO_API}/brain/progress")
@admin_required
def demo_brain_progress():
    demo_user = get_or_create_demo_user(current_user()["id"])
    plan = _ensure_demo_plan()
    progress = get_progress(demo_user["id"], plan["id"])
    for day in progress["days"].values():
        day["available"] = True
    return jsonify({
        "ok": True,
        "progress": progress,
        "plan_id": plan["id"],
        "plan_type": plan["plan_type"],
    })
