"""
spec section 20 -- Gemini failure:
    * application continues functioning gracefully

Covers extraction, pattern-insight generation, and -- since this session
added memory-awareness to the AI Companion/chat -- the chatbot endpoints
that now also depend on ml.memory under the hood.
"""
from database.db import insert_memory_fact
from ml.memory import extract_facts_from_entry, generate_pattern_insight


def _raise(*args, **kwargs):
    raise RuntimeError("simulated Gemini outage")


def test_extraction_survives_gemini_raising(app, fake_gemini):
    fake_gemini("ml.memory", _raise)
    facts = extract_facts_from_entry("I can't sleep, my exam is tomorrow.")
    assert isinstance(facts, list)
    assert any(f["type"] == "sleep_pattern" for f in facts)


def test_pattern_insight_survives_gemini_raising(app, make_user, fake_gemini):
    user_id = make_user()
    with app.app_context():
        insert_memory_fact(user_id, "stressor", "stressed about exams", "stressed exams", 0.6, "journal")
        insert_memory_fact(user_id, "stressor", "stressed about exams", "stressed exams", 0.6, "journal")
        fake_gemini("ml.memory", _raise)
        result = generate_pattern_insight(user_id)

    assert result["source"] == "fallback"
    assert isinstance(result["insight"], str)
    assert len(result["insight"]) > 0


def test_chat_endpoint_survives_gemini_raising(app, make_user, client, login, fake_gemini):
    user_id = make_user()
    login(user_id)
    fake_gemini("ml.chatbot", _raise)

    res = client.post("/api/chat", json={"message": "I'm feeling stressed about exams"})

    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["reply"]
    assert data["stubbed"] is True
    assert "error" in data


def test_companion_endpoint_survives_gemini_raising(app, make_user, client, login, fake_gemini):
    user_id = make_user()
    login(user_id)
    fake_gemini("ml.chatbot", _raise)

    res = client.post("/api/companion/send", json={"message": "Why can't I sleep lately?"})

    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["reply"]


def test_companion_survives_memory_retrieval_itself_failing(app, make_user, client, login, fake_gemini, monkeypatch):
    """Even if the memory subsystem itself throws (DB hiccup, etc.) while
    building the memory-aware prompt, the companion must still reply. Gemini
    itself is wired to work normally here -- only the memory lookup is
    broken -- to isolate that the outer try/except in
    get_companion_response() is what catches this, not luck."""
    user_id = make_user()
    login(user_id)
    fake_gemini("ml.chatbot", lambda *a, **k: type("R", (), {"text": "a normal reply"})())

    def _boom(user_id):
        raise RuntimeError("simulated memory subsystem failure")

    monkeypatch.setattr("ml.memory.get_memory_prompt_block", _boom)

    res = client.post("/api/companion/send", json={"message": "hello"})
    assert res.status_code == 200
    assert res.get_json()["ok"] is True


def test_journal_submission_survives_gemini_raising_during_extraction(app, make_user, client, login, fake_gemini):
    """The journal save path calls update_memory_from_entry() synchronously
    -- a Gemini failure there must not break saving the entry itself."""
    user_id = make_user()
    login(user_id)
    fake_gemini("ml.memory", _raise)

    res = client.post("/api/journal", json={"entry_text": "Feeling okay today, nothing much going on."})

    assert res.status_code == 200
    assert res.get_json()["ok"] is True
