"""
Interactive Demo Mode (routes/recovery_demo.py) -- admin-only sandbox.

Verifies:
  1. An admin can open the interactive demo page with every day unlocked
     (and the real progression-lock UI text never appears).
  2. The demo runs against an isolated throwaway "demo user", never the
     admin's own account -- performing activities leaves the admin's real
     recovery state, journal, habits, predictions and analytics untouched.
  3. Demo data is excluded from admin aggregates and the admin user list.
  4. Every demo endpoint is protected by @admin_required server-side.
  5. Brain exercises run against the demo user and every day is available.
  6. The timer still enforces a real wall-clock wait (>= 30s).
  7. The assessment runs on the demo user's premium plan (no free-plan
     daily-limit block) and persists only to the demo user.
  8. AI-conversation completion still requires real server-side turns.
  9. "Reset demo" wipes all sandbox state and the next visit rebuilds a
     fresh plan.
 10. The preview page links to the interactive demo.
"""
import json

import pytest
from datetime import datetime, timedelta, timezone

DEMO_URL = "/admin/recovery/demo"
DEMO_STATE = f"{DEMO_URL}/state"
DEMO_RESET = f"{DEMO_URL}/reset"


def _make_admin(app, client, make_user, login, plan_type="anxiety"):
    user_id = make_user()
    with app.app_context():
        from database.db import set_user_admin
        set_user_admin(user_id, True)
    login(user_id)
    r = client.post("/api/recovery/start", json={"plan_type": plan_type})
    assert r.status_code == 200
    return user_id, r.get_json()["plan"]


def _demo_user_id(app, admin_id):
    with app.app_context():
        from database.db import get_demo_user
        demo = get_demo_user(admin_id)
        return demo["id"] if demo is not None else None


def _task_of_type(plan, activity_type):
    for t in plan["tasks"]:
        if t["activity_type"] == activity_type:
            return t
    raise AssertionError(f"No task of type {activity_type} in plan")


def _open_demo(app, client, make_user, login, plan_type="anxiety"):
    """Sets up an admin with a plan, opens the demo page (creating the
    sandbox account + plan), and returns admin id, admin plan, demo state."""
    admin_id, admin_plan = _make_admin(app, client, make_user, login, plan_type)
    r = client.get(DEMO_URL)
    assert r.status_code == 200
    demo = _demo_user_id(app, admin_id)
    assert demo is not None and demo != admin_id
    return admin_id, admin_plan, demo


def _demo_plan_tasks(app, demo_id):
    with app.app_context():
        from database.db import get_recovery_plan_tasks
        from database.db import get_db
        row = get_db().execute(
            "SELECT id FROM recovery_plans WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (demo_id,),
        ).fetchone()
        assert row is not None
        return row["id"], get_recovery_plan_tasks(row["id"])


def _any_response(ex):
    """A syntactically-valid response for ANY exercise kind -- the score
    doesn't matter, only that a scored attempt gets recorded."""
    kind = ex["kind"]
    if kind in ("reframe", "worry_reality", "night_reset", "urge_breaker"):
        return -1  # never a valid option index, always scored wrong
    if kind == "gratitude_scan":
        return "family"
    if kind == "working_memory":
        return "not-a-real-word"
    return 0  # attention / updating


class TestAdminDemoAccess:
    def test_admin_sees_demo_page_with_all_days_unlocked(self, client, make_user, login, app):
        _, plan, _ = _open_demo(app, client, make_user, login, "anxiety")
        total_tasks = len(plan["tasks"])
        day_count = len({t["day_number"] for t in plan["tasks"]})

        r = client.get(DEMO_URL)
        assert r.status_code == 200
        html = r.get_data(as_text=True)

        assert "Interactive demo mode" in html
        assert "Sandbox plan" in html
        # JS is pointed at the demo mirror, not the player endpoints.
        assert 'window.KIVORA_DEMO_BASE = "/admin/recovery/demo"' in html
        assert "js/recovery.js" in html and "js/brain.js" in html
        # Every day renders, and none of them are progression-locked.
        for day_number in range(1, day_count + 1):
            assert f"Day {day_number}" in html
        assert "Locked" not in html
        # Every task is actionable (Start/Continue), none are locked.
        assert html.count("open-activity-btn") == total_tasks
        # A brain exercise row exists for every day.
        assert html.count("brain-exercise-row") == day_count

    def test_demo_state_exposes_isolated_demo_user_and_plan(self, client, make_user, login, app):
        admin_id, admin_plan, demo = _open_demo(app, client, make_user, login, "sleep")

        state = client.get(DEMO_STATE).get_json()
        assert state["ok"] is True
        assert state["demo_user_id"] == demo
        assert state["demo_user_id"] != admin_id
        # The sandbox plan mirrors the admin's plan type.
        assert state["plan"]["plan_type"] == admin_plan["plan_type"] == "sleep"

        with app.app_context():
            from database.db import get_demo_user, get_user_by_id
            demo_row = get_demo_user(admin_id)
            assert demo_row is not None
            assert demo_row["demo_owner_user_id"] == admin_id
            assert demo_row["plan"] == "premium"  # so assessment limits can't block a judge
            assert bool(demo_row["consent_given"]) is True
            assert bool(demo_row["is_admin"]) is False
            admin_row = get_user_by_id(admin_id)
            assert admin_row["demo_owner_user_id"] is None

    def test_demo_page_is_usable_when_admin_has_no_plan(self, client, make_user, login, app):
        admin_id = make_user()
        with app.app_context():
            from database.db import set_user_admin
            set_user_admin(admin_id, True)
        login(admin_id)
        r = client.get(DEMO_URL)
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "Sandbox plan" in html
        assert "Locked" not in html


