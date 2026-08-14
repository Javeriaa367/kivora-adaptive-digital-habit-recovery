"""
spec section 20 -- Security:
    * User A cannot access User B's memories

Covers every memory route (auth required + per-user scoping), not just
the delete endpoint.
"""
from database.db import insert_memory_fact


def test_unauthenticated_requests_are_redirected(client):
    for path in ("/memory", "/api/memory/insights", "/api/memory/facts", "/api/memory/manage"):
        res = client.get(path)
        # login_required redirects to the login page rather than 200ing
        assert res.status_code in (302, 401, 403), f"{path} did not require auth"


def test_user_b_cannot_see_user_as_facts_via_manage(app, make_user, client, login):
    user_a = make_user()
    user_b = make_user()
    with app.app_context():
        insert_memory_fact(user_a, "goal", "user A's private goal", "user a private goal", 0.6, "journal")

    login(user_b)
    res = client.get("/api/memory/manage")
    data = res.get_json()

    assert res.status_code == 200
    assert data["total"] == 0
    assert "user A's private goal" not in str(data)


def test_user_b_cannot_see_user_as_facts_via_facts_endpoint(app, make_user, client, login):
    user_a = make_user()
    user_b = make_user()
    with app.app_context():
        insert_memory_fact(user_a, "goal", "user A's private goal", "user a private goal", 0.6, "journal")

    login(user_b)
    res = client.get("/api/memory/facts")
    data = res.get_json()

    assert data["total_active_facts"] == 0
    assert "user A's private goal" not in str(data)


def test_user_b_cannot_delete_user_as_fact_by_guessing_id(app, make_user, client, login):
    """The core cross-account attack: user B knows/guesses a fact id that
    belongs to user A and tries to delete it directly."""
    user_a = make_user()
    user_b = make_user()
    with app.app_context():
        fact_id = insert_memory_fact(user_a, "goal", "user A's private goal", "user a private goal", 0.6, "journal")

    login(user_b)
    res = client.post(f"/api/memory/facts/{fact_id}/delete")

    assert res.status_code == 404
    assert res.get_json()["ok"] is False

    # and the fact must genuinely still exist for its real owner
    with app.app_context():
        from database.db import get_active_memory_facts
        remaining = get_active_memory_facts(user_a)
    assert any(f["id"] == fact_id for f in remaining)


def test_user_b_clear_all_does_not_touch_user_a(app, make_user, client, login):
    user_a = make_user()
    user_b = make_user()
    with app.app_context():
        fact_id = insert_memory_fact(user_a, "goal", "user A's private goal", "user a private goal", 0.6, "journal")
        insert_memory_fact(user_b, "goal", "user B's own goal", "user b own goal", 0.6, "journal")

    login(user_b)
    res = client.post("/api/memory/clear")
    assert res.status_code == 200
    assert res.get_json()["deleted"] == 1  # only user B's one fact

    with app.app_context():
        from database.db import get_active_memory_facts
        a_facts = get_active_memory_facts(user_a)
        b_facts = get_active_memory_facts(user_b)
    assert any(f["id"] == fact_id for f in a_facts)
    assert b_facts == []
