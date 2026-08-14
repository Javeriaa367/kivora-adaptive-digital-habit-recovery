"""
Privacy-floor, CSRF, and landing-page tests for the P0 hardening pass.

Covers: public landing page at /, dashboard behind /dashboard, consent
required at signup, CSRF enforcement on state-changing requests (with the
Stripe webhook exempt), full data export, and cascade account deletion
(including severing referrer links).
"""
import json
from pathlib import Path

from database.db import (
    create_habit, create_user, delete_user, export_user_data, get_active_memory_facts,
    get_habits, get_journal_entry_count, get_recent_predictions, get_user_by_email,
    get_user_by_id, checkin_habit, insert_memory_fact, save_journal_entry, save_prediction,
)


# ---- Landing page / route layout ------------------------------------------

def test_landing_page_is_public(app, client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Kivora" in res.get_data(as_text=True)


def test_dashboard_requires_login(app, client):
    res = client.get("/dashboard")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_privacy_policy_page_is_public(app, client):
    res = client.get("/privacy")
    assert res.status_code == 200
    assert "Privacy Policy" in res.get_data(as_text=True)


def test_settings_page_requires_login(app, client):
    res = client.get("/settings")
    assert res.status_code == 302


def test_signup_page_has_csrf_field(app, client):
    res = client.get("/signup")
    assert res.status_code == 200
    assert 'name="csrf_token"' in res.get_data(as_text=True)


# ---- Consent on signup ------------------------------------------------------

def test_signup_requires_consent(app, client):
    res = client.post("/signup", data={
        "name": "No Consent", "email": "noconsent@example.com",
        "password": "password123", "confirm_password": "password123",
    })
    assert res.status_code == 200
    with app.app_context():
        assert get_user_by_email("noconsent@example.com") is None
    assert "Privacy Policy" in res.get_data(as_text=True)


def test_signup_with_consent_creates_user(app, client):
    res = client.post("/signup", data={
        "name": "Consent Given", "email": "consent@example.com",
        "password": "password123", "confirm_password": "password123",
        "consent": "on",
    })
    assert res.status_code == 302
    with app.app_context():
        user = get_user_by_email("consent@example.com")
        assert user is not None
        assert user["consent_given"] == 1
        assert user["consent_at"] is not None


# ---- CSRF -------------------------------------------------------------------

def test_csrf_missing_token_rejected(app):
    raw = app.test_client()
    res = raw.post("/api/notifications/read-all")
    assert res.status_code == 400
    assert "Your session expired" in res.get_json()["error"]


def test_csrf_wrong_token_rejected(app):
    raw = app.test_client()
    with raw.session_transaction() as sess:
        sess["csrf_token"] = "expected-token"
    res = raw.post("/api/notifications/read-all", headers={"X-CSRF-Token": "wrong-token"})
    assert res.status_code == 400


def test_csrf_valid_token_accepted(app):
    raw = app.test_client()
    with raw.session_transaction() as sess:
        sess["csrf_token"] = "expected-token"
    # Valid token -> CSRF passes; the route then requires login -> 302.
    res = raw.post("/api/notifications/read-all", headers={"X-CSRF-Token": "expected-token"})
    assert res.status_code == 302


def test_stripe_webhook_is_csrf_exempt(app, monkeypatch):
    import routes.billing as billing_module
    monkeypatch.setattr(billing_module, "STRIPE_WEBHOOK_SECRET", None)
    raw = app.test_client()
    # No CSRF token sent; the webhook's own handling must run (it reports
    # its own error), not the CSRF rejection.
    res = raw.post("/api/billing/webhook", data=json.dumps({}),
                   content_type="application/json")
    assert res.status_code == 400
    assert res.get_json()["error"] == "Webhook secret not configured"


# ---- Data export -------------------------------------------------------------

def test_export_returns_all_user_data(app, client, make_user, login):
    uid = make_user(email="export@example.com")
    login(uid)
    analysis = {"emotion_label": "Calm", "confidence": 0.8,
                "overall_sentiment": "positive", "sentiment_score": 0.5,
                "crisis_flag": False}
    with app.app_context():
        save_journal_entry(uid, "A peaceful morning.", analysis)
        save_prediction(uid, {"Daily_Usage_Hours": 3}, {"wellbeing_score": {"value": 7}})
        habit_id = create_habit(uid, "Run")
        checkin_habit(habit_id, uid)
        insert_memory_fact(uid, "stressor", "stressed about exams", "exams", 0.6)

    res = client.get("/api/account/export")
    assert res.status_code == 200
    data = json.loads(res.get_data(as_text=True))
    assert data["account"]["email"] == "export@example.com"
    assert len(data["journal_entries"]) == 1
    assert len(data["prediction_records"]) == 1
    assert len(data["habits"]) == 1
    assert len(data["habit_checkins"]) == 1
    assert len(data["memory_facts"]) == 1
    # A credential is never exported.
    assert "password_hash" not in json.dumps(data)


# ---- Account deletion ----------------------------------------------------------

def test_account_deletion_cascades_all_data(app, client, make_user, login):
    uid = make_user(email="delete@example.com")
    login(uid)
    analysis = {"emotion_label": "Sad", "confidence": 0.7,
                "overall_sentiment": "negative", "sentiment_score": -0.3,
                "crisis_flag": False}
    with app.app_context():
        save_journal_entry(uid, "Rough day.", analysis)
        save_prediction(uid, {"FOMO_Score": 8}, {"addiction_risk_flag": {"label": "At-risk"}})
        habit_id = create_habit(uid, "Meditate")
        checkin_habit(habit_id, uid)
        insert_memory_fact(uid, "trigger", "conflict with a friend", "conflict", 0.6)

    res = client.post("/api/account/delete", json={"confirm": "DELETE"})
    assert res.status_code == 200
    assert res.get_json()["ok"] is True

    with app.app_context():
        assert get_user_by_id(uid) is None
        assert get_journal_entry_count(uid) == 0
        assert get_recent_predictions(uid) == []
        assert get_habits(uid) == []
        assert get_active_memory_facts(uid) == []

    # The deleted user's session is cleared: /dashboard is no longer reachable.
    res = client.get("/dashboard")
    assert res.status_code == 302


def test_account_deletion_requires_confirmation(app, client, make_user, login):
    uid = make_user(email="keep@example.com")
    login(uid)
    res = client.post("/api/account/delete", json={"confirm": "yes delete me"})
    assert res.status_code == 400
    with app.app_context():
        assert get_user_by_id(uid) is not None


def test_deleting_referrer_severs_link_not_referred_user(app, make_user):
    with app.app_context():
        referrer = create_user("Referrer", "referrer@example.com", "password123", consent_given=True)
        referred = create_user("Referred", "referred@example.com", "password123",
                               referred_by_code=referrer["referral_code"], consent_given=True)
        assert referred["referred_by_user_id"] == referrer["id"]
        assert delete_user(referrer["id"]) is True
        assert get_user_by_id(referrer["id"]) is None
        survivor = get_user_by_id(referred["id"])
        assert survivor is not None
        assert survivor["referred_by_user_id"] is None


# ---- Severity label removed from user-facing surfaces --------------------------

def test_severity_label_removed_from_user_facing_surfaces():
    root = Path(__file__).resolve().parents[1]
    predict_js = (root / "static" / "js" / "predict.js").read_text(encoding="utf-8")
    dashboard = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
    recovery_js = (root / "static" / "js" / "recovery.js").read_text(encoding="utf-8")
    checkin = (root / "templates" / "checkin.html").read_text(encoding="utf-8")
    assert "Addiction Level (detail)" not in predict_js
    assert "addiction_level_detail.label" not in dashboard
    assert "addiction_level_detail.label" not in recovery_js
    assert "addiction_level_detail" not in checkin


def test_predict_api_excludes_severity_label(app, client, make_user, login):
    login(make_user())
    form = {
        "Daily_Usage_Hours": "4.4", "Notifications_Per_Day": "59",
        "Platforms_Used_Count": "3", "Posts_Per_Week": "4",
        "Primary_Platform": "Instagram",
        "FOMO_Score": "5.5", "Social_Comparison_Score": "5.5",
        "Validation_Seeking_Score": "5.5", "Scroll_Without_Purpose": "5.5",
        "Late_Night_Usage": "1", "Tried_To_Cut_Back": "1",
        "Failed_To_Cut_Back": "1", "First_Check_Morning": "1",
        "Sleep_Hours": "6.6", "Physical_Activity_Hrs_Week": "3",
        "Screen_Free_Time_Hrs": "3", "Offline_Relationship_Quality": "5.4",
    }
    res = client.post("/api/predict", json=form)
    assert res.status_code == 200
    body = res.get_json()
    assert "addiction_level_detail" not in body["results"]
    assert "addiction_level_detail" not in json.dumps(body)
    assert {"addiction_risk_flag", "wellbeing_score", "wellbeing_risk_flag"} <= set(body["results"])
