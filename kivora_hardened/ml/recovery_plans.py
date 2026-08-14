"""
Personalized Recovery Plans (Feature 3).

Instead of generic advice, this generates a named, dated, day-by-day plan
(7 or 14 days) built from a small library of grounded templates, then:

  - picks WHICH template fits this user right now from real signals
    (their current risk profile from ml/risk_engine.py, plus explicit
    "exam" stressors already in long-term memory) -- never a random pick
  - optionally asks Gemini to reword each day's task using that same
    context (memory + the reason the plan was recommended), constrained
    to the exact day count and the template's intent -- never invents new
    days, never drops the deterministic fallback if Gemini is unavailable
    or returns something malformed
  - tracks completion per day, and auto-completes a day's task when the
    user's own logged activity already satisfies it (a journal entry on
    a "journal" day, a habit check-in on a "habit" day) -- never claims
    progress that isn't backed by a real stored row
  - regenerates automatically when a plan's duration elapses, using the
    risk profile AT THAT TIME (so the next plan reflects what actually
    changed, not what was true 7-14 days ago)

Same "Gemini if configured, deterministic fallback if not" pattern as the
rest of ml/*.py.
"""
import json
from datetime import datetime, timedelta, timezone

from database.db import (
    complete_recovery_task,
    create_recovery_plan,
    get_active_memory_facts,
    get_active_recovery_plan,
    get_habit_checkin_dates_between,
    get_journal_dates_between,
    get_recent_activity_results,
    get_recovery_plan,
    get_recovery_plan_history,
    get_recovery_plan_tasks,
    get_recovery_task_for_user,
    set_recovery_plan_status,
    set_recovery_task_completed,
    skip_recovery_task,
    start_recovery_task,
)
from ml.chatbot import GEMINI_API_KEY, GEMINI_MODEL, get_gemini_client

