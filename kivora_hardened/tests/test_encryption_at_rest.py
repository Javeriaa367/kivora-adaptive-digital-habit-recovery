"""
Item 8 (STARTUP_AUDIT correction pass): journal entries and memory facts
must be encrypted at rest. These tests read the raw SQLite bytes directly
(bypassing database/db.py's decrypt-on-read helpers) to prove the
plaintext never actually hits disk, then confirm the normal read path
still returns the original plaintext (decrypt-on-read works).
"""
import os
import sqlite3
import subprocess
import sys

from database.db import (
    get_active_memory_facts,
    get_journal_entries,
    insert_memory_fact,
    save_journal_entry,
)

SECRET_JOURNAL_TEXT = "Relapsed again last night and I feel ashamed about it."
SECRET_FACT_TEXT = "struggles most with late-night urges after work"


def _raw_column_values(db_path, table, column):
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute(f"SELECT {column} FROM {table}").fetchall()]
    finally:
        conn.close()


def test_journal_entry_text_is_encrypted_on_disk(app, make_user):
    user_id = make_user()
    analysis = {
        "emotion_label": "sadness",
        "confidence": 0.8,
        "overall_sentiment": "negative",
        "sentiment_score": -0.5,
        "crisis_flag": False,
    }
    with app.app_context():
        save_journal_entry(user_id, SECRET_JOURNAL_TEXT, analysis)

    raw_values = _raw_column_values(app.config["DATABASE_PATH"], "journal_entries", "entry_text")
    assert raw_values, "expected at least one journal row"
    for raw in raw_values:
        assert SECRET_JOURNAL_TEXT not in raw
        assert raw.startswith("enc:v1:")


def test_journal_entry_decrypts_on_normal_read_path(app, make_user):
    user_id = make_user()
    analysis = {
        "emotion_label": "sadness",
        "confidence": 0.8,
        "overall_sentiment": "negative",
        "sentiment_score": -0.5,
        "crisis_flag": False,
    }
    with app.app_context():
        save_journal_entry(user_id, SECRET_JOURNAL_TEXT, analysis)
        entries = get_journal_entries(user_id)

    assert entries[0]["entry_text"] == SECRET_JOURNAL_TEXT


def test_memory_fact_text_is_encrypted_on_disk(app, make_user):
    user_id = make_user()
    with app.app_context():
        insert_memory_fact(user_id, "stressor", SECRET_FACT_TEXT, SECRET_FACT_TEXT.lower(), 0.7)

    raw_values = _raw_column_values(app.config["DATABASE_PATH"], "memory_facts", "fact_text")
    assert raw_values, "expected at least one memory_facts row"
    for raw in raw_values:
        assert SECRET_FACT_TEXT not in raw
        assert raw.startswith("enc:v1:")


def test_memory_fact_decrypts_on_normal_read_path(app, make_user):
    user_id = make_user()
    with app.app_context():
        insert_memory_fact(user_id, "stressor", SECRET_FACT_TEXT, SECRET_FACT_TEXT.lower(), 0.7)
        facts = get_active_memory_facts(user_id)

    assert facts[0]["fact_text"] == SECRET_FACT_TEXT


def test_production_boot_fails_closed_without_encryption_key():
    """Run in a clean subprocess (not the pytest process) so it doesn't
    disturb config/crypto_fields' already-imported, cached module state
    for every other test in this session -- mirrors how the analogous
    SECRET_KEY fail-closed behavior would need to be exercised."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, FLASK_ENV="production", SECRET_KEY="not-a-real-secret")
    env.pop("ENCRYPTION_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c", "import config"],
        cwd=repo_root, env=env, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "ENCRYPTION_KEY must be set in production" in result.stderr


def test_same_configured_key_decrypts_across_processes(tmp_path):
    """A configured key, unlike the old dev fallback, survives a restart."""
    key = "mPZofEk0Fnj1uxeb1kLTnxVON2sBJ_1UoiiLeDbib_k="
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, ENCRYPTION_KEY=key)
    write = subprocess.run(
        [sys.executable, "-c", "from crypto_fields import encrypt_text; print(encrypt_text('restart-safe'))"],
        cwd=repo_root, env=env, capture_output=True, text=True, check=True,
    )
    token = write.stdout.strip()
    read = subprocess.run(
        [sys.executable, "-c", "import sys; from crypto_fields import decrypt_text; print(decrypt_text(sys.stdin.read().strip()))"],
        cwd=repo_root, env=env, input=token, capture_output=True, text=True, check=True,
    )
    assert read.stdout.strip() == "restart-safe"
