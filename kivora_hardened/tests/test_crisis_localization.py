"""Tests for crisis-resource localization (audit P1).

The rule that matters: never show a wrong-region phone number. Unknown
countries must get directory links only, and the US numbers (988 / 741741)
must never leak to a non-US user.
"""
import sqlite3

import pytest

from ml.crisis_resources import (
    COUNTRY_RESOURCES, GLOBAL_RESOURCES, SUPPORTED_COUNTRIES,
    crisis_reply_text, crisis_resources_for, crisis_resources_for_user,
    format_resources_for_chat,
)

CRISIS_TEXT = "I've been thinking about suicide and I want to end my life."


def _contact_has_phone(contact: str) -> bool:
    digits = "".join(ch for ch in contact if ch.isdigit())
    return len(digits) >= 3


# ---- unit: resource resolution ---------------------------------------------

def test_every_supported_country_has_resources():
    assert SUPPORTED_COUNTRIES
    for code, _label in SUPPORTED_COUNTRIES:
        assert crisis_resources_for(code), f"{code} must resolve to resources"


def test_us_resources_include_988():
    contacts = " ".join(r["contact"] for r in crisis_resources_for("us"))
    assert "988" in contacts


def test_pakistan_resources_exclude_us_numbers():
    resources = crisis_resources_for("pk")
    contacts = " ".join(r["contact"] for r in resources)
    assert "988" not in contacts and "741741" not in contacts
    assert any("Pakistan" in r["name"] or "Umang" in r["name"] for r in resources)


def test_unknown_or_blank_country_falls_back_to_global():
    for code in (None, "", "zz", "fr", "  "):
        assert crisis_resources_for(code) is GLOBAL_RESOURCES
    # Case-insensitive, so a valid code in any case still resolves.
    assert crisis_resources_for("PK") is COUNTRY_RESOURCES["pk"]
    assert crisis_resources_for("Us") is COUNTRY_RESOURCES["us"]


def test_global_resources_are_directory_links_only():
    for r in GLOBAL_RESOURCES:
        assert r["contact"].startswith("https://"), "no phone numbers in global list"
        assert not _contact_has_phone(r["contact"])


def test_global_fallback_never_contains_a_phone_number():
    for code in (None, "", "zz"):
        for r in crisis_resources_for(code):
            assert not _contact_has_phone(r["contact"]), f"wrong number leaked: {r}"


def test_crisis_reply_text_includes_localized_resources():
    reply = crisis_reply_text("pk")
    assert "Umang" in reply and "988" not in reply
    assert format_resources_for_chat(GLOBAL_RESOURCES) in crisis_reply_text(None)


def test_crisis_resources_for_user_accepts_row_and_dict():
    assert crisis_resources_for_user({"country_code": "pk"}) is COUNTRY_RESOURCES["pk"]
    assert crisis_resources_for_user(None) is GLOBAL_RESOURCES
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT 'gb' AS country_code").fetchone()
    assert crisis_resources_for_user(row) is COUNTRY_RESOURCES["gb"]


# ---- journal API: localized crisis banner -----------------------------------

def _post_crisis_entry(client):
    return client.post("/api/journal", json={"entry_text": CRISIS_TEXT})


def test_journal_crisis_resources_follow_user_country(app, client, make_user, login):
    uid = make_user(email="pk@example.com")
    with app.app_context():
        from database.db import update_country_code
        update_country_code(uid, "pk")
    login(uid)
    res = _post_crisis_entry(client)
    assert res.status_code == 200
    resources = res.get_json()["crisis"]["resources"]
    contacts = " ".join(r["contact"] for r in resources)
    assert any("Umang" in r["name"] for r in resources)
    assert "988" not in contacts and "741741" not in contacts


def test_journal_crisis_resources_us_user_gets_988(app, client, make_user, login):
    uid = make_user(email="us@example.com")
    with app.app_context():
        from database.db import update_country_code
        update_country_code(uid, "us")
    login(uid)
    res = _post_crisis_entry(client)
    resources = res.get_json()["crisis"]["resources"]
    assert "988" in " ".join(r["contact"] for r in resources)


