"""
spec section 20 -- Memory extraction:
    * meaningful memory
    * irrelevant statement
    * malformed Gemini response
"""
from ml.memory import extract_facts_from_entry


def test_meaningful_entry_produces_a_fact(app):
    with app.app_context():
        facts = extract_facts_from_entry("I usually feel stressed during exam weeks.")
    assert len(facts) >= 1
    assert any(f["type"] == "stressor" for f in facts)


def test_irrelevant_statement_produces_no_fact(app):
    """spec's own example of what should NOT become permanent memory."""
    with app.app_context():
        facts = extract_facts_from_entry("I'm tired today.")
    assert facts == []


def test_extraction_never_invents_unrelated_fact_types(app):
    with app.app_context():
        facts = extract_facts_from_entry("Just watered my plants, nothing else going on.")
    assert facts == []


def test_malformed_gemini_json_falls_back_without_crashing(app, fake_gemini):
    """If Gemini returns non-JSON (or garbage), extraction must fall back
    to the deterministic rules instead of raising -- 'robust JSON parsing,
    never let malformed output crash the application' (spec section 5)."""
    fake_gemini("ml.memory", lambda *a, **k: type("R", (), {"text": "not valid json {{{"})())

    facts = extract_facts_from_entry("I can't sleep because of my upcoming exam.")

    assert isinstance(facts, list)
    types = {f["type"] for f in facts}
    assert "sleep_pattern" in types
    assert "stressor" in types


def test_gemini_returning_wrong_shape_never_crashes(app, fake_gemini):
    """Gemini returning valid JSON that isn't the expected array-of-objects
    shape (e.g. a bare string) must degrade gracefully -- no items pass the
    dict/type/text validation, so nothing is trusted and extraction returns
    an empty list rather than raising or accepting garbage."""
    fake_gemini("ml.memory", lambda *a, **k: type("R", (), {"text": '"just a string, not a list"'})())

    facts = extract_facts_from_entry("I went for a run today, felt great.")

    assert facts == []


def test_gemini_empty_response_falls_back(app, fake_gemini):
    fake_gemini("ml.memory", lambda *a, **k: type("R", (), {"text": None})())

    facts = extract_facts_from_entry("I finally finished my big project, proud of myself.")

    assert isinstance(facts, list)
    assert any(f["type"] == "achievement" for f in facts)


def test_extraction_caps_at_four_facts(app):
    """Extraction is bounded regardless of how much a single entry
    matches, so one huge entry can't flood the fact table."""
    text = (
        "I can't sleep, exams are stressing me out, I had a fight with my "
        "roommate, I went for a run, I'm trying to meditate more, and I "
        "finished my thesis today."
    )
    with app.app_context():
        facts = extract_facts_from_entry(text)
    assert len(facts) <= 4