class TestNonAdminRejected:
    def test_normal_user_cannot_open_demo_page(self, client, make_user, login):
        login(make_user())
        r = client.get(DEMO_URL)
        assert r.status_code == 302  # existing forbidden response: redirect to dashboard
        assert "/dashboard" in r.headers.get("Location", "")

    def test_normal_user_cannot_open_demo_api(self, client, make_user, login):
        login(make_user())
        r = client.get(DEMO_STATE)
        assert r.status_code == 302
        assert "/dashboard" in r.headers.get("Location", "")

    def test_normal_user_cannot_complete_demo_activity(self, client, make_user, login):
        login(make_user())
        # JSON requests are rejected with a 403 (auth_utils._forbidden),
        # matching the rest of the app's API convention.
        r = client.post(f"{DEMO_URL}/api/recovery/activities/1/checkin",
                        json={"anxiety": 5, "energy": 5, "mood": "Okay"})
        assert r.status_code == 403
        assert r.get_json()["error"] == "Admin access required."

    def test_unauthenticated_redirected_to_login(self, client, make_user):
        r = client.get(DEMO_URL)
        assert r.status_code == 302


class TestSandboxIsolation:
    def test_demo_journal_activity_only_touches_demo_user(self, client, make_user, login, app):
        admin_id, admin_plan, demo = _open_demo(app, client, make_user, login, "anxiety")

        with app.app_context():
            from database.db import get_journal_entries, get_recovery_plan_tasks
            admin_before = [
                (t["id"], t["state"], t["completed"]) for t in get_recovery_plan_tasks(admin_plan["id"])
            ]

        plan_id, demo_tasks = _demo_plan_tasks(app, demo)
        task = _task_of_type({"tasks": demo_tasks}, "journal")
        client.post(f"{DEMO_URL}/api/recovery/activities/{task['id']}/start")
        r = client.post(f"{DEMO_URL}/api/recovery/activities/{task['id']}/journal",
                        json={"worry": "demo worry text", "control": "demo control"})
        assert r.status_code == 200
        assert r.get_json()["activity"]["state"] == "completed"
        assert r.get_json()["activity"]["result"]["journal_entry_id"]

        with app.app_context():
            from database.db import get_journal_entries, get_recovery_plan_tasks
            admin_after = [
                (t["id"], t["state"], t["completed"]) for t in get_recovery_plan_tasks(admin_plan["id"])
            ]
            # The journal entry exists for the DEMO user, never the admin.
            demo_entries = get_journal_entries(demo)
            admin_entries = get_journal_entries(admin_id)
        assert admin_before == admin_after  # admin's recovery state is byte-for-byte unchanged
        assert any("demo worry text" in e["entry_text"] for e in demo_entries)
        assert all("demo worry text" not in e["entry_text"] for e in admin_entries)

    def test_demo_activity_does_not_pollute_admin_analytics(self, client, make_user, login, app):
        admin_id, admin_plan, demo = _open_demo(app, client, make_user, login, "anxiety")

        with app.app_context():
            from database.db import get_admin_analytics, get_admin_stats
            stats_before = get_admin_stats()
            analytics_before = get_admin_analytics(days=30)

        # Perform a demo journal + a demo brain exercise.
        plan_id, demo_tasks = _demo_plan_tasks(app, demo)
        journal = _task_of_type({"tasks": demo_tasks}, "journal")
        client.post(f"{DEMO_URL}/api/recovery/activities/{journal['id']}/start")
        client.post(f"{DEMO_URL}/api/recovery/activities/{journal['id']}/journal",
                    json={"worry": "demo worry", "control": "demo control"})

        ex = client.get(f"{DEMO_URL}/api/brain/today?day_number=1").get_json()["exercise"]
        submit = client.post(
            f"{DEMO_URL}/api/brain/attempts/{ex['attempt_id']}/submit",
            json={"response": _any_response(ex)},
        )
        assert submit.status_code == 200

        with app.app_context():
            from database.db import get_admin_analytics, get_admin_stats
            stats_after = get_admin_stats()
            analytics_after = get_admin_analytics(days=30)

        assert stats_after == stats_before
        assert analytics_after == analytics_before

    def test_demo_user_excluded_from_admin_user_list(self, client, make_user, login, app):
        admin_id, _, demo = _open_demo(app, client, make_user, login, "anxiety")
        with app.app_context():
            from database.db import get_admin_stats, list_all_users
            users = list_all_users()
            stats = get_admin_stats()
        assert all(u["id"] != demo for u in users)
        assert len(users) == 1  # just the admin
        assert stats["total_users"] == 1


