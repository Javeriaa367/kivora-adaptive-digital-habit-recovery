"""
spec section 20 -- Consolidation:
    * duplicate memories merged

spec's own example:
    "User gets stressed during exams." + "User experiences stress during
    examination periods." -> one reinforced memory, not two.
"""
from database.db import get_active_memory_facts
from ml.memory import _upsert_fact, update_memory_from_entry


def test_near_duplicate_facts_merge_into_one(app, make_user):
    """Uses ml.memory's own similarity threshold (Jaccard word-overlap on
    the SAME fact_type) -- two differently-worded statements about the
    same underlying pattern should reinforce one row, not create a second."""
    user_id = make_user()
    with app.app_context():
        id1, status1 = _upsert_fact(user_id, "stressor", "stressed about exams", 0.6, "journal")
        id2, status2 = _upsert_fact(user_id, "stressor", "gets stressed during exams", 0.6, "journal")

        facts = get_active_memory_facts(user_id, fact_type="stressor")

    assert status1 == "created"
    assert status2 == "reinforced"
    assert id1 == id2
    assert len(facts) == 1
    assert facts[0]["occurrence_count"] == 2


def test_genuinely_different_facts_of_same_type_stay_separate(app, make_user):
    """Consolidation must not over-merge -- two unrelated stressors of the
    same type shouldn't collapse into one memory."""
    user_id = make_user()
    with app.app_context():
        _upsert_fact(user_id, "stressor", "stressed about exams", 0.6, "journal")
        _upsert_fact(user_id, "stressor", "conflict with a close relationship as an emotional trigger", 0.6, "journal")
        facts = get_active_memory_facts(user_id, fact_type="stressor")

    assert len(facts) == 2


def test_repeated_journal_entries_consolidate_via_full_pipeline(app, make_user):
    """End-to-end through update_memory_from_entry() (the real entry point
    called from routes/journal.py on every save), using the deterministic
    fallback rules -- no Gemini key needed for this to be meaningful, since
    the fallback rules produce identical fact text for matching entries."""
    user_id = make_user()
    with app.app_context():
        update_memory_from_entry(user_id, "I'm really stressed because of my upcoming exam.")
        update_memory_from_entry(user_id, "Another exam is coming up and I'm stressed again.")
        facts = get_active_memory_facts(user_id, fact_type="stressor")

    assert len(facts) == 1
    assert facts[0]["occurrence_count"] == 2


def test_new_journal_submission_populates_memory_endpoints(client, make_user, login):
    """The real POST path passes fresh text directly into memory extraction."""
    user_id = make_user()
    login(user_id)

    response = client.post("/api/journal", json={"entry_text": "I can't sleep because exams are stressing me out."})

    assert response.status_code == 200
    facts = client.get("/api/memory/facts").get_json()
    insight = client.get("/api/memory/insights").get_json()
    assert facts["total_active_facts"] >= 2
    assert facts["facts_by_type"]["sleep_pattern"]
    assert facts["facts_by_type"]["stressor"]
    assert insight["source"] != "insufficient_data"


def test_confidence_increases_on_reinforcement_but_is_capped(app, make_user):
    user_id = make_user()
    with app.app_context():
        fact_id, _ = _upsert_fact(user_id, "goal", "wants to improve sleep", 0.6, "journal")
        for _ in range(20):  # far more than enough to hit the 0.98 ceiling
            _upsert_fact(user_id, "goal", "wants to improve sleep", 0.6, "journal")
        facts = get_active_memory_facts(user_id, fact_type="goal")

    assert facts[0]["confidence"] <= 0.98
