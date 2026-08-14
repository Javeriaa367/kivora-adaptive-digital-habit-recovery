"""
Tests for the Recovery Plan Activity Engine (routes/recovery.py's
/api/recovery/activities/* endpoints + ml/recovery_plans.py's activity
completion functions).
"""
import json
import time

import pytest


def _start_plan(client, plan_type="anxiety"):
    r = client.post("/api/recovery/start", json={"plan_type": plan_type})
    assert r.status_code == 200
    return r.get_json()["plan"]


def _task_of_type(plan, activity_type):
    for t in plan["tasks"]:
        if t["activity_type"] == activity_type:
            return t
    raise AssertionError(f"No task of type {activity_type} in plan")


class TestPlanCreationAndTypes:
    def test_new_plan_tasks_have_activity_types(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client, "anxiety")
        assert len(plan["tasks"]) == 19  # 7 days, several activities per day
        assert len({t["day_number"] for t in plan["tasks"]}) == 7
        for t in plan["tasks"]:
            assert t["activity_type"] in (
                "journal", "reflection", "breathing", "timer", "checkin",
                "habit", "ai_conversation", "progress_review",
            )
            assert t["state"] == "not_started"

    def test_opening_a_day(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        task = plan["tasks"][0]
        r = client.get(f"/api/recovery/activities/{task['id']}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["activity"]["id"] == task["id"]
        assert "reflection_template" in data


class TestOwnershipAndSecurity:
    def test_unauthorized_activity_access_returns_404(self, client, make_user, login):
        owner = make_user()
        other = make_user()
        login(owner)
        plan = _start_plan(client)
        task = plan["tasks"][0]

        login(other)
        r = client.get(f"/api/recovery/activities/{task['id']}")
        assert r.status_code == 404

        r = client.post(f"/api/recovery/activities/{task['id']}/start")
        assert r.status_code == 404

        r = client.post(f"/api/recovery/activities/{task['id']}/checkin",
                         json={"anxiety": 1, "energy": 1, "mood": "Good"})
        assert r.status_code == 404

    def test_login_required_for_all_activity_routes(self, client, make_user):
        r = client.get("/api/recovery/activities/1")
        assert r.status_code in (302, 401, 403)

    def test_nonexistent_task_id(self, client, make_user, login):
        login(make_user())
        r = client.get("/api/recovery/activities/999999")
        assert r.status_code == 404


class TestStartingActivity:
    def test_start_sets_in_progress_and_is_idempotent(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        task = plan["tasks"][0]
        r1 = client.post(f"/api/recovery/activities/{task['id']}/start")
        started_at_1 = r1.get_json()["activity"]["started_at"]
        assert r1.get_json()["activity"]["state"] == "in_progress"

        r2 = client.post(f"/api/recovery/activities/{task['id']}/start")
        started_at_2 = r2.get_json()["activity"]["started_at"]
        assert started_at_1 == started_at_2  # doesn't reset the clock on refresh


class TestJournalActivity:
    def test_complete_journal_activity(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        task = _task_of_type(plan, "journal")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/journal",
                         json={"worry": "I'm behind on studying", "control": "I can plan tomorrow"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["activity"]["state"] == "completed"
        assert data["activity"]["result"]["journal_entry_id"]

    def test_journal_persists_to_real_journal_history(self, client, make_user, login, app):
        user_id = make_user()
        login(user_id)
        plan = _start_plan(client)
        task = _task_of_type(plan, "journal")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        client.post(f"/api/recovery/activities/{task['id']}/journal",
                     json={"worry": "exam nerves", "control": "my prep time"})
        with app.app_context():
            from database.db import get_journal_entries
            entries = get_journal_entries(user_id)
        assert any("exam nerves" in e["entry_text"] for e in entries)

    def test_empty_journal_rejected(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        task = _task_of_type(plan, "journal")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/journal", json={"worry": "", "control": "  "})
        assert r.status_code == 400
        assert r.get_json()["ok"] is False

    def test_duplicate_journal_submission_is_idempotent(self, client, make_user, login, app):
        user_id = make_user()
        login(user_id)
        plan = _start_plan(client)
        task = _task_of_type(plan, "journal")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r1 = client.post(f"/api/recovery/activities/{task['id']}/journal", json={"worry": "first", "control": "x"})
        r2 = client.post(f"/api/recovery/activities/{task['id']}/journal", json={"worry": "second", "control": "y"})
        assert r1.get_json()["ok"] and r2.get_json()["ok"]
        assert r2.get_json()["activity"]["result"] == r1.get_json()["activity"]["result"]
        with app.app_context():
            from database.db import get_journal_entries
            entries = [e for e in get_journal_entries(user_id) if "first" in e["entry_text"] or "second" in e["entry_text"]]
        assert len(entries) == 1  # duplicate submit did not create a second journal entry


class TestReflectionActivity:
    def test_complete_reflection(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        task = _task_of_type(plan, "reflection")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/reflection", json={"responses": [
            {"id": "thought", "answer": "I will fail"},
            {"id": "fact_or_prediction", "answer": "Prediction"},
            {"id": "reframe", "answer": "I have prepared well"},
        ]})
        assert r.status_code == 200
        assert r.get_json()["activity"]["state"] == "completed"

    def test_reflection_missing_answer_rejected(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        task = _task_of_type(plan, "reflection")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/reflection", json={"responses": [
            {"id": "thought", "answer": ""},
        ]})
        assert r.status_code == 400


class TestBreathingActivity:
    def test_complete_breathing(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        task = _task_of_type(plan, "breathing")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/breathing",
                         json={"rounds_completed": 4, "duration_seconds": 56, "mood_after": "Calmer"})
        assert r.status_code == 200
        assert r.get_json()["activity"]["result"]["rounds_completed"] == 4

    def test_zero_rounds_rejected(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        task = _task_of_type(plan, "breathing")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/breathing",
                         json={"rounds_completed": 0, "duration_seconds": 0})
        assert r.status_code == 400


class TestTimerActivity:
    def test_timer_cannot_complete_before_started(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        task = _task_of_type(plan, "timer")
        r = client.post(f"/api/recovery/activities/{task['id']}/timer", json={"planned_seconds": 30})
        assert r.status_code == 400
        assert "Start the timer" in r.get_json()["error"]

    def test_timer_cannot_complete_immediately(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        task = _task_of_type(plan, "timer")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/timer", json={"planned_seconds": 30})
        assert r.status_code == 400

    def test_timer_completes_after_real_elapsed_time(self, client, make_user, login, app, monkeypatch):
        from datetime import datetime, timedelta, timezone
        login(make_user())
        plan = _start_plan(client)
        task = _task_of_type(plan, "timer")
        client.post(f"/api/recovery/activities/{task['id']}/start")

        # Rewind started_at directly rather than sleeping in the test suite.
        with app.app_context():
            from database.db import get_db
            db = get_db()
            past = (datetime.now(timezone.utc) - timedelta(seconds=40)).isoformat()
            db.execute("UPDATE recovery_plan_tasks SET started_at = ? WHERE id = ?", (past, task["id"]))
            db.commit()

        r = client.post(f"/api/recovery/activities/{task['id']}/timer", json={"planned_seconds": 30})
        assert r.status_code == 200
        assert r.get_json()["activity"]["state"] == "completed"


class TestCheckinActivity:
    def test_complete_checkin(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client, "sleep")
        task = _task_of_type(plan, "checkin")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/checkin",
                         json={"anxiety": 6, "energy": 4, "mood": "Stressed"})
        assert r.status_code == 200
        assert r.get_json()["activity"]["result"]["mood"] == "Stressed"

    def test_checkin_out_of_range_rejected(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client, "sleep")
        task = _task_of_type(plan, "checkin")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/checkin",
                         json={"anxiety": 55, "energy": 4, "mood": "Stressed"})
        assert r.status_code == 400


class TestHabitActivity:
    def test_complete_habit_creates_and_checks_in(self, client, make_user, login, app):
        user_id = make_user()
        login(user_id)
        plan = _start_plan(client, "sleep")
        task = _task_of_type(plan, "habit")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/habit", json={"habit_name": "Evening walk"})
        assert r.status_code == 200
        with app.app_context():
            from database.db import get_habit_status
            habits = get_habit_status(user_id)
        assert any(h["name"] == "Evening walk" and h["checked_today"] for h in habits)


class TestMultiActivityDays:
    def test_day_one_has_multiple_activities(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client, "anxiety")
        day1 = [t for t in plan["tasks"] if t["day_number"] == 1]
        assert len(day1) == 3
        assert {t["activity_type"] for t in day1} == {"checkin", "breathing", "reflection"}

    def test_plan_only_completes_when_every_activity_on_every_day_is_done(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client, "anxiety")
        day1 = [t for t in plan["tasks"] if t["day_number"] == 1]

        # complete only 2 of day 1's 3 activities
        checkin = next(t for t in day1 if t["activity_type"] == "checkin")
        breathing = next(t for t in day1 if t["activity_type"] == "breathing")
        client.post(f"/api/recovery/activities/{checkin['id']}/start")
        client.post(f"/api/recovery/activities/{checkin['id']}/checkin",
                    json={"anxiety": 3, "energy": 5, "mood": "Okay"})
        client.post(f"/api/recovery/activities/{breathing['id']}/start")
        client.post(f"/api/recovery/activities/{breathing['id']}/breathing",
                    json={"rounds_completed": 4, "duration_seconds": 56})

        r = client.get("/api/recovery/active")
        plan2 = r.get_json()["plan"]
        assert plan2["status"] == "active"
        assert plan2["progress"]["completed"] == 2
        assert plan2["progress"]["total"] == 19


class TestPlanProgressAndCompletion:
    def test_progress_updates_as_activities_complete(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        assert plan["progress"]["completed"] == 0
        task = _task_of_type(plan, "journal")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        client.post(f"/api/recovery/activities/{task['id']}/journal", json={"worry": "a", "control": "b"})

        r = client.get("/api/recovery/active")
        plan2 = r.get_json()["plan"]
        assert plan2["progress"]["completed"] == 1

    def test_progress_review_endpoint(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        task = _task_of_type(plan, "journal")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        client.post(f"/api/recovery/activities/{task['id']}/journal", json={"worry": "a", "control": "b"})

        r = client.get(f"/api/recovery/plans/{plan['id']}/progress-review")
        assert r.status_code == 200
        review = r.get_json()["review"]
        assert review["activities_completed"] == 1
        assert review["by_activity_type"]["journal"]["completed"] == 1


class TestSkipActivity:
    def test_skip_marks_state_skipped(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client)
        task = plan["tasks"][0]
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/skip")
        assert r.status_code == 200
        assert r.get_json()["activity"]["state"] == "skipped"

    def test_cannot_skip_completed_activity(self, client, make_user, login):
        login(make_user())
        plan = _start_plan(client, "sleep")
        task = _task_of_type(plan, "checkin")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        client.post(f"/api/recovery/activities/{task['id']}/checkin",
                     json={"anxiety": 1, "energy": 1, "mood": "Good"})
        r = client.post(f"/api/recovery/activities/{task['id']}/skip")
        assert r.status_code == 400


class TestQuizActivity:
    def test_quiz_scores_correctly(self, client, make_user, login, app):
        login(make_user())
        plan = _start_plan(client)
        task = plan["tasks"][0]
        with app.app_context():
            from database.db import get_db
            db = get_db()
            db.execute("UPDATE recovery_plan_tasks SET activity_type='quiz' WHERE id=?", (task["id"],))
            db.commit()
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/quiz", json={"responses": [
            {"id": "q1", "answer": "Prediction"},
            {"id": "q2", "answer": "Assumption"},
            {"id": "q3", "answer": "Fact"},
        ]})
        assert r.status_code == 200
        result = r.get_json()["activity"]["result"]
        assert result["score"] == 3 and result["total"] == 3

    def test_quiz_incomplete_answers_rejected(self, client, make_user, login, app):
        login(make_user())
        plan = _start_plan(client)
        task = plan["tasks"][0]
        with app.app_context():
            from database.db import get_db
            db = get_db()
            db.execute("UPDATE recovery_plan_tasks SET activity_type='quiz' WHERE id=?", (task["id"],))
            db.commit()
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/quiz", json={"responses": [
            {"id": "q1", "answer": "Prediction"},
        ]})
        assert r.status_code == 400


