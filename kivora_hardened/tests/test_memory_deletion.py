"""
spec section 20 -- Deletion:
    * individual deletion
    * clear-all functionality

(Cross-user access to these same operations is covered separately in
test_memory_security.py -- this file checks the happy path actually works
and is complete/correct for the owning user.)
"""
from database.db import get_active_memory_facts, get_recent_memory_summaries, insert_memory_fact, insert_memory_summary


def test_delete_single_memory_removes_only_that_one(app, make_user, client, login):
    user_id = make_user()
    with app.app_context():
        keep_id = insert_memory_fact(user_id, "goal", "wants to improve sleep", "wants improve sleep", 0.6, "journal")
        delete_id = insert_memory_fact(user_id, "stressor", "stressed about exams", "stressed exams", 0.6, "journal")

    login(user_id)
    res = client.post(f"/api/memory/facts/{delete_id}/delete")
    assert res.status_code == 200
    assert res.get_json()["ok"] is True

    with app.app_context():
        remaining = get_active_memory_facts(user_id)
    remaining_ids = {f["id"] for f in remaining}
    assert delete_id not in remaining_ids
    assert keep_id in remaining_ids


def test_delete_nonexistent_memory_returns_404(app, make_user, client, login):
    user_id = make_user()
    login(user_id)
    res = client.post("/api/memory/facts/999999/delete")
    assert res.status_code == 404
    assert res.get_json()["ok"] is False


def test_delete_is_idempotent_not_double_counted(app, make_user, client, login):
    """Deleting the same (already-deleted) id again should 404, not error
    or silently 'succeed' a second time."""
    user_id = make_user()
    with app.app_context():
        fact_id = insert_memory_fact(user_id, "habit", "exercises as a coping habit", "exercises coping habit", 0.6, "journal")
    login(user_id)

    first = client.post(f"/api/memory/facts/{fact_id}/delete")
    second = client.post(f"/api/memory/facts/{fact_id}/delete")

    assert first.status_code == 200
    assert second.status_code == 404


def test_clear_all_removes_every_fact_and_summary(app, make_user, client, login):
    user_id = make_user()
    with app.app_context():
        insert_memory_fact(user_id, "goal", "goal one", "goal one", 0.6, "journal")
        insert_memory_fact(user_id, "stressor", "stressor one", "stressor one", 0.6, "journal")
        insert_memory_summary(user_id, "2026-01-01", "2026-01-31", "A summary of January.", 5)

    login(user_id)
    res = client.post("/api/memory/clear")
    assert res.status_code == 200
    assert res.get_json()["deleted"] == 2

    with app.app_context():
        assert get_active_memory_facts(user_id) == []
        assert get_recent_memory_summaries(user_id) == []


def test_clear_all_on_empty_account_is_a_safe_noop(app, make_user, client, login):
    user_id = make_user()
    login(user_id)
    res = client.post("/api/memory/clear")
    assert res.status_code == 200
    assert res.get_json()["deleted"] == 0


def test_manage_endpoint_reflects_deletions(app, make_user, client, login):
    """End-to-end via the actual UI-facing endpoint the memory page reads."""
    user_id = make_user()
    with app.app_context():
        fact_id = insert_memory_fact(user_id, "goal", "wants to improve sleep", "wants improve sleep", 0.6, "journal")
    login(user_id)

    before = client.get("/api/memory/manage").get_json()
    assert before["total"] == 1

    client.post(f"/api/memory/facts/{fact_id}/delete")

    after = client.get("/api/memory/manage").get_json()
    assert after["total"] == 0
