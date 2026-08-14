import json

from flask import Blueprint, jsonify, render_template, request, session

from auth_utils import ROLE_RANK, current_user, login_required, user_role
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


def _humanize_mechanism(mechanism: str | None) -> str:
    mapping = {
        "automatic_checking": "automatic checking",
        "notification_triggered": "notification-driven checking",
        "boredom": "boredom-driven scrolling",
        "cant_stop_once_started": "difficulty stopping once you start",
        "fomo": "fear of missing out",
        "social_comparison": "social comparison",
        "stress_triggered": "stress-triggered checking",
        "emotional_avoidance": "emotional avoidance",
        "sleep_disruption": "sleep disruption",
        "procrastination": "study/work avoidance",
        "loneliness_driven": "loneliness-driven checking",
    }
    return mapping.get(mechanism, "your current pattern") if mechanism else "your current pattern"


def _workload_label(plan: dict) -> str:
    stage = int(plan.get("stage") or 1)
    if stage >= 3:
        return "High"
    if stage == 2:
        return "Moderate"
    return "Low"


def _plan_summary(plan: dict) -> dict:
    mechanism = plan.get("mechanism")
    stage = int(plan.get("stage") or 1)
    completion = plan.get("progress", {}).get("percent", 0)
    next_task = None
    for task in plan.get("tasks") or []:
        if task.get("state") != "completed":
            next_task = task
            break
    next_intervention = next_task.get("task_text") if next_task else "Your next recovery step is almost ready."
    return {
        "mechanism": _humanize_mechanism(mechanism),
        "stage": stage,
        "workload": _workload_label(plan),
        "progress_percent": completion,
        "reason": plan.get("recommend_reason") or plan.get("selection_reason") or "KIVORA is still learning your pattern.",
        "next_intervention": next_intervention,
    }


def _analytics_summary(plan: dict, history: list[dict]) -> dict:
    outcomes = []
    for item in history:
        raw = item.get("outcome_json")
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            outcomes.append(parsed)
    if plan and plan.get("outcome_json"):
        try:
            parsed = json.loads(plan.get("outcome_json"))
        except (TypeError, ValueError):
            parsed = {}
        if isinstance(parsed, dict):
            outcomes.append(parsed)

    completion_rates = [float(o.get("completion_rate", 0)) for o in outcomes if isinstance(o.get("completion_rate"), (int, float))]
    usefulness_vals = [float(o.get("avg_usefulness", 0)) for o in outcomes if isinstance(o.get("avg_usefulness"), (int, float))]
    avg_completion = round(sum(completion_rates) / len(completion_rates), 2) if completion_rates else 0.0
    avg_usefulness = round(sum(usefulness_vals) / len(usefulness_vals), 2) if usefulness_vals else 0.0
    plan_count = max(len(history), 1)
    trend = "Improving" if avg_completion >= 0.7 else "Needs adjustment" if avg_completion >= 0.4 else "Early stage"
    confidence = "High" if getattr(plan, "get", lambda *_: None)("mechanism") else "Learning"
    return {
        "completion_rate": avg_completion,
        "usefulness_score": avg_usefulness,
        "plan_count": plan_count,
        "trend": trend,
        "confidence": confidence,
    }


def _adaptation_timeline(history: list[dict]) -> list[dict]:
    events = []
    for item in history[:5]:
        outcome = {}
        raw = item.get("outcome_json")
        if raw:
            try:
                outcome = json.loads(raw)
            except (TypeError, ValueError):
                outcome = {}
        avg_use = outcome.get("avg_usefulness")
        completion = outcome.get("completion_rate")
        if avg_use is not None:
            if avg_use >= 4:
                detail = "The previous plan worked well; KIVORA kept the recovery approach steady."
            elif avg_use <= 2:
                detail = "The last plan felt difficult, so KIVORA reduced the burden and simplified the approach."
            else:
                detail = "KIVORA adjusted the plan based on your recent response and workload."
        elif completion is not None:
            detail = f"Your recent plan reached {completion * 100:.0f}% completion, which informs the next recovery step."
        else:
            detail = "KIVORA is still learning from your recent recovery pattern."
        events.append({
            "title": item.get("title") or "Recovery plan",
            "status": item.get("status") or "active",
            "detail": detail,
            "date": (item.get("started_at") or "")[:10],
        })
    return events


@recovery_bp.route("/recovery")
@login_required
def recovery_page():
    user = current_user()
    user_id = user["id"]
    plan = get_or_create_active_plan(user_id)
    history = get_history(user_id)
    summary = _plan_summary(plan)
    summary["analytics"] = _analytics_summary(plan, history)
    adaptation_timeline = _adaptation_timeline(history)
    is_admin = ROLE_RANK.get(user_role(user), 0) >= ROLE_RANK["admin"]
    return render_template(
        "recovery.html", plan=plan, history=history, summary=summary,
        adaptation_timeline=adaptation_timeline,
        plan_library=PLAN_LIBRARY, plan_types=list(PLAN_LIBRARY.keys()),
        is_admin=is_admin,
    )


@recovery_bp.route("/api/recovery/active")
@login_required
def api_active_plan():
    user_id = current_user()["id"]
    plan = get_or_create_active_plan(user_id)
    history = get_history(user_id)
    summary = _plan_summary(plan)
    summary["analytics"] = _analytics_summary(plan, history)
    return jsonify({
        "ok": True,
        "plan": plan,
        "summary": summary,
        "adaptation_timeline": _adaptation_timeline(history),
    })


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
            data.get("usefulness"),
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
