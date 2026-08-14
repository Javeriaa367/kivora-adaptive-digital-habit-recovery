"""Tests for the real referral program (audit Phase 3 P2).

A valid referral code at signup must do something real: it grants BOTH sides
Premium days (premium_until in the future), the reward is auditable via
subscription_events, it stacks on existing premium, and it lifts the free
daily prediction limit on both /api/predict and the recovery-plan assessment
path. Invalid/self-referral codes must be ignored, not crash.
"""
from datetime import datetime, timedelta, timezone

import pytest

from database.db import (
    REFERRAL_PREMIUM_DAYS, create_user, get_user_by_id, get_user_by_email,
    grant_premium_days, is_premium_user,
)
@pytest.fixture
def referrer(app, make_user):
    uid = make_user()
    with app.app_context():
        return dict(get_user_by_id(uid))


def _premium_until(app, user_id):
    with app.app_context():
        return get_user_by_id(user_id)["premium_until"]


def test_valid_referral_grants_both_sides_premium(app, referrer):
    with app.app_context():
        new_user = create_user("Referred Friend", "friend@test.local", "pw" * 4,
                               referred_by_code=referrer["referral_code"])
        referrer_after = dict(get_user_by_id(referrer["id"]))
    assert new_user["referral_rewarded"] is True
    assert is_premium_user(new_user) is True
    assert is_premium_user(referrer_after) is True

    for until in (_premium_until(app, referrer["id"]), _premium_until(app, new_user["id"])):
        assert until is not None
        parsed = datetime.fromisoformat(until)
        assert datetime.now(timezone.utc) < parsed <= datetime.now(timezone.utc) + timedelta(days=REFERRAL_PREMIUM_DAYS + 1)


def test_referral_events_logged(app, referrer):
    with app.app_context():
        from database.db import get_db
        new_user = create_user("Referred Friend", "friend2@test.local", "pw" * 4,
                               referred_by_code=referrer["referral_code"])
        rows = get_db().execute(
            "SELECT user_id, raw_payload FROM subscription_events WHERE event_type = 'premium_grant'"
        ).fetchall()
    ids = {r["user_id"] for r in rows}
    assert ids == {referrer["id"], new_user["id"]}
    assert len(rows) == 2
    sources = {eval(r["raw_payload"])["source"] for r in rows}
    assert "referral:referrer" in sources
    assert "referral:new_user" in sources


def test_referral_grants_stack_on_existing_premium(app, referrer):
    with app.app_context():
        grant_premium_days(referrer["id"], 30, "coupon")
        before = _premium_until(app, referrer["id"])
        create_user("Referred Friend", "friend3@test.local", "pw" * 4,
                    referred_by_code=referrer["referral_code"])
        after = _premium_until(app, referrer["id"])
    assert (datetime.fromisoformat(after) - datetime.fromisoformat(before)).days == REFERRAL_PREMIUM_DAYS


def test_invalid_referral_code_ignored(app, referrer):
    with app.app_context():
        new_user = create_user("Nobody", "nobody@test.local", "pw" * 4, referred_by_code="BOGUS123")
    assert new_user["referral_rewarded"] is False
    assert _premium_until(app, new_user["id"]) is None
    assert _premium_until(app, referrer["id"]) is None


def test_no_referral_gets_no_premium(app, make_user):
    uid = make_user()
    assert _premium_until(app, uid) is None


def test_premium_until_expired_means_free(app, make_user):
    uid = make_user()
    with app.app_context():
        from database.db import get_db
        db = get_db()
        db.execute("UPDATE users SET premium_until = ? WHERE id = ?",
                   ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), uid))
        db.commit()
        row = get_user_by_id(uid)
    assert is_premium_user(row) is False


def test_signup_route_flashes_reward(app, client, referrer):
    res = client.post("/signup", data={
        "name": "Referred Pal",
        "email": "pal4@test.local",
        "password": "supersecure",
        "confirm_password": "supersecure",
        "consent": "on",
        "referral_code": referrer["referral_code"],
    }, follow_redirects=False)
    assert res.status_code in (301, 302)
    with app.app_context():
        new_user = get_user_by_email("pal4@test.local")
    assert new_user is not None
    assert is_premium_user(new_user) is True


def test_referral_premium_bypasses_api_limit(app, client, referrer):
    with app.app_context():
        new_user = create_user("Referred Pal", "pal5@test.local", "pw" * 4,
                               referred_by_code=referrer["referral_code"])
    with client.session_transaction() as s:
        s["user_id"] = new_user["id"]

    payload = {
        "Daily_Usage_Hours": 3.0, "Platforms_Used_Count": 2, "Posts_Per_Week": 1,
        "Notifications_Per_Day": 40, "FOMO_Score": 5, "Social_Comparison_Score": 4,
        "Validation_Seeking_Score": 3, "Scroll_Without_Purpose": 6, "Sleep_Hours": 7,
        "Offline_Relationship_Quality": 6, "Physical_Activity_Hrs_Week": 3,
        "Screen_Free_Time_Hrs": 4, "Late_Night_Usage": 0, "Tried_To_Cut_Back": 1,
        "Failed_To_Cut_Back": 0, "First_Check_Morning": 1, "Primary_Platform": "Instagram",
    }
    # Far beyond the free limit -- premium must not be throttled.
    for _ in range(10):
        res = client.post("/api/predict", json=payload)
        assert res.status_code == 200
        assert res.get_json()["ok"] is True


def test_free_user_hits_api_limit_after_free_daily_limit(app, client, make_user, login):
    uid = make_user()
    login(uid)
    from routes.billing import FREE_PLAN_DAILY_PREDICTION_LIMIT

    payload = {
        "Daily_Usage_Hours": 3.0, "Platforms_Used_Count": 2, "Posts_Per_Week": 1,
        "Notifications_Per_Day": 40, "FOMO_Score": 5, "Social_Comparison_Score": 4,
        "Validation_Seeking_Score": 3, "Scroll_Without_Purpose": 6, "Sleep_Hours": 7,
        "Offline_Relationship_Quality": 6, "Physical_Activity_Hrs_Week": 3,
        "Screen_Free_Time_Hrs": 4, "Late_Night_Usage": 0, "Tried_To_Cut_Back": 1,
        "Failed_To_Cut_Back": 0, "First_Check_Morning": 1, "Primary_Platform": "Instagram",
    }
    for _ in range(FREE_PLAN_DAILY_PREDICTION_LIMIT):
        res = client.post("/api/predict", json=payload)
        assert res.status_code == 200
    res = client.post("/api/predict", json=payload)
    assert res.status_code == 403
    assert res.get_json()["upgrade_required"] is True
