"""
Durable-persistence tests (database/persistence.py).

The core scenario these tests simulate is Cloud Run's redeploy: the
container's local filesystem is replaced (our app.db simply vanishes) and
a fresh process boots. With persistence configured, the boot-time restore
must pull the newest backup back down so all user data survives intact.
"""
import sqlite3

import pytest


def _config(tmp_path, **overrides):
    from config import Config as BaseConfig

    class PersistenceConfig(BaseConfig):
        TESTING = True
        SECRET_KEY = "test-secret"
        SESSION_COOKIE_SECURE = False
        DATABASE_PATH = str(tmp_path / "app.db")
        PERSISTENCE_BACKUP_DIR = str(tmp_path / "backups")
        PERSISTENCE_BACKUP_INTERVAL = 0

    for key, value in overrides.items():
        setattr(PersistenceConfig, key, value)
    return PersistenceConfig


def _boot(tmp_path, **overrides):
    from app import create_app
    return create_app(_config(tmp_path, **overrides))


def _wipe_database(tmp_path):
    """Simulate Cloud Run replacing the ephemeral filesystem."""
    for f in list(tmp_path.iterdir()):
        if f.name.startswith("app.db"):
            f.unlink()
    assert not (tmp_path / "app.db").exists()


def _backup_files(tmp_path):
    backups = tmp_path / "backups"
    return sorted(backups.glob("*.bak")) if backups.is_dir() else []


# ---- the headline scenario -------------------------------------------------

def test_data_survives_simulated_redeploy(tmp_path):
    app1 = _boot(tmp_path)
    with app1.app_context():
        from database.db import (
            create_habit, create_user, get_active_memory_facts, get_habits,
            get_journal_entry_count, get_recent_predictions, insert_memory_fact,
            save_journal_entry, save_prediction,
        )
        user = create_user("Durable", "durable@example.com", "password123", consent_given=True)
        uid = user["id"]
        save_journal_entry(uid, "today I noticed I feel calm after a walk", {
            "emotion_label": "Calm", "confidence": 0.8,
            "overall_sentiment": "Positive", "sentiment_score": 0.6,
            "crisis_flag": False,
        })
        insert_memory_fact(uid, "stressors", "User is calmer after walking",
                           "walking calms", 0.8)
        create_habit(uid, "Evening walk")
        save_prediction(uid, {"Daily_Usage_Hours": 4},
                        {"addiction_risk_flag": {"label": "At-risk", "confidence": 0.9}})

    from database.persistence import backup_now
    with app1.app_context():
        assert backup_now(app1) is True

    _wipe_database(tmp_path)

    app2 = _boot(tmp_path)
    with app2.app_context():
        from database.db import get_user_by_email
        restored = get_user_by_email("durable@example.com")
        assert restored is not None
        assert restored["consent_given"] == 1
        facts = get_active_memory_facts(restored["id"], fact_type="stressors")
        assert len(facts) == 1
        assert facts[0]["fact_text"] == "User is calmer after walking"
        assert get_journal_entry_count(restored["id"]) == 1
        assert len(get_habits(restored["id"])) == 1
        assert len(get_recent_predictions(restored["id"])) == 1


def test_restore_uses_newest_backup(tmp_path):
    app = _boot(tmp_path)
    with app.app_context():
        from database.db import create_user
        create_user("First", "first@example.com", "pw")

    from database.persistence import backup_now
    with app.app_context():
        backup_now(app)

    with app.app_context():
        from database.db import create_user
        create_user("Second", "second@example.com", "pw")
    with app.app_context():
        backup_now(app)

    _wipe_database(tmp_path)

    app2 = _boot(tmp_path)
    with app2.app_context():
        from database.db import get_user_by_email
        assert get_user_by_email("first@example.com") is not None
        assert get_user_by_email("second@example.com") is not None


# ---- edge cases -----------------------------------------------------------

def test_fresh_boot_without_backup_starts_empty(tmp_path):
    app = _boot(tmp_path)
    with app.app_context():
        from database.db import get_user_by_email
        assert get_user_by_email("nobody@example.com") is None
        conn = sqlite3.connect(app.config["DATABASE_PATH"])
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
        assert count == 0


def test_backup_file_is_a_valid_consistent_snapshot(tmp_path):
    app = _boot(tmp_path)
    with app.app_context():
        from database.db import create_user, save_journal_entry
        u = create_user("Snap", "snap@example.com", "pw")
        save_journal_entry(u["id"], "snapshot check", {
            "emotion_label": "Calm", "confidence": 0.9,
            "overall_sentiment": "Positive", "sentiment_score": 0.7,
            "crisis_flag": False,
        })

    from database.persistence import backup_now
    with app.app_context():
        assert backup_now(app) is True

    files = _backup_files(tmp_path)
    assert files, "expected at least one backup object"
    conn = sqlite3.connect(str(files[-1]))
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    journals = conn.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]
    conn.close()
    assert users == 1 and journals == 1


def test_after_request_backs_up_latest_writes(tmp_path):
    app = _boot(tmp_path)
    with app.app_context():
        from database.db import create_user
        create_user("Hook", "hook@example.com", "pw")
    before = len(_backup_files(tmp_path))

    client = app.test_client()
    resp = client.get("/")  # any request fires the after-request backup hook
    assert resp.status_code == 200
    assert len(_backup_files(tmp_path)) > before

    newest = _backup_files(tmp_path)[-1]
    conn = sqlite3.connect(str(newest))
    row = conn.execute("SELECT email FROM users WHERE email = 'hook@example.com'").fetchone()
    conn.close()
    assert row is not None


def test_no_persistence_config_is_a_safe_noop(tmp_path):
    # Default config (no PERSISTENCE_BACKUP_*) must keep working with zero
    # backup side effects -- this is the normal local-dev / test path.
    from config import Config as BaseConfig

    class PlainConfig(BaseConfig):
        TESTING = True
        SECRET_KEY = "test-secret"
        SESSION_COOKIE_SECURE = False
        DATABASE_PATH = str(tmp_path / "plain.db")

    from app import create_app
    app = create_app(PlainConfig)
    with app.app_context():
        from database.db import create_user
        create_user("Plain", "plain@example.com", "pw")

    assert not (tmp_path / "backups").exists()


# ---- production fail-closed behavior ---------------------------------------

def test_production_fails_closed_without_persistence_store(tmp_path, monkeypatch):
    from flask import Flask
    from database.persistence import ensure_persistence_configured

    monkeypatch.setenv("FLASK_ENV", "production")

    app = Flask(__name__)
    app.config["PERSISTENCE_BACKUP_BUCKET"] = ""
    app.config["PERSISTENCE_BACKUP_DIR"] = ""
    app.config["TESTING"] = False
    with pytest.raises(RuntimeError):
        ensure_persistence_configured(app)

    app.config["PERSISTENCE_BACKUP_DIR"] = str(tmp_path / "backups")
    ensure_persistence_configured(app)  # with a store configured, no raise