# Each template: duration, the risk categories it addresses (for
# recommendation), and one (task_text, auto_signal) pair per day.
# auto_signal is "journal", "habit", or None -- used only to auto-check a
# day off when the user's own logged activity already covers it.
# Each template: duration, the risk categories it addresses (for
# recommendation), and "days" -- a list of length duration_days, one entry
# per day, each entry itself a list of one-or-more activities for that day:
# {"text": ..., "auto_signal": "journal"|"habit"|None, "activity_type": ...}.
# A day can hold several activities (e.g. a check-in, a breathing session,
# and a reflection all on Day 1) -- that's the "journey" the Activity
# Engine renders, not a single checkbox per day.
PLAN_LIBRARY = {
    "anxiety": {
        "title": "7-Day Anxiety Recovery",
        "duration_days": 7,
        "risk_categories": ["anxiety"],
        "days": [
            [  # Day 1
                {"text": "Check in: how anxious do you feel right now?", "auto_signal": None, "activity_type": "checkin"},
                {"text": "Try a 4-7-8 breathing round (inhale 4s, hold 7s, exhale 8s) x4 when you feel tense.", "auto_signal": None, "activity_type": "breathing"},
                {"text": "Reflect on what's actually within your control today.", "auto_signal": None, "activity_type": "reflection"},
            ],
            [  # Day 2
                {"text": "Identify one anxious thought and check whether it's a fact or a prediction.", "auto_signal": None, "activity_type": "reflection"},
                {"text": "Try another breathing round when the thought comes back.", "auto_signal": None, "activity_type": "breathing"},
                {"text": "Journal about what's actually in your control today vs. what isn't.", "auto_signal": "journal", "activity_type": "journal"},
            ],
            [  # Day 3
                {"text": "Do one grounding exercise (5 things you see, 4 you hear, 3 you feel).", "auto_signal": None, "activity_type": "reflection"},
                {"text": "Reflect on what's been triggering this anxiety lately.", "auto_signal": None, "activity_type": "reflection"},
                {"text": "Take a 10-minute screen-free break.", "auto_signal": "habit", "activity_type": "timer"},
            ],
            [  # Day 4
                {"text": "Practice reframing today's anxious thought into a more balanced one.", "auto_signal": None, "activity_type": "reflection"},
                {"text": "Talk through what's making you anxious with your AI companion.", "auto_signal": None, "activity_type": "ai_conversation"},
            ],
            [  # Day 5
                {"text": "Take on a small habit challenge that supports calmer days.", "auto_signal": "habit", "activity_type": "habit"},
                {"text": "Name three things that went okay today, even small ones.", "auto_signal": "journal", "activity_type": "journal"},
            ],
            [  # Day 6
                {"text": "Try a breathing round before your day gets busy.", "auto_signal": None, "activity_type": "breathing"},
                {"text": "Do one more grounding exercise.", "auto_signal": None, "activity_type": "reflection"},
                {"text": "Check in: has your anxiety shifted at all this week?", "auto_signal": None, "activity_type": "checkin"},
            ],
            [  # Day 7
                {"text": "Final check-in for this plan.", "auto_signal": None, "activity_type": "checkin"},
                {"text": "Review your progress across the whole week.", "auto_signal": None, "activity_type": "progress_review"},
                {"text": "Reflect: has anything felt more manageable this week than last?", "auto_signal": "journal", "activity_type": "journal"},
            ],
        ],
    },
    "sleep": {
        "title": "14-Day Better Sleep Plan",
        "duration_days": 14,
        "risk_categories": ["burnout"],
        "days": [
            [{"text": "Set a fixed wind-down time tonight, 30 minutes before bed.", "auto_signal": None, "activity_type": "checkin"}],
            [{"text": "No screens for the last 20 minutes before bed tonight.", "auto_signal": None, "activity_type": "checkin"},
             {"text": "Journal any racing thoughts before bed instead of scrolling with them.", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "Keep today's caffeine to the morning only.", "auto_signal": None, "activity_type": "checkin"}],
            [{"text": "Check in on a habit that supports your sleep routine.", "auto_signal": "habit", "activity_type": "habit"}],
            [{"text": "Try 5 minutes of slow breathing before bed.", "auto_signal": None, "activity_type": "breathing"},
             {"text": "Journal how last night's sleep actually felt.", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "Get 10 minutes of daylight in the first hour after waking.", "auto_signal": None, "activity_type": "checkin"}],
            [{"text": "Keep the wind-down time going -- same time as day 1.", "auto_signal": None, "activity_type": "checkin"},
             {"text": "Reflect on how the first week felt.", "auto_signal": None, "activity_type": "reflection"}],
            [{"text": "Check in on your sleep-supporting habit again.", "auto_signal": "habit", "activity_type": "habit"}],
            [{"text": "Journal what's helped so far and what hasn't.", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "No screens for the last 20 minutes before bed again tonight.", "auto_signal": None, "activity_type": "checkin"}],
            [{"text": "Try 5 minutes of stretching or slow breathing before bed again.", "auto_signal": None, "activity_type": "breathing"}],
            [{"text": "Notice: is falling asleep feeling any different than day 1?", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "Check in on your sleep-supporting habit one more time.", "auto_signal": "habit", "activity_type": "habit"}],
            [{"text": "Review your progress across the two weeks.", "auto_signal": None, "activity_type": "progress_review"},
             {"text": "Reflect on the two weeks -- what's worth keeping as a routine?", "auto_signal": "journal", "activity_type": "journal"}],
        ],
    },
    "exam_stress": {
        "title": "Exam Stress Plan",
        "duration_days": 7,
        "risk_categories": ["burnout", "anxiety"],
        "days": [
            [{"text": "Write down everything you need to study, then pick just today's slice.", "auto_signal": "journal", "activity_type": "journal"},
             {"text": "Check in: how anxious do you feel about the exam right now?", "auto_signal": None, "activity_type": "checkin"}],
            [{"text": "Study in 25-minute focused blocks with real breaks between them.", "auto_signal": "habit", "activity_type": "timer"}],
            [{"text": "Journal one exam worry and one fact that actually helps with it.", "auto_signal": "journal", "activity_type": "journal"},
             {"text": "Try a breathing round if the worry spikes.", "auto_signal": None, "activity_type": "breathing"}],
            [{"text": "Take a full break this evening -- no studying after a set cutoff.", "auto_signal": None, "activity_type": "timer"}],
            [{"text": "Check in on your study habit again.", "auto_signal": "habit", "activity_type": "habit"}],
            [{"text": "Do a low-stakes practice run (practice questions, flashcards, teach-back).", "auto_signal": None, "activity_type": "reflection"},
             {"text": "Talk through your exam-day plan with your AI companion.", "auto_signal": None, "activity_type": "ai_conversation"}],
            [{"text": "Review your progress this week.", "auto_signal": None, "activity_type": "progress_review"},
             {"text": "Journal how prepared you feel now vs. day 1.", "auto_signal": "journal", "activity_type": "journal"}],
        ],
    },
    "digital_detox": {
        "title": "Digital Detox Plan",
        "duration_days": 7,
        "risk_categories": ["digital_addiction"],
        "days": [
            [{"text": "Check your current social-media assessment as a starting point.", "auto_signal": None, "activity_type": "assessment"},
             {"text": "Turn off non-essential notifications for the day.", "auto_signal": None, "activity_type": "checkin"}],
            [{"text": "Pick one no-phone hour today and protect it.", "auto_signal": "habit", "activity_type": "timer"},
             {"text": "Journal how it felt to not check your phone during that hour.", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "Move social apps off your home screen.", "auto_signal": None, "activity_type": "checkin"}],
            [{"text": "Try a no-phone activity you used to enjoy before bed.", "auto_signal": "habit", "activity_type": "habit"}],
            [{"text": "Notice what you reach for your phone to avoid, then reflect on it.", "auto_signal": None, "activity_type": "reflection"},
             {"text": "Journal what you noticed you reach for your phone to avoid.", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "Take a 10-minute screen-free break outside.", "auto_signal": "habit", "activity_type": "timer"}],
            [{"text": "Review your progress across the week.", "auto_signal": None, "activity_type": "progress_review"},
             {"text": "Re-check your assessment to see what's shifted since day 1.", "auto_signal": None, "activity_type": "assessment"},
             {"text": "Reflect on this week -- what's one change worth keeping?", "auto_signal": "journal", "activity_type": "journal"}],
        ],
    },
    "self_esteem": {
        "title": "Self-Esteem Builder",
        "duration_days": 14,
        "risk_categories": ["depression", "loneliness"],
        "days": [
            [{"text": "Write down one thing you did well today, however small.", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "Do one small habit check-in just for you.", "auto_signal": "habit", "activity_type": "habit"}],
            [{"text": "Notice one moment of self-criticism today, then rewrite it kindly.", "auto_signal": None, "activity_type": "reflection"},
             {"text": "Journal about it a little more if it helps.", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "Check in: how are you feeling about yourself today?", "auto_signal": None, "activity_type": "checkin"}],
            [{"text": "Journal about a past challenge you got through.", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "Check in on your habit again.", "auto_signal": "habit", "activity_type": "habit"}],
            [{"text": "Name one strength a friend would say you have, and journal about it.", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "Check in: what's one thing you did today purely because you enjoy it?", "auto_signal": None, "activity_type": "checkin"}],
            [{"text": "Journal one thing that felt different from day 1.", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "Check in on your habit.", "auto_signal": "habit", "activity_type": "habit"}],
            [{"text": "Write a short note to yourself as if to a friend having your week.", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "Notice one compliment or good moment today and sit with it.", "auto_signal": None, "activity_type": "reflection"},
             {"text": "Journal about that moment.", "auto_signal": "journal", "activity_type": "journal"}],
            [{"text": "Check in on your habit one more time.", "auto_signal": "habit", "activity_type": "habit"}],
            [{"text": "Review your progress across the two weeks.", "auto_signal": None, "activity_type": "progress_review"},
             {"text": "Reflect on the two weeks -- what's worth carrying forward?", "auto_signal": "journal", "activity_type": "journal"}],
        ],
    },
}