class TestDemoBrain:
    def test_demo_brain_progress_marks_every_day_available(self, client, make_user, login, app):
        admin_id, admin_plan, demo = _open_demo(app, client, make_user, login, "anxiety")

        r = client.get(f"{DEMO_URL}/api/brain/progress")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        progress = data["progress"]
        assert set(progress["days"].keys()) == {str(d) for d in range(1, int(admin_plan["duration_days"]) + 1)}
        for day in progress["days"].values():
            assert day["available"] is True

    def test_demo_brain_exercise_runs_on_demo_user_any_day(self, client, make_user, login, app):
        admin_id, admin_plan, demo = _open_demo(app, client, make_user, login, "anxiety")

        # Day 7 is beyond the fresh demo plan's current day -- still playable.
        r = client.get(f"{DEMO_URL}/api/brain/today?day_number=7")
        assert r.status_code == 200
        ex = r.get_json()["exercise"]
        assert ex["day_number"] == 7
        assert "answer" not in ex and "scoring" not in ex  # ground truth never leaks

        submit = client.post(f"{DEMO_URL}/api/brain/attempts/{ex['attempt_id']}/submit",
                             json={"response": _any_response(ex)})
        assert submit.status_code == 200
        result = submit.get_json()["result"]
        assert "score" in result and "streak" in result

        with app.app_context():
            from database.db import get_brain_exercise_attempt
            attempt = get_brain_exercise_attempt(ex["attempt_id"], demo)
            assert attempt is not None
            assert attempt["user_id"] == demo
            assert attempt["user_id"] != admin_id


class TestDemoTimer:
    def test_demo_timer_still_requires_real_elapsed_time(self, client, make_user, login, app):
        admin_id, _, demo = _open_demo(app, client, make_user, login, "anxiety")
        _, demo_tasks = _demo_plan_tasks(app, demo)
        task = _task_of_type({"tasks": demo_tasks}, "timer")

        client.post(f"{DEMO_URL}/api/recovery/activities/{task['id']}/start")
        r = client.post(f"{DEMO_URL}/api/recovery/activities/{task['id']}/timer",
                        json={"planned_seconds": 30})
        assert r.status_code == 400  # not enough wall-clock time has passed

        with app.app_context():
            from database.db import get_db
            db = get_db()
            past = (datetime.now(timezone.utc) - timedelta(seconds=40)).isoformat()
            db.execute("UPDATE recovery_plan_tasks SET started_at = ? WHERE id = ?", (past, task["id"]))
            db.commit()

        r = client.post(f"{DEMO_URL}/api/recovery/activities/{task['id']}/timer",
                        json={"planned_seconds": 30})
        assert r.status_code == 200
        assert r.get_json()["activity"]["state"] == "completed"
        assert r.get_json()["activity"]["result"]["planned_seconds"] == 30


class TestDemoAssessment:
    def test_demo_assessment_runs_premium_without_limit_block(self, client, make_user, login, app):
        admin_id, admin_plan, demo = _open_demo(app, client, make_user, login, "digital_detox")
        _, demo_tasks = _demo_plan_tasks(app, demo)
        task = _task_of_type({"tasks": demo_tasks}, "assessment")

        with app.app_context():
            from ml.recovery_plans import get_assessment_defaults
            form = get_assessment_defaults()

        client.post(f"{DEMO_URL}/api/recovery/activities/{task['id']}/start")
        r = client.post(f"{DEMO_URL}/api/recovery/activities/{task['id']}/assessment", json=form)
        assert r.status_code == 200
        result = r.get_json()["activity"]["result"]
        assert "wellbeing_score" in result

        with app.app_context():
            from database.db import get_recent_predictions
            demo_preds = get_recent_predictions(demo)
            admin_preds = get_recent_predictions(admin_id)
        assert len(demo_preds) == 1
        assert len(admin_preds) == 0


