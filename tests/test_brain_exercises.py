"""
Adaptive Brain Exercises -- unit + route tests.

Covers the deterministic exercise engine in ml/brain_exercises.py: answer
ground-truth never leaking to the client, server-side scoring (including
the heuristic gratitude scan), difficulty-tier adaptation, streak
calculation, cross-user ownership isolation, GDPR export redaction, and
the /api/brain/* route flow with CSRF enabled.
"""
from datetime import datetime, timedelta, timezone

import pytest

import json

import ml.brain_exercises as be
from database.db import export_user_data, get_brain_exercise_attempt, get_db


def _start_plan(app, user_id, plan_type="anxiety"):
    from ml.recovery_plans import start_plan
    with app.app_context():
        return start_plan(user_id, plan_type)


def _backdate_plan(app, plan_id, days=4):
    with app.app_context():
        past = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        db = get_db()
        db.execute("UPDATE recovery_plans SET started_at = ? WHERE id = ?", (past, plan_id))
        db.commit()


_MCQ_KINDS = ("reframe", "worry_reality", "night_reset", "urge_breaker")


def _correct_response(ex, user_id=None):
    """Derives the right answer from the PUBLIC prompt, the same way an
    honest user who actually does the task would, for the kinds where the
    answer follows deterministically from what's shown. For the
    multiple-choice kinds the correct index is server-only ground truth
    (that's the point -- it must never leak to the client), so tests peek
    at the stored attempt row directly, the same way a test double-checks
    a database write."""
    kind = ex["kind"]
    inp = ex["input"]
    if kind == "attention":
        return sum(1 for c in inp["sequence"] if c == inp["target"])
    if kind == "working_memory":
        probe = inp["question"].split('"')[1]
        return inp["items"][inp["items"].index(probe) + 1]
    if kind == "updating":
        return max(inp["sequence"])
    if kind in _MCQ_KINDS:
        assert user_id is not None, "MCQ kinds need user_id to peek at the stored answer"
        attempt = get_brain_exercise_attempt(ex["attempt_id"], user_id)
        return json.loads(attempt["prompt_json"])["answer"]
    raise AssertionError(f"No helper for kind {kind}")


def _any_response(ex):
    """Submits a syntactically-valid response for ANY kind -- the score
    doesn't matter to the streak tests, only that the attempt is recorded."""
    kind = ex["kind"]
    if kind in _MCQ_KINDS:
        return -1  # never a valid option index, so always scored wrong
    if kind == "gratitude_scan":
        return "family"
    if kind == "working_memory":
        return "not-a-real-word"
    if kind in ("attention", "updating"):
        return 0
    raise AssertionError(f"No helper for kind {kind}")


def _score_day(user_id, plan_id, day):
    ex = be.get_or_create_today_exercise(user_id, plan_id, day)
    return be.submit_attempt(user_id, ex["attempt_id"], _any_response(ex))


# ---- engine: issue + secrecy -----------------------------------------------

def test_today_exercise_created_and_reused(app, make_user):
    user_id = make_user()
    plan = _start_plan(app, user_id)
    with app.app_context():
        first = be.get_or_create_today_exercise(user_id, plan["id"], 1)
        second = be.get_or_create_today_exercise(user_id, plan["id"], 1)
    assert first["attempt_id"] == second["attempt_id"]
    assert first["kind"] in be.KINDS
    assert "answer" not in first
    assert "scoring" not in first


def test_today_exercise_none_for_finished_plan(app, make_user):
    user_id = make_user()
    plan = _start_plan(app, user_id)
    with app.app_context():
        get_db().execute(
            "UPDATE recovery_plans SET status = 'completed' WHERE id = ?", (plan["id"],)
        )
        get_db().commit()
        assert be.get_or_create_today_exercise(user_id, plan["id"], 1) is None


def test_today_exercise_rejects_foreign_plan(app, make_user):
    owner = make_user()
    outsider = make_user()
    plan = _start_plan(app, owner)
    with app.app_context():
        with pytest.raises(be.BrainError) as e:
            be.get_or_create_today_exercise(outsider, plan["id"], 1)
        assert e.value.status == 404


def test_today_exercise_rejects_out_of_range_day(app, make_user):
    user_id = make_user()
    plan = _start_plan(app, user_id)  # 7-day plan
    with app.app_context():
        with pytest.raises(be.BrainError):
            be.get_or_create_today_exercise(user_id, plan["id"], 8)


# ---- engine: scoring -------------------------------------------------------

def test_submit_correct_answer_scores_full(app, make_user):
    user_id = make_user()
    plan = _start_plan(app, user_id)
    with app.app_context():
        ex = be.get_or_create_today_exercise(user_id, plan["id"], 1)
        result = be.submit_attempt(user_id, ex["attempt_id"], _correct_response(ex, user_id))
    assert result["correct"] is True
    assert result["score"] == result["max_score"] == 1