GENERATE_SYSTEM_PROMPT = (
    "You personalize a mental-wellness recovery plan's daily tasks. You will "
    "be given a plan's existing day-by-day tasks and a user's stored memory "
    "facts (recurring stressors/goals/habits/triggers). Reword each task to "
    "gently reference relevant stored facts where it fits naturally -- do "
    "NOT invent facts not given, do NOT change the number of days, do NOT "
    "change what kind of action each task is (journaling stays journaling, "
    "a habit check-in stays a habit check-in), do NOT add medical or "
    "diagnostic language, keep each task under 25 words. Return ONLY a JSON "
    "array of strings, exactly {n} items, one per day in order, no prose, "
    "no markdown fences."
)


def _recent_checkin_anxiety_signal(user_id: int) -> tuple[bool, float, int]:
    """Looks at this user's own logged CHECK_IN activities (anxiety 0-10
    scale) from the last 10 days across any plan -- real numbers the user
    entered, not inferred. Returns (elevated, average, count). Needs at
    least 2 data points to avoid overreacting to a single check-in."""
    since = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    results = get_recent_activity_results(user_id, "checkin", since)
    anxieties = [r["anxiety"] for r in results if isinstance(r.get("anxiety"), (int, float))]
    if len(anxieties) < 2:
        return False, 0.0, len(anxieties)
    avg = sum(anxieties) / len(anxieties)
    return avg >= 6.5, avg, len(anxieties)


def recommend_plan_type(user_id: int) -> tuple[str, str]:
    """Picks a template from real signals. Returns (plan_type, reason).
    Precedence: an explicit 'exam' stressor in memory beats general risk
    scoring (a student's actual stated stressor is more specific than a
    heuristic risk category); then the user's own recent CHECK_IN activity
    results if they show elevated anxiety (this is the personalization
    loop -- what the user reported feeling during their last plan shapes
    the next one); then the highest-severity active risk category, mapped
    to the template built for it; otherwise a general self-esteem plan as
    a safe default for a new/low-risk user."""
    from ml.risk_engine import compute_risk_profile

    stressors = get_active_memory_facts(user_id, fact_type="stressor")
    if any("exam" in f["fact_text"].lower() for f in stressors):
        return "exam_stress", "you have a recurring exam-related stressor in your memory"

    elevated, avg_anxiety, n = _recent_checkin_anxiety_signal(user_id)
    if elevated:
        return "anxiety", f"your last {n} check-ins averaged {avg_anxiety:.1f}/10 anxiety"

    profile = compute_risk_profile(user_id, persist=False)
    severity_order = {"critical": 3, "high": 2, "moderate": 1, "low": 0}
    ranked = sorted(profile.items(), key=lambda kv: severity_order[kv[1]["level"]], reverse=True)
    top_category, top = ranked[0]

    if severity_order[top["level"]] == 0:
        return "self_esteem", "a general plan to build on since no elevated risk signals are active right now"

    category_to_plan = {
        "anxiety": "anxiety",
        "burnout": "sleep",
        "digital_addiction": "digital_detox",
        "depression": "self_esteem",
        "loneliness": "self_esteem",
    }
    plan_type = category_to_plan.get(top_category, "self_esteem")
    reason = f"your {top_category.replace('_', ' ')} risk is currently {top['level']}"
    return plan_type, reason


