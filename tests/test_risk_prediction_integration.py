"""A successful check-in must refresh the persisted Risk Insights snapshot."""

from database.db import get_risk_history

def test_prediction_refreshes_risk_snapshot(client, make_user, login, monkeypatch, app):
    user_id = make_user()
    login(user_id)

    monkeypatch.setattr("routes.api.predict_all", lambda form: {
        "addiction_risk_flag": {"label": "At-risk", "confidence": 0.8},
        "wellbeing_score": {"value": 4.0},
        "wellbeing_risk_flag": {"label": "Below median", "confidence": 0.7},
    })
    monkeypatch.setattr("routes.api.user_facing_results", lambda results: results)
    monkeypatch.setattr("routes.api.get_recommendations", lambda results: [])
    monkeypatch.setattr("routes.api.generate_wellness_report", lambda results: {"report": "ok", "source": "rule_based"})
    monkeypatch.setattr("routes.api.explain_all", lambda form: {})
    monkeypatch.setattr("ml.risk_engine.GEMINI_API_KEY", None)

    response = client.post("/api/predict", json={"Daily_Usage_Hours": "6"})

    assert response.status_code == 200
    assert len(response.get_json()["risk_profile"]) == 5
    with app.app_context():
        assert len(get_risk_history(user_id)) == 5

    profile_response = client.get("/api/risk/profile")
    trend_response = client.get("/api/risk/trend")
    assert profile_response.status_code == 200
    assert profile_response.get_json()["ok"] is True
    assert trend_response.status_code == 200
    assert all(trend_response.get_json()["trend"][category] for category in response.get_json()["risk_profile"])
