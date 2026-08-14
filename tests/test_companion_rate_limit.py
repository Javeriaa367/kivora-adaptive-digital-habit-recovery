"""Tests for the AI companion endpoint's rate limiter."""
import routes.companion as companion_module


def test_rate_limit_blocks_after_threshold(client, make_user, login):
    login(make_user())
    companion_module._rate_limit_hits.clear()  # isolate from other tests sharing the module-level store

    statuses = []
    for i in range(companion_module._RATE_LIMIT_MAX_MESSAGES + 3):
        r = client.post("/api/companion/send", json={"message": f"hello {i}"})
        statuses.append(r.status_code)

    assert 429 in statuses
    first_429 = statuses.index(429)
    assert first_429 == companion_module._RATE_LIMIT_MAX_MESSAGES
    assert all(s != 429 for s in statuses[:first_429])


def test_rate_limit_is_per_user(client, make_user, login):
    companion_module._rate_limit_hits.clear()
    u1 = make_user()
    login(u1)
    for i in range(companion_module._RATE_LIMIT_MAX_MESSAGES):
        client.post("/api/companion/send", json={"message": f"hi {i}"})

    u2 = make_user()
    login(u2)
    r = client.post("/api/companion/send", json={"message": "fresh user, fresh budget"})
    assert r.status_code != 429


def test_history_is_bounded_and_clipped(client, make_user, login):
    user_id = make_user()
    login(user_id)
    companion_module._rate_limit_hits.clear()

    for i in range(companion_module.MAX_HISTORY_TURNS + 2):
        response = client.post("/api/companion/send", json={"message": "x" * 1000 + str(i)})
        assert response.status_code == 200

    with client.session_transaction() as sess:
        history = sess["companion_history"]

    assert len(history) == companion_module.MAX_HISTORY_TURNS * 2
    assert all(len(turn["text"]) <= companion_module.MAX_HISTORY_MESSAGE_CHARS for turn in history)