def _flatten_days(days: list[list[dict]]) -> list[tuple[int, dict]]:
    """[[{...}, {...}], [{...}]] -> [(1, act), (1, act), (2, act), ...]"""
    return [(day_number, act) for day_number, day in enumerate(days, start=1) for act in day]


def _personalize_tasks(plan_type: str, flat_activities: list[tuple[int, dict]], user_id: int) -> list[str]:
    """Returns reworded task text (same length/order/meaning as
    flat_activities) if Gemini is configured and returns a valid
    same-length array; otherwise the deterministic template text
    unchanged."""
    texts = [act["text"] for _, act in flat_activities]
    if not GEMINI_API_KEY:
        return texts

    facts = get_active_memory_facts(user_id, limit=10)
    if not facts:
        return texts

    facts_block = "\n".join(f"- ({f['fact_type']}) {f['fact_text']}" for f in facts)
    tasks_block = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    prompt = (
        f"{GENERATE_SYSTEM_PROMPT.format(n=len(texts))}\n\n"
        f"Existing tasks:\n{tasks_block}\n\nUser's stored memory facts:\n{facts_block}"
    )
    try:
        import json
        client = get_gemini_client()
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = (response.text or "").strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(raw)
        if isinstance(result, list) and len(result) == len(texts) and all(isinstance(t, str) and t.strip() for t in result):
            return [t.strip()[:200] for t in result]
    except Exception:
        pass
    return texts


def get_or_create_active_plan(user_id: int) -> dict:
    """Returns the user's active plan (with tasks + progress), creating a
    recommended one if none exists, and rolling over an expired plan into
    a freshly-recommended one first."""
    plan = get_active_recovery_plan(user_id)

    if plan is not None:
        ends_at = datetime.fromisoformat(plan["ends_at"])
        if datetime.now(timezone.utc) >= ends_at:
            tasks = get_recovery_plan_tasks(plan["id"])
            done = sum(1 for t in tasks if t["completed"])
            status = "completed" if tasks and done / len(tasks) >= 0.6 else "expired"
            set_recovery_plan_status(plan["id"], status)
            plan = None

    if plan is None:
        plan_type, reason = recommend_plan_type(user_id)
        plan = _instantiate_plan(user_id, plan_type, source="risk_suggested", reason=reason)

    _sync_auto_progress(user_id, plan)
    return _plan_with_progress(plan)


def start_plan(user_id: int, plan_type: str) -> dict:
    """User-chosen plan, replacing any current active plan."""
    if plan_type not in PLAN_LIBRARY:
        raise ValueError("Unknown plan type")
    plan = _instantiate_plan(user_id, plan_type, source="manual", reason=None)
    _sync_auto_progress(user_id, plan)
    return _plan_with_progress(plan)


def _instantiate_plan(user_id: int, plan_type: str, source: str, reason: str | None) -> dict:
    template = PLAN_LIBRARY[plan_type]
    flat = _flatten_days(template["days"])
    task_texts = _personalize_tasks(plan_type, flat, user_id)
    activities = [
        (day_number, text, act["auto_signal"], act["activity_type"])
        for (day_number, act), text in zip(flat, task_texts)
    ]
    plan_id = create_recovery_plan(
        user_id, plan_type, template["title"], template["duration_days"], activities, source=source,
    )
    plan = get_recovery_plan(plan_id, user_id)
    plan["recommend_reason"] = reason
    return plan


def _sync_auto_progress(user_id: int, plan: dict):
    """Auto-completes tasks whose day has already passed (or is today) if
    the user's own logged activity on that calendar day already satisfies
    the task's auto_signal -- grounded in real rows, never guessed."""
    tasks = get_recovery_plan_tasks(plan["id"])
    if not tasks:
        return
    started = datetime.fromisoformat(plan["started_at"])
    journal_dates = get_journal_dates_between(user_id, started.isoformat(), datetime.now(timezone.utc).isoformat())
    habit_dates = get_habit_checkin_dates_between(user_id, started.isoformat(), datetime.now(timezone.utc).isoformat())

    for t in tasks:
        if t["completed"] or not t["auto_signal"]:
            continue
        day_date = (started + timedelta(days=t["day_number"] - 1)).date().isoformat()
        satisfied = (
            (t["auto_signal"] == "journal" and day_date in journal_dates)
            or (t["auto_signal"] == "habit" and day_date in habit_dates)
        )
        if satisfied:
            set_recovery_task_completed(t["id"], plan["id"], True)


