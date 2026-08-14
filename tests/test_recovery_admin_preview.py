"""
Admin-only full recovery plan preview (routes/admin.py's
/admin/recovery/preview + ml/recovery_plans.admin_plan_preview).

Verifies:
  1. An admin can preview every day of the plan -- including days beyond
     the current progression day (which stay locked for normal users).
  2. The preview is read-only: no task state / plan status / current_day
     changes.
  3. A non-admin is rejected server-side by the existing @admin_required
     behavior (redirect to the admin forbidden response).
  4. Normal users keep the exact existing locking/progression UI, and the
     admin-only "Preview Full Plan" control is hidden from them.
"""
import pytest


def _make_admin(app, client, make_user, login, plan_type="anxiety"):
    user_id = make_user()
    with app.app_context():
        from database.db import set_user_admin
        set_user_admin(user_id, True)
    login(user_id)
    r = client.post("/api/recovery/start", json={"plan_type": plan_type})
    assert r.status_code == 200
    return user_id, r.get_json()["plan"]


PREVIEW_URL = "/admin/recovery/preview"


class TestAdminPreviewAccess:
    def test_admin_sees_every_day_and_every_task(self, client, make_user, login, app):
        _, plan = _make_admin(app, client, make_user, login, "anxiety")
        total_tasks = len(plan["tasks"])
        day_count = len({t["day_number"] for t in plan["tasks"]})

        r = client.get(PREVIEW_URL)
        assert r.status_code == 200
        html = r.get_data(as_text=True)

        assert "Admin preview" in html
        assert "Full Recovery Plan" in html
        assert "Progression locks are bypassed for inspection only" in html
        # Every day of the plan is rendered, including future/locked days.
        for day_number in range(1, day_count + 1):
            assert f"Day {day_number}" in html
        # Every stored task row is shown exactly once (reused real data).
        assert html.count("activity-row") == total_tasks
        # Future days are NOT displayed as "Locked" in the preview.
        assert "Locked" not in html
        # A task from a day beyond Day 1 (normally locked) is visible.
        from markupsafe import escape
        future_task = next(t for t in plan["tasks"] if t["day_number"] > 1)
        assert escape(future_task["task_text"]) in html

    def test_preview_is_read_only(self, client, make_user, login, app):
        user_id, plan = _make_admin(app, client, make_user, login, "anxiety")

        with app.app_context():
            from database.db import get_recovery_plan, get_recovery_plan_tasks
            before_tasks = [
                (t["id"], t["state"], t["completed"], t.get("started_at"), t.get("result_json"))
                for t in get_recovery_plan_tasks(plan["id"])
            ]
            before_status = get_recovery_plan(plan["id"], user_id)["status"]

        r = client.get(PREVIEW_URL)
        assert r.status_code == 200

        with app.app_context():
            from database.db import get_recovery_plan, get_recovery_plan_tasks
            after_tasks = [
                (t["id"], t["state"], t["completed"], t.get("started_at"), t.get("result_json"))
                for t in get_recovery_plan_tasks(plan["id"])
            ]
            after_status = get_recovery_plan(plan["id"], user_id)["status"]

        assert before_tasks == after_tasks
        assert before_status == after_status == "active"

    def test_preview_does_not_change_current_day(self, client, make_user, login, app):
        user_id, plan = _make_admin(app, client, make_user, login, "anxiety")

        with app.app_context():
            from ml.recovery_plans import admin_plan_preview
            before_day = admin_plan_preview(user_id)["current_day"]

        r = client.get(PREVIEW_URL)
        assert r.status_code == 200

        with app.app_context():
            from ml.recovery_plans import admin_plan_preview
            after_day = admin_plan_preview(user_id)["current_day"]

        assert before_day == after_day == plan["progress"]["current_day"]

    def test_no_plan_shows_empty_state(self, client, make_user, login, app):
        user_id = make_user()
        with app.app_context():
            from database.db import set_user_admin
            set_user_admin(user_id, True)
        login(user_id)
        r = client.get(PREVIEW_URL)
        assert r.status_code == 200
        assert "No active recovery plan" in r.get_data(as_text=True)


class TestNonAdminRejected:
    def test_normal_user_is_forbidden(self, client, make_user, login):
        login(make_user())
        r = client.get(PREVIEW_URL)
        assert r.status_code == 302  # existing forbidden response: redirect to dashboard
        assert "/dashboard" in r.headers.get("Location", "")

    def test_unauthenticated_is_redirected_to_login(self, client, make_user):
        r = client.get(PREVIEW_URL)
        assert r.status_code == 302


class TestNormalUserBehaviorUnchanged:
    def test_normal_user_locking_persists(self, client, make_user, login):
        login(make_user())
        r = client.post("/api/recovery/start", json={"plan_type": "anxiety"})
        plan = r.get_json()["plan"]
        day1_task_count = sum(1 for t in plan["tasks"] if t["day_number"] == 1)

        r = client.get("/recovery")
        assert r.status_code == 200
        html = r.get_data(as_text=True)

        # Day 1 tasks are actionable; future days show Locked instead.
        assert html.count("open-activity-btn") == day1_task_count
        assert "Locked" in html
        # Admin-only control is hidden from normal users.
        assert "Preview Full Plan" not in html

    def test_admin_recovery_page_shows_preview_control(self, client, make_user, login, app):
        _make_admin(app, client, make_user, login)
        r = client.get("/recovery")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "Preview Full Plan" in html
        assert "/admin/recovery/preview" in html