def test_submit_wrong_answer_scores_zero_and_reveals_preview(app, make_user):
    user_id = make_user()
    plan = _start_plan(app, user_id)
    with app.app_context():
        ex = be.get_or_create_today_exercise(user_id, plan["id"], 1)
        result = be.submit_attempt(user_id, ex["attempt_id"], -999)
    assert result["correct"] is False
    assert result["score"] == 0
    assert result["answer_preview"]


def test_submit_is_idempotent(app, make_user):
    user_id = make_user()
    plan = _start_plan(app, user_id)
    with app.app_context():
        ex = be.get_or_create_today_exercise(user_id, plan["id"], 1)
        first = be.submit_attempt(user_id, ex["attempt_id"], _correct_response(ex, user_id))
        replay = be.submit_attempt(user_id, ex["attempt_id"], "totally wrong")
        assert replay["score"] == first["score"]
        assert replay["correct"] is True
        assert get_db().execute(
            "SELECT COUNT(*) AS n FROM brain_exercise_attempts WHERE user_id = ?",
            (user_id,),
        ).fetchone()["n"] == 1


def test_ownership_isolation(app, make_user):
    alice = make_user()
    bob = make_user()
    plan = _start_plan(app, alice)
    with app.app_context():
        ex = be.get_or_create_today_exercise(alice, plan["id"], 1)
        with pytest.raises(be.BrainError) as e:
            be.submit_attempt(bob, ex["attempt_id"], 0)
        assert e.value.status == 404


def test_reframe_scoring_picks_balanced_option():
    prompt = {
        "kind": "reframe",
        "input": {"options": ["unbalanced A", "unbalanced B", "balanced one"]},
        "answer": 2,
        "scoring": {"max_score": 1},
    }
    good = be.score_exercise(prompt, 2)
    bad = be.score_exercise(prompt, 0)
    assert good["correct"] is True and good["score"] == 1
    assert bad["correct"] is False
    assert bad["answer_preview"] == "balanced one"


def test_gratitude_scan_heuristic_scoring():
    prompt = {
        "kind": "gratitude_scan",
        "input": {"min_items": 3, "min_words": 4},
        "answer": None,
        "scoring": {"max_score": 3},
    }
    response = (
        "the way the rain stopped right as I reached the bus stop\n"
        "family\n"
        "stuff\n"
        "A genuinely calm first coffee while the house was still quiet"
    )
    result = be.score_exercise(prompt, response)
    assert result["score"] == 2
    assert result["max_score"] == 3
    assert result["correct"] is False

    empty = be.score_exercise(prompt, "")
    assert empty["score"] == 0


# ---- engine: adaptation + progress -----------------------------------------

def test_tier_increases_after_strong_score(app, make_user):
    user_id = make_user()
    plan = _start_plan(app, user_id)  # manual plans start at stage/tier 1
    with app.app_context():
        ex1 = be.get_or_create_today_exercise(user_id, plan["id"], 1)
        assert ex1["difficulty_tier"] == 1
        be.submit_attempt(user_id, ex1["attempt_id"], _correct_response(ex1, user_id))
        ex2 = be.get_or_create_today_exercise(user_id, plan["id"], 1)
    assert ex2["attempt_id"] != ex1["attempt_id"]
    assert ex2["difficulty_tier"] == 2
    assert ex2["last"]["score"] == 1


def test_streak_counts_consecutive_scored_days(app, make_user):
    user_id = make_user()
    plan = _start_plan(app, user_id)
    _backdate_plan(app, plan["id"], days=4)  # current_day becomes 5
    with app.app_context():
        for d in (3, 4, 5):
            _score_day(user_id, plan["id"], d)
        progress = be.get_progress(user_id, plan["id"])
    assert progress["streak"] == 3
    assert progress["days"]["5"]["state"] == "done"
    assert progress["days"]["5"]["score"] is not None


def test_streak_breaks_on_gap(app, make_user):
    user_id = make_user()
    plan = _start_plan(app, user_id)
    _backdate_plan(app, plan["id"], days=4)  # current_day = 5
    with app.app_context():
        _score_day(user_id, plan["id"], 3)
        _score_day(user_id, plan["id"], 5)  # gap at day 4 breaks the run
        progress = be.get_progress(user_id, plan["id"])
    assert progress["streak"] == 1


# ---- GDPR export -----------------------------------------------------------

def test_export_redacts_answer_key(app, make_user):
    user_id = make_user()
    plan = _start_plan(app, user_id)
    with app.app_context():
        _score_day(user_id, plan["id"], 1)
        data = export_user_data(user_id)
    rows = data["brain_exercise_attempts"]
    assert len(rows) == 1
    assert "answer" not in rows[0]["prompt_json"]
    assert "scoring" not in rows[0]["prompt_json"]
    assert rows[0]["score"] == 0