def toggle_task(user_id: int, plan_id: int, task_id: int, completed: bool) -> dict:
    plan = get_recovery_plan(plan_id, user_id)
    if plan is None or plan["status"] != "active":
        raise ValueError("No active plan with that id for this user")
    set_recovery_task_completed(task_id, plan_id, completed)
    _maybe_complete_plan(plan)
    return _plan_with_progress(plan)


def _maybe_complete_plan(plan: dict):
    """Shared by the legacy checkbox toggle and every Activity Engine
    completion path: once every day's task is completed, the plan itself
    is marked completed. Mutates plan['status'] in place for callers that
    reuse the same dict afterward."""
    tasks = get_recovery_plan_tasks(plan["id"])
    if tasks and all(t["completed"] for t in tasks):
        set_recovery_plan_status(plan["id"], "completed")
        plan["status"] = "completed"


def _plan_with_progress(plan: dict) -> dict:
    tasks = get_recovery_plan_tasks(plan["id"])
    completed = sum(1 for t in tasks if t["completed"])
    started = datetime.fromisoformat(plan["started_at"])
    current_day = min(plan["duration_days"], max(1, (datetime.now(timezone.utc) - started).days + 1))
    return {
        **plan,
        "tasks": tasks,
        "progress": {
            "completed": completed,
            "total": len(tasks),
            "percent": round(100 * completed / len(tasks)) if tasks else 0,
            "current_day": current_day,
        },
    }


def get_history(user_id: int, limit: int = 10) -> list[dict]:
    plans = get_recovery_plan_history(user_id, limit)
    out = []
    for p in plans:
        tasks = get_recovery_plan_tasks(p["id"])
        completed = sum(1 for t in tasks if t["completed"])
        out.append({**p, "progress": {
            "completed": completed, "total": len(tasks),
            "percent": round(100 * completed / len(tasks)) if tasks else 0,
        }})
    return out


# ==========================================================================
# ACTIVITY ENGINE
#
# Turns each day's task from a checkbox into a self-contained interactive
# activity. Every function below is used by routes/recovery.py's
# /api/recovery/activities/* endpoints. Every one starts with the same
# ownership check (get_recovery_task_for_user) -- a task_id is never acted
# on without proving it belongs to the requesting user's own plan, and the
# activity_type is always read from the server-stored task, never trusted
# from the client.
# ==========================================================================

MAX_TEXT_LEN = 3000
MIN_TIMER_TOLERANCE_SECONDS = 3  # small grace so network latency can't fail an honest completion


class ActivityError(ValueError):
    """Raised for any activity request that fails ownership, state, or
    input validation -- routes/recovery.py turns this into a 400/403/404."""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _load_task(user_id: int, task_id: int) -> dict:
    task = get_recovery_task_for_user(task_id, user_id)
    if task is None:
        raise ActivityError("Activity not found.", 404)
    if task["plan_status"] != "active":
        raise ActivityError("This plan is no longer active.", 400)
    task["result"] = json.loads(task["result_json"]) if task.get("result_json") else None
    return task


def get_activity(user_id: int, task_id: int) -> dict:
    """Read-only fetch for opening/resuming an activity (e.g. after a page
    refresh) -- includes started_at so a TIMER activity's client can
    recompute real elapsed time instead of restarting the clock."""
    return _load_task(user_id, task_id)


def start_activity(user_id: int, task_id: int) -> dict:
    task = _load_task(user_id, task_id)
    if task["state"] == "not_started":
        start_recovery_task(task_id, task["plan_id"])
        task = _load_task(user_id, task_id)
    return task


def skip_activity(user_id: int, task_id: int) -> dict:
    task = _load_task(user_id, task_id)
    if task["activity_type"] in ("progress_review",):
        raise ActivityError("This activity can't be skipped.")
    if task["state"] == "completed":
        raise ActivityError("This activity is already completed.")
    skip_recovery_task(task_id, task["plan_id"])
    return _load_task(user_id, task_id)


def _check_idempotent(user_id: int, task_id: int, expected_type: str) -> dict | None:
    """Call BEFORE any side-effecting work (saving a journal entry,
    checking in a habit, etc). Returns the existing task if this activity
    is already completed -- so a duplicate submission returns the original
    saved result without re-running the side effect a second time. Returns
    None if the caller should proceed normally."""
    task = _load_task(user_id, task_id)
    if task["activity_type"] != expected_type:
        raise ActivityError(f"This activity is a '{task['activity_type']}' activity, not '{expected_type}'.")
    return task if task["state"] == "completed" else None