class TestPersonalizationLoop:
    def test_elevated_recent_checkin_anxiety_steers_next_plan(self, client, make_user, login, app):
        """Closes the personalization loop: a user's own recent check-in
        anxiety scores (real numbers they entered) should be able to steer
        which plan gets recommended for their *next* plan -- not just the
        journal-derived risk engine."""
        user_id = make_user()
        login(user_id)
        # Log 3 high-anxiety check-ins directly (as if from a past plan),
        # without going through a full plan lifecycle.
        plan = _start_plan(client, "sleep")  # has checkin-type days
        checkin_tasks = [t for t in plan["tasks"] if t["activity_type"] == "checkin"][:3]
        for t in checkin_tasks:
            client.post(f"/api/recovery/activities/{t['id']}/start")
            client.post(f"/api/recovery/activities/{t['id']}/checkin",
                        json={"anxiety": 8, "energy": 3, "mood": "Anxious"})

        with app.app_context():
            from ml.recovery_plans import recommend_plan_type
            plan_type, reason = recommend_plan_type(user_id)
        assert plan_type == "anxiety"
        assert "check-in" in reason

    def test_low_recent_checkin_anxiety_does_not_force_anxiety_plan(self, client, make_user, login, app):
        user_id = make_user()
        login(user_id)
        plan = _start_plan(client, "sleep")
        checkin_tasks = [t for t in plan["tasks"] if t["activity_type"] == "checkin"][:2]
        for t in checkin_tasks:
            client.post(f"/api/recovery/activities/{t['id']}/start")
            client.post(f"/api/recovery/activities/{t['id']}/checkin",
                        json={"anxiety": 1, "energy": 8, "mood": "Good"})

        with app.app_context():
            from ml.recovery_plans import recommend_plan_type
            plan_type, reason = recommend_plan_type(user_id)
        assert plan_type != "anxiety" or "check-in" not in reason