# ---- plan -> exercise mapping ----------------------------------------------
# The core product bug this suite guards against: exercises used to cycle
# through all five internal kinds by day number regardless of which
# recovery plan they belonged to, so two different plans could surface the
# identical exercise. Each plan type must now get its own, fixed,
# genuinely distinct exercise kind.

def test_each_plan_type_maps_to_its_own_distinct_kind(app, make_user):
    expected = {
        "self_esteem": "reframe",
        "anxiety": "worry_reality",
        "sleep": "night_reset",
        "exam_stress": "working_memory",
        "digital_detox": "urge_breaker",
    }
    assert set(expected.values()) == set(be.PLAN_KIND_MAP.values()), \
        "every plan type must map to a distinct kind"
    for plan_type, expected_kind in expected.items():
        user_id = make_user()
        plan = _start_plan(app, user_id, plan_type=plan_type)
        with app.app_context():
            ex = be.get_or_create_today_exercise(user_id, plan["id"], 1)
        assert ex["kind"] == expected_kind, f"{plan_type} should issue {expected_kind}, got {ex['kind']}"


def test_plan_mapping_stable_across_days_and_attempts(app, make_user):
    """A plan's exercise kind must not drift across different days or
    after re-issuing following a scored attempt -- the kind is a property
    of the plan type, not of the day number or attempt count."""
    user_id = make_user()
    plan = _start_plan(app, user_id, plan_type="sleep")
    with app.app_context():
        ex_day1 = be.get_or_create_today_exercise(user_id, plan["id"], 1)
        be.submit_attempt(user_id, ex_day1["attempt_id"], 0)
        ex_day1_again = be.get_or_create_today_exercise(user_id, plan["id"], 1)
        ex_day2 = be.get_or_create_today_exercise(user_id, plan["id"], 2)
    assert ex_day1["kind"] == "night_reset"
    assert ex_day1_again["kind"] == "night_reset"
    assert ex_day2["kind"] == "night_reset"


def test_public_titles_match_required_product_names(app, make_user):
    """Each plan surfaces the exact product-facing exercise name from the
    spec, not a raw internal kind key with underscores."""
    expected_titles = {
        "self_esteem": "Inner Critic Battle",
        "anxiety": "Worry vs Reality",
        "sleep": "Night Mind Reset",
        "exam_stress": "Memory Arena",
        "digital_detox": "Urge Breaker",
    }
    for plan_type, title in expected_titles.items():
        u = make_user()
        plan = _start_plan(app, u, plan_type=plan_type)
        with app.app_context():
            ex = be.get_or_create_today_exercise(u, plan["id"], 1)
        assert ex["title"] == title
        assert ex["title"] not in be.KINDS  # never the bare internal key


def test_mcq_kinds_never_expose_answer_or_scoring_to_client(app, make_user):
    for plan_type, kind in be.PLAN_KIND_MAP.items():
        if kind not in _MCQ_KINDS:
            continue
        u = make_user()
        plan = _start_plan(app, u, plan_type=plan_type)
        with app.app_context():
            ex = be.get_or_create_today_exercise(u, plan["id"], 1)
        assert "answer" not in ex
        assert "scoring" not in ex
        assert "options" in ex["input"]


# ---- route flow ------------------------------------------------------------

def test_api_flow(app, client, login, make_user):
    user_id = make_user()
    login(user_id)

    progress_resp = client.get("/api/brain/progress")
    assert progress_resp.status_code == 200
    progress = progress_resp.get_json()
    assert progress["ok"] is True

    today = client.get("/api/brain/today?day_number=1")
    assert today.status_code == 200
    ex = today.get_json()["exercise"]
    assert ex is not None
    assert "answer" not in today.get_data(as_text=True)

    with app.app_context():
        correct = _correct_response(ex, user_id)
    submit = client.post(
        f"/api/brain/attempts/{ex['attempt_id']}/submit", json={"response": correct}
    )
    assert submit.status_code == 200
    result = submit.get_json()["result"]
    assert result["correct"] is True

    progress2 = client.get("/api/brain/progress").get_json()
    assert progress2["progress"]["days"]["1"]["state"] == "done"
    assert progress2["progress"]["best_percent"] == 100


def test_api_submit_rejects_other_users_attempt(app, client, login, make_user):
    alice = make_user()
    bob = make_user()
    with app.app_context():
        plan = _start_plan(app, alice)
        ex = be.get_or_create_today_exercise(alice, plan["id"], 1)
        attempt_id = ex["attempt_id"]
    login(bob)
    resp = client.post(f"/api/brain/attempts/{attempt_id}/submit", json={"response": 1})
    assert resp.status_code == 404