def _finish(user_id: int, task_id: int, expected_type: str, result: dict) -> dict:
    """Common completion path for every activity type: re-checks ownership
    fresh (never trusts an earlier read), refuses to run the wrong
    activity's completion logic against a task of a different type, and is
    idempotent on duplicate submission -- resubmitting an already-completed
    activity just returns its existing saved result instead of silently
    overwriting it or erroring."""
    task = _load_task(user_id, task_id)
    if task["activity_type"] != expected_type:
        raise ActivityError(f"This activity is a '{task['activity_type']}' activity, not '{expected_type}'.")
    if task["state"] == "completed":
        return task  # duplicate submission -- idempotent, keep the original result
    complete_recovery_task(task_id, task["plan_id"], result)
    task = _load_task(user_id, task_id)
    plan = get_recovery_plan(task["plan_id"], user_id)
    if plan:
        _maybe_complete_plan(plan)
    return task


# ---- JOURNAL --------------------------------------------------------------
def complete_journal_activity(user_id: int, task_id: int, prompt_responses: dict) -> dict:
    """prompt_responses: {"worry": str, "control": str} (either may be
    blank, but not both). Reuses the exact journal pipeline (analysis +
    persistence + long-term memory update) that /journal uses, so a
    reflection written inside a plan shows up in the user's real journal
    history -- never a shadow copy."""
    from database.db import save_journal_entry
    from ml.emotion_analyzer import analyze_journal_entry
    from ml.memory import update_memory_from_entry

    already = _check_idempotent(user_id, task_id, "journal")
    if already is not None:
        return already

    worry = (prompt_responses.get("worry") or "").strip()[:MAX_TEXT_LEN]
    control = (prompt_responses.get("control") or "").strip()[:MAX_TEXT_LEN]
    if not worry and not control:
        raise ActivityError("Write at least a little before saving.")

    parts = []
    if worry:
        parts.append(f"What's on my mind: {worry}")
    if control:
        parts.append(f"What's within my control: {control}")
    entry_text = "\n\n".join(parts)

    analysis = analyze_journal_entry(entry_text)
    entry = save_journal_entry(user_id, entry_text, analysis, input_method="text")
    update_memory_from_entry(user_id, entry_text)

    result = {
        "journal_entry_id": entry["id"],
        "emotion_label": entry["emotion_label"],
        "overall_sentiment": entry["overall_sentiment"],
        "crisis_flag": bool(analysis.get("crisis_flag")),
    }
    task = _finish(user_id, task_id, "journal", result)
    task["crisis_flag"] = bool(analysis.get("crisis_flag"))
    return task


# ---- GUIDED REFLECTION / QUIZ ---------------------------------------------
REFLECTION_TEMPLATE = [
    {"id": "thought", "prompt": "What thought is bothering you?", "type": "text"},
    {"id": "fact_or_prediction", "prompt": "Is this thought a fact or a prediction?",
     "type": "choice", "choices": ["Fact", "Prediction", "Assumption"]},
    {"id": "reframe", "prompt": "What's another possible interpretation?", "type": "text"},
]


def get_reflection_template() -> list:
    return REFLECTION_TEMPLATE


def complete_reflection_activity(user_id: int, task_id: int, responses: list) -> dict:
    if not isinstance(responses, list) or not responses:
        raise ActivityError("Reflection responses are required.")
    template_ids = {q["id"] for q in REFLECTION_TEMPLATE}
    cleaned = []
    for r in responses:
        if not isinstance(r, dict):
            raise ActivityError("Malformed reflection response.")
        qid = r.get("id")
        answer = (r.get("answer") or "").strip()[:MAX_TEXT_LEN]
        if qid not in template_ids or not answer:
            raise ActivityError("Every reflection question needs an answer.")
        cleaned.append({"id": qid, "answer": answer})
    result = {"responses": cleaned}
    return _finish(user_id, task_id, "reflection", result)


# ---- BREATHING --------------------------------------------------------------
def complete_breathing_activity(user_id: int, task_id: int, rounds_completed: int,
                                 duration_seconds: int, mood_after: str | None) -> dict:
    try:
        rounds_completed = int(rounds_completed)
        duration_seconds = int(duration_seconds)
    except (TypeError, ValueError):
        raise ActivityError("Invalid breathing session data.")
    if rounds_completed < 1 or duration_seconds < 4:
        raise ActivityError("Complete at least one full breathing round first.")
    mood_after = (mood_after or "").strip()[:40] or None
    result = {
        "rounds_completed": min(rounds_completed, 50),
        "duration_seconds": min(duration_seconds, 3600),
        "mood_after": mood_after,
    }
    return _finish(user_id, task_id, "breathing", result)


# ---- TIMER / FOCUS CHALLENGE ----------------------------------------------
DEFAULT_TIMER_SECONDS = 600  # 10 minutes, matches the plan-library copy ("10-minute" tasks)