class TestDemoAiConversation:
    def test_demo_ai_conversation_needs_real_turns(self, client, make_user, login, app):
        admin_id, _, demo = _open_demo(app, client, make_user, login, "anxiety")
        _, demo_tasks = _demo_plan_tasks(app, demo)
        task = _task_of_type({"tasks": demo_tasks}, "ai_conversation")

        client.post(f"{DEMO_URL}/api/recovery/activities/{task['id']}/start")
        # No companion history in the session yet -> completion rejected.
        r = client.post(f"{DEMO_URL}/api/recovery/activities/{task['id']}/ai-conversation")
        assert r.status_code == 400
        assert "companion" in r.get_json()["error"]

        # A real exchange populates the server-side session history (the
        # companion blueprint's own mechanism), same as the player route.
        with client.session_transaction() as sess:
            sess["companion_history"] = [
                {"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
                {"role": "user", "content": "again"}, {"role": "assistant", "content": "sure"},
            ]
        r = client.post(f"{DEMO_URL}/api/recovery/activities/{task['id']}/ai-conversation")
        assert r.status_code == 200
        assert r.get_json()["activity"]["state"] == "completed"
        assert r.get_json()["activity"]["result"]["turns"] == 4


class TestDemoReset:
    def test_reset_wipes_all_demo_state_and_rebuilds_fresh(self, client, make_user, login, app):
        admin_id, admin_plan, demo = _open_demo(app, client, make_user, login, "anxiety")

        # Do some demo activity so there is real sandbox state to wipe.
        plan_id, demo_tasks = _demo_plan_tasks(app, demo)
        journal = _task_of_type({"tasks": demo_tasks}, "journal")
        client.post(f"{DEMO_URL}/api/recovery/activities/{journal['id']}/start")
        client.post(f"{DEMO_URL}/api/recovery/activities/{journal['id']}/journal",
                    json={"worry": "demo", "control": "demo"})
        ex = client.get(f"{DEMO_URL}/api/brain/today?day_number=1").get_json()["exercise"]
        client.post(f"{DEMO_URL}/api/brain/attempts/{ex['attempt_id']}/submit",
                    json={"response": _any_response(ex)})

        with app.app_context():
            from database.db import get_admin_stats
            stats_before = get_admin_stats()

        r = client.post(DEMO_RESET)
        assert r.status_code == 200

        with app.app_context():
            from database.db import get_admin_stats, get_db, get_demo_user
            assert get_demo_user(admin_id) is None  # sandbox account gone
            # And therefore every cascaded demo row is gone too.
            assert get_db().execute(
                "SELECT COUNT(*) c FROM recovery_plans WHERE user_id = ?", (demo,)
            ).fetchone()["c"] == 0
            assert get_db().execute(
                "SELECT COUNT(*) c FROM recovery_plan_tasks WHERE plan_id = ?", (plan_id,)
            ).fetchone()["c"] == 0
            assert get_db().execute(
                "SELECT COUNT(*) c FROM journal_entries WHERE user_id = ?", (demo,)
            ).fetchone()["c"] == 0
            assert get_db().execute(
                "SELECT COUNT(*) c FROM brain_exercise_attempts WHERE user_id = ?", (demo,)
            ).fetchone()["c"] == 0
            assert get_admin_stats() == stats_before  # admin aggregates untouched

        # Next visit rebuilds a brand-new sandbox + fresh plan.
        r = client.get(DEMO_URL)
        assert r.status_code == 200
        fresh_demo = _demo_user_id(app, admin_id)
        assert fresh_demo is not None and fresh_demo != demo
        state = client.get(DEMO_STATE).get_json()
        assert state["plan"]["progress"]["completed"] == 0

    def test_reset_is_idempotent(self, client, make_user, login, app):
        admin_id, _, demo = _open_demo(app, client, make_user, login, "anxiety")
        assert client.post(DEMO_RESET).status_code == 200
        assert client.post(DEMO_RESET).status_code == 200


class TestPreviewIntegration:
    def test_preview_page_links_to_interactive_demo(self, client, make_user, login, app):
        _make_admin(app, client, make_user, login, "anxiety")
        r = client.get("/admin/recovery/preview")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "Enter Interactive Demo" in html
        assert "/admin/recovery/demo" in html