class TestAssessmentActivity:
    def test_complete_assessment_runs_real_pipeline(self, client, make_user, login, app):
        login(make_user())
        plan = _start_plan(client, "digital_detox")
        task = _task_of_type(plan, "assessment")
        with app.app_context():
            from ml.recovery_plans import get_assessment_defaults
            form = get_assessment_defaults()
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/assessment", json=form)
        assert r.status_code == 200
        result = r.get_json()["activity"]["result"]
        assert "wellbeing_score" in result and "addiction_risk_flag" in result
        assert "addiction_level_detail" not in result

    def test_assessment_saves_to_real_prediction_history(self, client, make_user, login, app):
        user_id = make_user()
        login(user_id)
        plan = _start_plan(client, "digital_detox")
        task = _task_of_type(plan, "assessment")
        with app.app_context():
            from ml.recovery_plans import get_assessment_defaults
            form = get_assessment_defaults()
        client.post(f"/api/recovery/activities/{task['id']}/start")
        client.post(f"/api/recovery/activities/{task['id']}/assessment", json=form)
        with app.app_context():
            from database.db import get_recent_predictions
            preds = get_recent_predictions(user_id)
        assert len(preds) == 1

    def test_assessment_respects_free_plan_daily_limit(self, client, make_user, login, app):
        user_id = make_user()
        login(user_id)
        plan = _start_plan(client, "digital_detox")
        task = _task_of_type(plan, "assessment")
        with app.app_context():
            from ml.recovery_plans import get_assessment_defaults
            from routes.billing import FREE_PLAN_DAILY_PREDICTION_LIMIT
            form = get_assessment_defaults()
            from database.db import save_prediction
            for _ in range(FREE_PLAN_DAILY_PREDICTION_LIMIT):
                save_prediction(user_id, form, {"wellbeing_score": {"value": 5.0}})
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/assessment", json=form)
        assert r.status_code == 403
        assert r.get_json()["ok"] is False

    def test_invalid_assessment_input_rejected(self, client, make_user, login, app):
        login(make_user())
        plan = _start_plan(client, "digital_detox")
        task = _task_of_type(plan, "assessment")
        client.post(f"/api/recovery/activities/{task['id']}/start")
        r = client.post(f"/api/recovery/activities/{task['id']}/assessment", json={"Daily_Usage_Hours": 3})
        assert r.status_code == 400  # missing required fields