def complete_timer_activity(user_id: int, task_id: int, planned_seconds: int,
                             mood_after: str | None) -> dict:
    """Server-verified completion: the activity must have been started
    (start_activity) and enough wall-clock time must have actually passed
    since started_at -- a client can't fake this by just clicking a
    button, since started_at lives server-side."""
    task = _load_task(user_id, task_id)
    if task["activity_type"] != "timer":
        raise ActivityError("This activity is not a timer.")
    if task["state"] == "completed":
        return task
    if not task.get("started_at"):
        raise ActivityError("Start the timer before completing it.")
    try:
        planned_seconds = int(planned_seconds)
    except (TypeError, ValueError):
        planned_seconds = DEFAULT_TIMER_SECONDS
    planned_seconds = max(30, min(planned_seconds, 3600))

    started = datetime.fromisoformat(task["started_at"])
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    if elapsed + MIN_TIMER_TOLERANCE_SECONDS < planned_seconds:
        raise ActivityError(
            f"Only {int(elapsed)}s have passed since you started -- give it the full "
            f"{planned_seconds}s before completing."
        )
    mood_after = (mood_after or "").strip()[:40] or None
    result = {"planned_seconds": planned_seconds, "actual_seconds": int(elapsed), "mood_after": mood_after}
    return _finish(user_id, task_id, "timer", result)


# ---- CHECK-IN --------------------------------------------------------------
def complete_checkin_activity(user_id: int, task_id: int, anxiety: int, energy: int, mood: str) -> dict:
    try:
        anxiety = int(anxiety)
        energy = int(energy)
    except (TypeError, ValueError):
        raise ActivityError("Anxiety and energy must be numbers 0-10.")
    if not (0 <= anxiety <= 10) or not (0 <= energy <= 10):
        raise ActivityError("Anxiety and energy must be between 0 and 10.")
    mood = (mood or "").strip()[:40]
    if not mood:
        raise ActivityError("Pick a mood before continuing.")
    result = {"anxiety": anxiety, "energy": energy, "mood": mood}
    return _finish(user_id, task_id, "checkin", result)


# ---- HABIT CHALLENGE --------------------------------------------------------
def complete_habit_activity(user_id: int, task_id: int, habit_name: str) -> dict:
    from database.db import checkin_habit, create_habit, get_habits

    already = _check_idempotent(user_id, task_id, "habit")
    if already is not None:
        return already

    habit_name = (habit_name or "").strip()[:60]
    if not habit_name:
        raise ActivityError("Name the habit you're checking in on.")
    normalized = " ".join(habit_name.split()).lower()  # collapse "Evening  Walk" / "evening walk" together

    existing = {" ".join(h["name"].split()).lower(): h["id"] for h in get_habits(user_id)}
    habit_id = existing.get(normalized)
    if habit_id is None:
        if len(existing) >= 15:
            raise ActivityError("You've reached the 15-habit limit -- reuse an existing habit instead.")
        habit_id = create_habit(user_id, habit_name)

    checkin_date = checkin_habit(habit_id, user_id)
    result = {"habit_id": habit_id, "habit_name": habit_name, "checkin_date": checkin_date}
    return _finish(user_id, task_id, "habit", result)


# ---- AI CONVERSATION --------------------------------------------------------
def complete_ai_conversation_activity(user_id: int, task_id: int, turn_count: int) -> dict:
    """turn_count is passed in by the route from the *server-side* Flask
    session's companion_history length, not from the request body -- so a
    client can't claim a conversation happened that didn't."""
    if turn_count < 2:
        raise ActivityError("Have at least one exchange with the companion before finishing.")
    result = {"turns": turn_count}
    return _finish(user_id, task_id, "ai_conversation", result)


# ---- QUIZ / THOUGHT EXERCISE -----------------------------------------------
QUIZ_TEMPLATE = [
    {"id": "q1", "prompt": '"I will fail this exam." What type of thought is this?',
     "choices": ["Fact", "Prediction", "Assumption"], "correct": "Prediction"},
    {"id": "q2", "prompt": '"Everyone thinks I\'m not prepared." What type of thought is this?',
     "choices": ["Fact", "Prediction", "Assumption"], "correct": "Assumption"},
    {"id": "q3", "prompt": '"I studied for three hours today." What type of thought is this?',
     "choices": ["Fact", "Prediction", "Assumption"], "correct": "Fact"},
]


def get_quiz_template() -> list:
    return QUIZ_TEMPLATE


