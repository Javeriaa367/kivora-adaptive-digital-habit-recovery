"""Tests for the honest rule-based rebrand (audit P0, Phase 2).

The product presents deterministic rules + journal memory as its real
engine, and Gemini as an optional enhancement. User-facing surfaces must
not confess "canned responses", advertise "no live AI yet", or pitch an
AI-generated upgrade to the user.
"""
from ml.chatbot import get_chatbot_response, get_companion_response
from ml.faq import answer_faq


def test_dashboard_widget_has_no_stub_label(app, client, make_user, login):
    uid = make_user()
    # A brand-new user with no data is routed to onboarding; give this one a
    # first prediction so the dashboard actually renders.
    with app.app_context():
        from database.db import save_prediction
        save_prediction(uid, {"Daily_Usage_Hours": 4.0}, {
            "addiction_risk_flag": {"label": "Not at-risk", "confidence": 0.9, "at_risk_probability": 0.1},
            "wellbeing_score": {"value": 7.2},
            "wellbeing_risk_flag": {"label": "Above median", "confidence": 0.8},
        })
    login(uid)
    res = client.get("/dashboard")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "Wellness Assistant" in body
    assert "Stub" not in body and "no live AI" not in body


def test_companion_page_has_no_canned_or_gemini_hook(app, client, make_user, login):
    uid = make_user()
    login(uid)
    res = client.get("/companion")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "AI Companion" not in body
    assert "canned" not in body.lower()
    assert "set GEMINI_API_KEY" not in body
    assert "no external AI model" in body  # honest deterministic framing


def test_landing_page_rebranded(app, client):
    body = client.get("/").get_data(as_text=True)
    assert "AI Companion" not in body
    assert "AI Check-Ins" not in body
    assert "honest, explainable analysis" in body
    assert "no live AI" not in body


def test_memory_page_rebranded(app, client, make_user, login):
    uid = make_user()
    login(uid)
    body = client.get("/memory").get_data(as_text=True)
    assert "AI Memory" not in body and "AI memory" not in body


def test_chat_fallback_reply_is_not_self_deprecating():
    result = get_chatbot_response("tell me about the color of your parachute")
    assert result["crisis"] is False
    assert "GEMINI_API_KEY" not in result["reply"]
    assert "canned" not in result["reply"].lower()


def test_companion_fallback_reply_mentions_nothing_canned():
    result = get_companion_response([], "what is 2+2?")
    assert "GEMINI_API_KEY" not in result["reply"]
    assert "canned" not in result["reply"].lower()


def test_faq_fallback_has_no_api_key_confession():
    answer = answer_faq("what is the meaning of life?")["answer"]
    assert "GEMINI_API_KEY" not in answer
    assert "canned" not in answer.lower()