def test_journal_crisis_no_country_gets_directory_only(app, client, make_user, login):
    uid = make_user(email="anon@example.com")  # no country_code set
    login(uid)
    res = _post_crisis_entry(client)
    resources = res.get_json()["crisis"]["resources"]
    assert resources == GLOBAL_RESOURCES
    assert all(r["contact"].startswith("https://") for r in resources)


# ---- signup -------------------------------------------------------------------

def test_signup_persists_country_code(app, client):
    res = client.post("/signup", data={
        "name": "Rania", "email": "rania@example.com", "password": "correct horse",
        "confirm_password": "correct horse", "consent": "on", "country": "pk",
    })
    assert res.status_code == 302
    with app.app_context():
        from database.db import get_user_by_email
        assert get_user_by_email("rania@example.com")["country_code"] == "pk"


def test_signup_rejects_invalid_country(app, client):
    res = client.post("/signup", data={
        "name": "Noor", "email": "noor@example.com", "password": "correct horse",
        "confirm_password": "correct horse", "consent": "on", "country": "zz",
    })
    assert res.status_code == 302
    with app.app_context():
        from database.db import get_user_by_email
        assert get_user_by_email("noor@example.com")["country_code"] is None


def test_signup_page_renders_country_dropdown(app, client):
    res = client.get("/signup")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert 'name="country"' in body and 'value="pk"' in body


# ---- settings ------------------------------------------------------------------

def test_settings_page_renders_country_control(app, client, make_user, login):
    uid = make_user()
    login(uid)
    res = client.get("/settings")
    assert res.status_code == 200
    assert 'id="country-select"' in res.get_data(as_text=True)


def test_settings_updates_country(app, client, make_user, login):
    uid = make_user()
    login(uid)
    res = client.post("/api/account/country", json={"country_code": "in"})
    assert res.status_code == 200 and res.get_json()["ok"] is True
    with app.app_context():
        from database.db import get_user_by_id
        assert get_user_by_id(uid)["country_code"] == "in"


def test_settings_rejects_unknown_country(app, client, make_user, login):
    uid = make_user()
    login(uid)
    res = client.post("/api/account/country", json={"country_code": "zz"})
    assert res.status_code == 400
    with app.app_context():
        from database.db import get_user_by_id
        assert get_user_by_id(uid)["country_code"] is None


def test_settings_country_requires_login(app, client):
    # No user in the session: login_required must redirect before the
    # endpoint runs. (The client fixture supplies the CSRF header.)
    res = client.post("/api/account/country", json={"country_code": "pk"})
    assert res.status_code == 302  # login_required redirect


# ---- migration ------------------------------------------------------------------

def test_country_code_migration_preserves_existing_rows(tmp_path):
    """A pre-localization database (users without country_code) gains the
    column on boot, keeps existing rows, and accepts updates."""
    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
        "email TEXT UNIQUE NOT NULL, password_hash TEXT, created_at TEXT NOT NULL, "
        "is_admin INTEGER NOT NULL DEFAULT 0, plan TEXT NOT NULL DEFAULT 'free', "
        "stripe_customer_id TEXT, stripe_subscription_id TEXT, referral_code TEXT UNIQUE, "
        "referred_by_user_id INTEGER, google_sub TEXT UNIQUE, "
        "consent_given INTEGER NOT NULL DEFAULT 0, consent_at TEXT)"
    )
    conn.execute(
        "INSERT INTO users (name, email, password_hash, created_at) "
        "VALUES ('Legacy', 'legacy@example.com', 'x', '2024-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    from config import Config

    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "t"
        DATABASE_PATH = db_path

    from app import create_app
    app = create_app(TestConfig)  # runs init_db -> _migrate_existing_db

    with app.app_context():
        from database.db import get_user_by_id, update_country_code
        row = get_user_by_id(1)
        assert "country_code" in row.keys()
        assert row["country_code"] is None
        updated = update_country_code(1, "pk")
        assert updated["country_code"] == "pk"
