"""
Shared fixtures for the Long-Term AI Memory test suite (spec section 20).

Every test gets its own throwaway sqlite file (tmp_path), so tests never
share state or touch a developer's real app.db. Gemini is never called for
real in this suite -- tests either run with GEMINI_API_KEY unset (exercises
the deterministic fallback path, same as a fresh install with no key) or
monkeypatch ml.chatbot.get_gemini_client with a fake client to test the
Gemini-configured paths (malformed JSON, API failures) without a network
call or the google-genai package being installed.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config as BaseConfig  # noqa: E402


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Belt-and-suspenders: make sure no real key leaks into a test that
    # expects the fallback path, regardless of the environment running
    # this suite.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("ml.chatbot.GEMINI_API_KEY", None)
    monkeypatch.setattr("ml.memory.GEMINI_API_KEY", None)

    # The companion send-message rate limiter is a module-level dict keyed
    # by user_id -- reset it per test so unrelated tests (which often
    # reuse the same low user ids against a fresh per-test database) never
    # inherit hit counts from an earlier test in the same pytest process.
    import routes.companion as _companion_module
    _companion_module._rate_limit_hits.clear()

    class TestConfig(BaseConfig):
        TESTING = True
        SECRET_KEY = "test-secret"
        DATABASE_PATH = str(tmp_path / "test.db")
        # The app's CSRF protection is always on (see security.py); tests
        # exercise it for real via the `client` fixture, which attaches a
        # session token to every POST. Keep SESSION_COOKIE_SECURE off so the
        # http:// test client can carry the session cookie.
        SESSION_COOKIE_SECURE = False

    from app import create_app
    application = create_app(TestConfig)
    yield application


@pytest.fixture
def client(app):
    """Test client that auto-attaches the CSRF token to every POST, the
    same way the browser does via the X-CSRF-Token header (base.html). A
    token is minted into the session if one isn't there yet, so tests can
    POST straight away -- and CSRF stays genuinely enabled in tests."""
    base = app.test_client()
    import secrets as _secrets

    def _ensure_token() -> str:
        with base.session_transaction() as sess:
            if "csrf_token" not in sess:
                sess["csrf_token"] = _secrets.token_urlsafe(32)
            return sess["csrf_token"]

    def _post(*args, **kwargs):
        token = _ensure_token()
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("X-CSRF-Token", token)
        kwargs["headers"] = headers
        return base.post(*args, **kwargs)

    class _Client:
        def __getattr__(self, name):
            if name == "post":
                return _post
            return getattr(base, name)

    return _Client()


@pytest.fixture
def make_user(app):
    """Factory fixture: make_user() -> user_id. Call multiple times per
    test for multi-user (security/isolation) scenarios."""
    from database.db import create_user
    counter = {"n": 0}

    def _make(email: str | None = None, name: str = "Test User"):
        counter["n"] += 1
        email = email or f"user{counter['n']}@example.com"
        with app.app_context():
            row = create_user(name, email, "not-a-real-password")
            return row["id"]

    return _make


@pytest.fixture
def login(client):
    """login(user_id) sets the session cookie the same way auth_utils'
    login_user() does, without going through the real login form/route."""
    def _login(user_id: int):
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
    return _login


class FakeGeminiResponse:
    def __init__(self, text):
        self.text = text


class FakeGeminiModels:
    """Stands in for client.models -- generate_content is monkeypatched
    per-test to return a canned response or raise, to simulate malformed
    output or an outright Gemini API failure without any network access."""
    def __init__(self, behavior):
        self._behavior = behavior  # callable(model, contents, config=None) -> FakeGeminiResponse

    def generate_content(self, model=None, contents=None, config=None):
        return self._behavior(model, contents, config)


class FakeGeminiClient:
    def __init__(self, behavior):
        self.models = FakeGeminiModels(behavior)


@pytest.fixture
def fake_gemini(monkeypatch, app):
    """fake_gemini(module, behavior_fn) wires GEMINI_API_KEY "on" for the
    given ml module (ml.chatbot / ml.memory each hold their own imported
    copy of the constant) and swaps in a FakeGeminiClient so the
    Gemini-configured code path runs against a controlled fake instead of
    the real API."""
    def _wire(module, behavior_fn):
        monkeypatch.setattr(f"{module}.GEMINI_API_KEY", "fake-key-for-tests")
        monkeypatch.setattr(f"{module}.get_gemini_client", lambda: FakeGeminiClient(behavior_fn))
    return _wire
