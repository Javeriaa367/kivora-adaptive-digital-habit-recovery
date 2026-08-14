"""Tests for the first-run onboarding flow (audit Phase 2 P2).

A brand-new account (no predictions, no journal entries, no habits) lands on
/onboarding instead of the empty dashboard. The flow is: check-in -> results
-> first journal entry, after which /onboarding redirects to the real
dashboard.
"""
from database.db import save_journal_entry, save_prediction


def _seed_prediction(app, uid):
    with app.app_context():
        save_prediction(uid, {"Daily_Usage_Hours": 4.0}, {
            "addiction_risk_flag": {"label": "Not at-risk", "confidence": 0.9, "at_risk_probability": 0.1},
            "wellbeing_score": {"value": 7.2},
            "wellbeing_risk_flag": {"label": "Above median", "confidence": 0.8},
        })


def _seed_journal(app, uid):
    with app.app_context():
        save_journal_entry(uid, "Feeling pretty calm and focused today.",
                           {"emotion_label": "Calm", "confidence": 0.85,
                            "overall_sentiment": "positive", "sentiment_score": 0.7,
                            "crisis_flag": 0})


def test_new_user_dashboard_redirects_to_onboarding(app, client, make_user, login):
    uid = make_user()
    login(uid)
    res = client.get("/dashboard")
    assert res.status_code == 302
    assert "/onboarding" in res.headers["Location"]


def test_onboarding_page_renders_three_steps(app, client, make_user, login):
    uid = make_user()
    login(uid)
    res = client.get("/onboarding")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "Run your first Check-In" in body
    assert "See what your answers mean" in body
    assert "Write your first journal entry" in body
    assert "Start Check-In" in body


def test_dashboard_available_once_started(app, client, make_user, login):
    uid = make_user()
    _seed_prediction(app, uid)
    login(uid)
    res = client.get("/dashboard")
    assert res.status_code == 200


def test_onboarding_redirects_to_dashboard_when_completed(app, client, make_user, login):
    uid = make_user()
    _seed_prediction(app, uid)
    _seed_journal(app, uid)
    login(uid)
    res = client.get("/onboarding")
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/dashboard")


def test_checkin_onboard_banner(app, client, make_user, login):
    uid = make_user()
    login(uid)
    res = client.get("/checkin?onboard=1")
    assert res.status_code == 200
    assert "Onboarding — step 1 of 3" in res.get_data(as_text=True)


def test_journal_onboard_banner(app, client, make_user, login):
    uid = make_user()
    login(uid)
    res = client.get("/journal?onboard=1")
    assert res.status_code == 200
    assert "Onboarding — step 3 of 3" in res.get_data(as_text=True)


def test_onboarding_page_marks_step1_done(app, client, make_user, login):
    uid = make_user()
    _seed_prediction(app, uid)
    login(uid)
    body = client.get("/onboarding").get_data(as_text=True)
    assert "Write entry" in body  # step 3 becomes the active CTA
    assert "Start Check-In" not in body