class TestBackwardCompatibility:
    def test_legacy_toggle_endpoint_still_works(self, client, make_user, login):
        """The pre-Activity-Engine checkbox endpoint must keep working
        unchanged for any existing integration."""
        login(make_user())
        plan = _start_plan(client)
        task = plan["tasks"][0]
        r = client.post(f"/api/recovery/tasks/{task['id']}/toggle",
                         json={"plan_id": plan["id"], "completed": True})
        assert r.status_code == 200
        assert r.get_json()["plan"]["tasks"][0]["completed"] == 1

    def test_migration_backfills_legacy_rows_without_crashing(self, tmp_path, monkeypatch):
        """Simulates a pre-Activity-Engine database (recovery_plan_tasks
        without the new columns) and checks init_db() backfills it safely."""
        import sqlite3
        db_path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE recovery_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                plan_type TEXT NOT NULL, title TEXT NOT NULL, duration_days INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active', source TEXT NOT NULL DEFAULT 'manual',
                started_at TEXT NOT NULL, ends_at TEXT NOT NULL, created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE recovery_plan_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER NOT NULL,
                day_number INTEGER NOT NULL, task_text TEXT NOT NULL, auto_signal TEXT,
                completed INTEGER NOT NULL DEFAULT 0, completed_at TEXT
            )
        """)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT, password_hash TEXT, "
                      "created_at TEXT, is_admin INTEGER DEFAULT 0, plan TEXT DEFAULT 'free', "
                      "stripe_customer_id TEXT, stripe_subscription_id TEXT, referral_code TEXT, "
                      "referred_by_user_id INTEGER, google_sub TEXT)")
        conn.execute("INSERT INTO recovery_plans VALUES (1, 1, 'anxiety', 'Old Plan', 7, 'completed', 'manual', "
                      "'2024-01-01T00:00:00+00:00', '2024-01-08T00:00:00+00:00', '2024-01-01T00:00:00+00:00')")
        conn.execute("INSERT INTO recovery_plan_tasks (id, plan_id, day_number, task_text, auto_signal, completed) "
                      "VALUES (1, 1, 1, 'Try a breathing exercise today', NULL, 1)")
        conn.commit()
        conn.close()

        from config import Config

        class TestConfig(Config):
            TESTING = True
            SECRET_KEY = "t"
            DATABASE_PATH = db_path

        from app import create_app
        app = create_app(TestConfig)  # runs init_db -> _migrate_existing_db on the legacy file
        with app.app_context():
            from database.db import get_recovery_plan_tasks
            tasks = get_recovery_plan_tasks(1)
        assert tasks[0]["activity_type"] == "breathing"
        assert tasks[0]["state"] == "completed"