def complete_quiz_activity(user_id: int, task_id: int, responses: list) -> dict:
    if not isinstance(responses, list) or not responses:
        raise ActivityError("Quiz answers are required.")
    by_id = {q["id"]: q for q in QUIZ_TEMPLATE}
    answered = {}
    for r in responses:
        if not isinstance(r, dict):
            raise ActivityError("Malformed quiz response.")
        qid, answer = r.get("id"), (r.get("answer") or "").strip()
        q = by_id.get(qid)
        if q is None or answer not in q["choices"]:
            raise ActivityError("Every quiz question needs a valid answer.")
        answered[qid] = answer
    if set(answered) != set(by_id):
        raise ActivityError("Answer every question before finishing.")
    score = sum(1 for qid, q in by_id.items() if answered[qid] == q["correct"])
    result = {
        "responses": [{"id": qid, "answer": ans} for qid, ans in answered.items()],
        "score": score, "total": len(by_id),
    }
    return _finish(user_id, task_id, "quiz", result)


# ---- ASSESSMENT -------------------------------------------------------------
# Reuses the exact same predictor pipeline as the standalone dashboard
# assessment (ml.predictor.predict_all + database.db.save_prediction) --
# never a separate/fake result path -- and respects the same free-plan
# daily prediction limit, since an in-plan assessment is still an
# assessment for billing purposes.
ASSESSMENT_DEFAULTS = {
    "Daily_Usage_Hours": 4.0, "Notifications_Per_Day": 50, "Platforms_Used_Count": 3,
    "Posts_Per_Week": 4, "Primary_Platform": "Instagram",
    "FOMO_Score": 5, "Social_Comparison_Score": 5, "Validation_Seeking_Score": 5,
    "Scroll_Without_Purpose": 5, "First_Check_Morning": 1,
    "Sleep_Hours": 7.0, "Physical_Activity_Hrs_Week": 3.0, "Screen_Free_Time_Hrs": 3.0,
    "Offline_Relationship_Quality": 5.0,
    "Late_Night_Usage": 0, "Tried_To_Cut_Back": 0, "Failed_To_Cut_Back": 0,
}


def get_assessment_defaults() -> dict:
    return dict(ASSESSMENT_DEFAULTS)


def complete_assessment_activity(user_id: int, task_id: int, form: dict, user_plan: str) -> dict:
    """form: the same field set the standalone /dashboard assessment posts
    (see ml.predictor.NUMERIC_BOUNDS/BINARY_FIELDS). Runs the real model
    pipeline -- no separate or shortcut scoring path -- and enforces the
    same free-plan daily limit as /api/predict, since this IS a real
    assessment, not a lighter in-plan copy of one."""
    from database.db import get_predictions_count_today, is_premium_user_id, save_prediction
    from ml.predictor import ValidationError, predict_all, user_facing_results
    from routes.billing import FREE_PLAN_DAILY_PREDICTION_LIMIT

    already = _check_idempotent(user_id, task_id, "assessment")
    if already is not None:
        return already

    if not is_premium_user_id(user_id) and get_predictions_count_today(user_id) >= FREE_PLAN_DAILY_PREDICTION_LIMIT:
        raise ActivityError(
            f"You've used your {FREE_PLAN_DAILY_PREDICTION_LIMIT} free assessments for today. "
            f"Upgrade to Premium for unlimited assessments.", 403,
        )

    try:
        results = predict_all(form)
    except ValidationError as e:
        raise ActivityError(str(e))

    results = user_facing_results(results)  # never persist the 57% severity label to history/export
    save_prediction(user_id, dict(form), results)
    result = {
        "wellbeing_score": results.get("wellbeing_score"),
        "wellbeing_risk_flag": results.get("wellbeing_risk_flag"),
        "addiction_risk_flag": results.get("addiction_risk_flag"),
    }
    return _finish(user_id, task_id, "assessment", result)


# ---- PROGRESS REVIEW --------------------------------------------------------
def get_progress_review(user_id: int, plan_id: int) -> dict:
    plan = get_recovery_plan(plan_id, user_id)
    if plan is None:
        raise ActivityError("Plan not found.", 404)
    tasks = get_recovery_plan_tasks(plan_id)

    by_type = {}
    moods = []
    for t in tasks:
        by_type.setdefault(t["activity_type"], {"completed": 0, "total": 0})
        by_type[t["activity_type"]]["total"] += 1
        if t["completed"]:
            by_type[t["activity_type"]]["completed"] += 1
            if t.get("result_json"):
                try:
                    r = json.loads(t["result_json"])
                except (TypeError, ValueError):
                    r = {}
                mood = r.get("mood") or r.get("mood_after")
                if mood:
                    moods.append(mood)

    completed = sum(1 for t in tasks if t["completed"])
    skipped = sum(1 for t in tasks if t["state"] == "skipped")
    return {
        "plan_id": plan_id,
        "title": plan["title"],
        "activities_completed": completed,
        "activities_total": len(tasks),
        "activities_skipped": skipped,
        "by_activity_type": by_type,
        "moods_logged": moods,
    }


def complete_progress_review_activity(user_id: int, task_id: int) -> dict:
    task = _load_task(user_id, task_id)
    review = get_progress_review(user_id, task["plan_id"])
    return _finish(user_id, task_id, "progress_review", {"reviewed": True, "snapshot": review})
