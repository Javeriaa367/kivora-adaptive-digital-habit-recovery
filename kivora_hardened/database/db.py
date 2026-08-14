"""
Lightweight database layer on stdlib sqlite3. Avoids a Flask-SQLAlchemy
dependency -- keeps the project installable with just Flask + Werkzeug
if needed, and easy to swap for Postgres later (only this file changes).
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from flask import current_app, g
from werkzeug.security import check_password_hash, generate_password_hash

from crypto_fields import decrypt_text, encrypt_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    created_at TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    plan TEXT NOT NULL DEFAULT 'free',
    premium_until TEXT,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    referral_code TEXT UNIQUE,
    referred_by_user_id INTEGER REFERENCES users(id),
    google_sub TEXT UNIQUE,
    consent_given INTEGER NOT NULL DEFAULT 0,
    consent_at TEXT,
    country_code TEXT
);

CREATE TABLE IF NOT EXISTS prediction_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    results_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_predictions_user ON prediction_records(user_id);

CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    entry_text TEXT NOT NULL,
    emotion_label TEXT NOT NULL,
    confidence REAL NOT NULL,
    overall_sentiment TEXT NOT NULL,
    sentiment_score REAL NOT NULL,
    crisis_flag INTEGER NOT NULL DEFAULT 0,
    input_method TEXT NOT NULL DEFAULT 'text'
);
CREATE INDEX IF NOT EXISTS idx_journal_user ON journal_entries(user_id);
CREATE INDEX IF NOT EXISTS idx_journal_created ON journal_entries(created_at);

CREATE TABLE IF NOT EXISTS habits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_habits_user ON habits(user_id);

CREATE TABLE IF NOT EXISTS habit_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    checkin_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(habit_id, checkin_date)
);
CREATE INDEX IF NOT EXISTS idx_checkins_habit ON habit_checkins(habit_id);

CREATE TABLE IF NOT EXISTS coupons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    discount_percent INTEGER NOT NULL,
    max_uses INTEGER NOT NULL DEFAULT 1,
    uses_count INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coupon_redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coupon_id INTEGER NOT NULL REFERENCES coupons(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    UNIQUE(coupon_id, user_id)
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    rating INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS testimonials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    quote TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscription_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    stripe_event_id TEXT UNIQUE,
    event_type TEXT NOT NULL,
    raw_payload TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    kind TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);

CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    exam_date TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subjects_user ON subjects(user_id);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    due_date TEXT,
    completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assignments_user ON assignments(user_id);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reset_tokens_user ON password_reset_tokens(user_id);

-- Long-Term AI Memory (Feature 1): facts the AI has learned about a user
-- over time (recurring stressors, goals, habits, sleep patterns, triggers,
-- themes, achievements), plus periodic summaries so old raw journal text
-- doesn't have to be replayed into every prompt.
CREATE TABLE IF NOT EXISTS memory_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fact_type TEXT NOT NULL,
    fact_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    confidence REAL NOT NULL DEFAULT 0.6,
    source TEXT NOT NULL DEFAULT 'journal',
    active INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_facts_user ON memory_facts(user_id, active);

CREATE TABLE IF NOT EXISTS memory_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    entry_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_summaries_user ON memory_summaries(user_id);

-- Early Risk Detection (Feature 2): point-in-time computed risk snapshots,
-- one row per category per computation, so trend charts can be drawn.
-- Scores are a transparent heuristic (see ml/risk_engine.py), same honesty
-- standard as the existing churn heuristic in ml/churn.py -- not a trained
-- classifier, since there's no historical risk-outcome label data to train
-- one on.
CREATE TABLE IF NOT EXISTS risk_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    level TEXT NOT NULL,
    score INTEGER NOT NULL,
    reasons_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_risk_snapshots_user ON risk_snapshots(user_id, category, created_at);

-- Personalized Recovery Plans (Feature 3): a plan is one 7/14-day named
-- template (see ml/recovery_plans.py's PLAN_LIBRARY) instantiated for a
-- user, with one row per day in recovery_plan_tasks. Only one plan is
-- 'active' per user at a time -- when it finishes (or is swapped), it's
-- marked 'completed'/'abandoned' and stays in history for the timeline.
CREATE TABLE IF NOT EXISTS recovery_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_type TEXT NOT NULL,
    title TEXT NOT NULL,
    duration_days INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL DEFAULT 'manual',
    started_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recovery_plans_user ON recovery_plans(user_id, status);

-- Activity Engine: each day's task is also an interactive activity. Kept
-- as columns on the existing table (not a new table) since the shape is
-- still one row per plan-day -- activity_type/state/result_json turn that
-- row from a checkbox into a structured, resumable activity. Columns are
-- added via _migrate_existing_db() for pre-existing databases.
CREATE TABLE IF NOT EXISTS recovery_plan_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES recovery_plans(id) ON DELETE CASCADE,
    day_number INTEGER NOT NULL,
    task_text TEXT NOT NULL,
    auto_signal TEXT,
    completed INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    activity_type TEXT NOT NULL DEFAULT 'checkin',
    state TEXT NOT NULL DEFAULT 'not_started',
    started_at TEXT,
    result_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_recovery_tasks_plan ON recovery_plan_tasks(plan_id, day_number);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    with app.app_context():
        # Durable persistence (database/persistence.py): if the local DB
        # file is missing (Cloud Run redeploy wiped the filesystem), pull
        # the newest backup down before creating schema -- a restored DB
        # already has all tables, so the idempotent SCHEMA/migrations
        # below are a no-op on it. No-op when persistence isn't configured.
        from database.persistence import backup_now, maybe_restore_on_boot
        maybe_restore_on_boot(app)

        conn = sqlite3.connect(app.config["DATABASE_PATH"])
        conn.executescript(SCHEMA)
        _migrate_existing_db(conn)
        conn.commit()
        conn.close()

        # Establish a durable baseline after every boot (migrated or
        # restored), so the store always holds a current restore point.
        backup_now(app)
    app.teardown_appcontext(close_db)


def _migrate_existing_db(conn):
    """Adds new user columns to a pre-existing app.db from before the
    business features were added. Safe to run repeatedly -- each ALTER
    is wrapped so an already-migrated DB just skips it."""
    migrations = [
        "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'free'",
        "ALTER TABLE users ADD COLUMN premium_until TEXT",
        "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT",
        "ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT",
        "ALTER TABLE users ADD COLUMN referral_code TEXT",
        "ALTER TABLE users ADD COLUMN referred_by_user_id INTEGER",
        "ALTER TABLE users ADD COLUMN google_sub TEXT",
        # Privacy floor: explicit consent recorded at signup (see
        # routes/auth.py + templates/auth/signup.html). Pre-existing
        # accounts default to 0 until they re-affirm consent on the
        # Settings page.
        "ALTER TABLE users ADD COLUMN consent_given INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN consent_at TEXT",
        # Crisis-resource localization (audit P1) -- the user's country picks
        # which helplines the app shows. NULL/unknown -> directory links only.
        "ALTER TABLE users ADD COLUMN country_code TEXT",
        # Voice Journal (Feature 5) -- tags how the entry was captured so we
        # can measure voice adoption later without touching the analysis
        # pipeline (text is transcribed client-side before it ever reaches
        # this table, so entry_text/emotion/crisis logic is untouched).
        "ALTER TABLE journal_entries ADD COLUMN input_method TEXT NOT NULL DEFAULT 'text'",
        # Hybrid emotion analyzer (lexical + VADER + transformer) -- holds
        # the newer, richer analysis fields (secondary_emotion,
        # sentiment_breakdown, low_confidence, analysis_engine) as a single
        # JSON blob rather than one column each, so future analyzer fields
        # don't require another migration. NULL on rows written before this
        # upgrade -- _journal_row_to_dict() below fills in safe defaults for
        # those so old entries keep rendering exactly as before.
        "ALTER TABLE journal_entries ADD COLUMN analysis_extra TEXT",
        # Activity Engine -- recovery plan days become interactive
        # activities instead of plain checkboxes. Existing rows default to
        # 'checkin' / 'not_started'; backfilled more precisely just below.
        "ALTER TABLE recovery_plan_tasks ADD COLUMN activity_type TEXT NOT NULL DEFAULT 'checkin'",
        "ALTER TABLE recovery_plan_tasks ADD COLUMN state TEXT NOT NULL DEFAULT 'not_started'",
        "ALTER TABLE recovery_plan_tasks ADD COLUMN started_at TEXT",
        "ALTER TABLE recovery_plan_tasks ADD COLUMN result_json TEXT",
    ]
    activity_engine_column_added = False
    for sql in migrations:
        try:
            conn.execute(sql)
            if "activity_type" in sql:
                activity_engine_column_added = True
        except sqlite3.OperationalError:
            pass  # column already exists

    if activity_engine_column_added:
        # This is a genuinely pre-Activity-Engine database (the ALTER for
        # activity_type only succeeds once, the first time this runs
        # against it) -- backfill activity_type/state on its existing rows
        # from what's already stored (task_text/auto_signal/completed),
        # never guessed data. A fresh install never hits this: the table
        # is created via SCHEMA with the columns already present, so the
        # ALTER above fails with "column already exists" and this block
        # is skipped, leaving real activity_type values from
        # create_recovery_plan() untouched.
        rows = conn.execute(
            "SELECT id, task_text, auto_signal, completed FROM recovery_plan_tasks"
        ).fetchall()
        for r in rows:
            inferred = infer_activity_type(r[1], r[2])
            new_state = "completed" if r[3] else "not_started"
            conn.execute(
                "UPDATE recovery_plan_tasks SET activity_type = ?, state = ? WHERE id = ?",
                (inferred, new_state, r[0]),
            )


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---- User operations ----------------------------------------------------
# Each valid referral gives BOTH sides this many Premium days (audit Phase 3
# P2: "make the referral real (both sides get premium days) or delete it").
REFERRAL_PREMIUM_DAYS = 7


def _generate_referral_code(name: str) -> str:
    import secrets
    base = "".join(c for c in name.upper() if c.isalnum())[:6] or "USER"
    return f"{base}{secrets.token_hex(3).upper()}"


def create_user(name: str, email: str, password: str | None, referred_by_code: str | None = None,
                consent_given: bool = False, country_code: str | None = None):
    db = get_db()
    password_hash = generate_password_hash(password) if password else None
    referral_code = _generate_referral_code(name)

    referred_by_user_id = None
    if referred_by_code:
        referrer = db.execute("SELECT id FROM users WHERE referral_code = ?", (referred_by_code,)).fetchone()
        if referrer:
            referred_by_user_id = referrer["id"]

    cur = db.execute(
        """INSERT INTO users (name, email, password_hash, created_at, referral_code,
                              referred_by_user_id, consent_given, consent_at, country_code)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, email, password_hash, _now(), referral_code, referred_by_user_id,
         int(bool(consent_given)), _now() if consent_given else None, country_code),
    )
    new_user_id = cur.lastrowid

    # Referral is real: a valid, non-self-referral code grants both sides
    # Premium days. Grant BEFORE the commit so it's atomic with the signup.
    referral_rewarded = bool(referred_by_user_id and referred_by_user_id != new_user_id)
    if referral_rewarded:
        grant_premium_days(referred_by_user_id, REFERRAL_PREMIUM_DAYS, "referral:referrer")
        grant_premium_days(new_user_id, REFERRAL_PREMIUM_DAYS, "referral:new_user")

    db.commit()
    user = dict(get_user_by_id(new_user_id))
    user["referral_rewarded"] = referral_rewarded
    return user


def grant_premium_days(user_id: int, days: int, source: str):
    """Extends a user's premium entitlement by `days` from today (or from
    their existing premium_until if they're already premium -- so rewards
    stack instead of overwriting). Logs the grant so it's auditable."""
    from datetime import datetime, timedelta, timezone
    db = get_db()
    row = db.execute("SELECT premium_until FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    base = None
    if row["premium_until"]:
        try:
            base = datetime.fromisoformat(row["premium_until"])
        except ValueError:
            base = None
    start = base if (base and base > now) else now
    until = (start + timedelta(days=days)).isoformat()
    db.execute("UPDATE users SET premium_until = ? WHERE id = ?", (until, user_id))
    db.execute(
        "INSERT INTO subscription_events (user_id, event_type, raw_payload, created_at) "
        "VALUES (?, 'premium_grant', ?, ?)",
        (user_id, json.dumps({"days": days, "source": source, "premium_until": until}), _now()),
    )
    db.commit()
    return until


def is_premium_user(user_row) -> bool:
    """A user is premium if they paid (plan == 'premium', Stripe keeps that
    in sync via the webhook) OR they hold a time-boxed grant (referral/
    coupon via premium_until, which outlives any plan column sync).
    Accepts a dict or a sqlite3.Row."""
    from datetime import datetime, timezone
    if not user_row:
        return False
    try:
        plan = user_row["plan"]
        until = user_row["premium_until"]
    except (IndexError, KeyError, TypeError):
        return False
    if plan == "premium":
        return True
    if not until:
        return False
    try:
        return datetime.fromisoformat(until) > datetime.now(timezone.utc)
    except ValueError:
        return False


def is_premium_user_id(user_id: int) -> bool:
    row = get_db().execute("SELECT plan, premium_until FROM users WHERE id = ?", (user_id,)).fetchone()
    return is_premium_user(row)


def get_or_create_google_user(google_sub: str, name: str, email: str):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
    if user:
        return user
    existing_by_email = get_user_by_email(email)
    if existing_by_email:
        db.execute("UPDATE users SET google_sub = ? WHERE id = ?", (google_sub, existing_by_email["id"]))
        db.commit()
        return get_user_by_id(existing_by_email["id"])
    cur = db.execute(
        """INSERT INTO users (name, email, password_hash, created_at, referral_code, google_sub,
                              consent_given, consent_at)
           VALUES (?, ?, NULL, ?, ?, ?, 1, ?)""",
        (name, email, _now(), _generate_referral_code(name), google_sub, _now()),
    )
    db.commit()
    return get_user_by_id(cur.lastrowid)


def get_user_by_email(email: str):
    return get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def get_user_by_id(user_id: int):
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def verify_password(user_row, password: str) -> bool:
    if not user_row["password_hash"]:
        return False  # Google-only account, no password set
    return check_password_hash(user_row["password_hash"], password)


def set_user_consent(user_id: int, consent_given: bool):
    db = get_db()
    db.execute(
        "UPDATE users SET consent_given = ?, consent_at = ? WHERE id = ?",
        (int(bool(consent_given)), _now() if consent_given else None, user_id),
    )
    db.commit()


def update_country_code(user_id: int, country_code: str | None):
    """Set the user's region (lowercase ISO code, or None to clear it).
    Drives which crisis helplines the app shows (see ml/crisis_resources.py)."""
    db = get_db()
    db.execute(
        "UPDATE users SET country_code = ? WHERE id = ?",
        (country_code, user_id),
    )
    db.commit()
    return get_user_by_id(user_id)


# ---- Account deletion / data export (privacy floor) -----------------------
# Every table that stores per-user rows references users(id) with ON DELETE
# CASCADE (see SCHEMA), so deleting the users row wipes all derived data --
# journal entries, predictions, habits + check-ins, memory facts/summaries,
# risk snapshots, recovery plans + tasks, notifications, feedback, student
# subjects/assignments, password reset tokens. The one exception is
# users.referred_by_user_id (no cascade -- a deleted referrer must not nuke
# the people they referred, just sever the link).
def delete_user(user_id: int) -> bool:
    db = get_db()
    row = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return False
    db.execute("UPDATE users SET referred_by_user_id = NULL WHERE referred_by_user_id = ?", (user_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    return True


def export_user_data(user_id: int) -> dict | None:
    """Full machine-readable copy of everything the user owns, for the
    Settings-page "Download my data" action. Deliberately excludes
    password_hash (a credential, not user content); keeps every other
    stored value, parsing JSON blobs back into objects for readability."""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        return None
    account = {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "plan": user["plan"],
        "premium_until": user["premium_until"],
        "is_admin": bool(user["is_admin"]),
        "created_at": user["created_at"],
        "referral_code": user["referral_code"],
        "referred_by_user_id": user["referred_by_user_id"],
        "google_sub": user["google_sub"],
        "consent_given": bool(user["consent_given"]),
        "consent_at": user["consent_at"],
    }

    def rows(sql: str, params=()):
        return [dict(r) for r in db.execute(sql, params).fetchall()]

    def rows_json(sql: str, params=(), json_cols=()):
        out = []
        for r in db.execute(sql, params).fetchall():
            d = dict(r)
            for col in json_cols:
                if d.get(col):
                    try:
                        d[col] = json.loads(d[col])
                    except (TypeError, ValueError):
                        pass
            out.append(d)
        return out

    data = {
        "account": account,
        "exported_at": _now(),
        "prediction_records": rows_json(
            "SELECT created_at, inputs_json, results_json FROM prediction_records "
            "WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,), ("inputs_json", "results_json")),
        "journal_entries": [
            {**d, "entry_text": decrypt_text(d.get("entry_text"))}
            for d in rows_json(
                "SELECT created_at, entry_text, emotion_label, confidence, overall_sentiment, "
                "sentiment_score, crisis_flag, input_method, analysis_extra FROM journal_entries "
                "WHERE user_id = ? ORDER BY created_at ASC",
                (user_id,), ("analysis_extra",))
        ],
        "habits": rows("SELECT id, name, created_at FROM habits WHERE user_id = ?", (user_id,)),
        "habit_checkins": rows(
            "SELECT hc.habit_id, hc.checkin_date, hc.created_at FROM habit_checkins hc "
            "WHERE hc.user_id = ? ORDER BY hc.checkin_date ASC", (user_id,)),
        "memory_facts": [
            {**d, "fact_text": decrypt_text(d.get("fact_text"))}
            for d in rows(
                "SELECT id, fact_type, fact_text, occurrence_count, confidence, source, active, "
                "first_seen, last_seen FROM memory_facts WHERE user_id = ?", (user_id,))
        ],
        "memory_summaries": rows(
            "SELECT period_start, period_end, summary_text, entry_count, created_at "
            "FROM memory_summaries WHERE user_id = ?", (user_id,)),
        "risk_snapshots": rows_json(
            "SELECT category, level, score, reasons_json, created_at FROM risk_snapshots "
            "WHERE user_id = ? ORDER BY created_at ASC", (user_id,), ("reasons_json",)),
        "recovery_plans": rows(
            "SELECT id, plan_type, title, duration_days, status, source, started_at, ends_at, "
            "created_at FROM recovery_plans WHERE user_id = ?", (user_id,)),
        "recovery_plan_tasks": rows(
            "SELECT t.plan_id, t.day_number, t.task_text, t.auto_signal, t.completed, "
            "t.activity_type, t.state, t.started_at, t.completed_at, t.result_json "
            "FROM recovery_plan_tasks t JOIN recovery_plans p ON p.id = t.plan_id "
            "WHERE p.user_id = ?", (user_id,)),
        "notifications": rows(
            "SELECT message, kind, read, created_at FROM notifications WHERE user_id = ?", (user_id,)),
        "feedback": rows(
            "SELECT message, rating, created_at FROM feedback WHERE user_id = ?", (user_id,)),
        "testimonials": rows(
            "SELECT quote, approved, created_at FROM testimonials WHERE user_id = ?", (user_id,)),
        "coupon_redemptions": rows(
            "SELECT c.code, cr.created_at FROM coupon_redemptions cr "
            "JOIN coupons c ON c.id = cr.coupon_id WHERE cr.user_id = ?", (user_id,)),
        "subjects": rows(
            "SELECT id, name, exam_date, created_at FROM subjects WHERE user_id = ?", (user_id,)),
        "assignments": rows(
            "SELECT id, subject_id, title, due_date, completed, created_at FROM assignments "
            "WHERE user_id = ?", (user_id,)),
    }
    return data


# ---- Prediction history ---------------------------------------------------
def save_prediction(user_id: int, inputs: dict, results: dict):
    db = get_db()
    db.execute(
        "INSERT INTO prediction_records (user_id, created_at, inputs_json, results_json) VALUES (?, ?, ?, ?)",
        (user_id, _now(), json.dumps(inputs), json.dumps(results)),
    )
    db.commit()


def get_recent_predictions(user_id: int, limit: int = 5):
    rows = get_db().execute(
        "SELECT * FROM prediction_records WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "created_at": r["created_at"],
            "inputs": json.loads(r["inputs_json"]),
            "results": json.loads(r["results_json"]),
        })
    return out


def get_onboarding_state(user_id: int) -> dict:
    """Data-derived onboarding progress. No flag column needed -- a user is
    "not started" until they have any prediction, journal entry or habit, and
    onboarding is complete once they have both a prediction and an entry."""
    db = get_db()
    preds = db.execute(
        "SELECT COUNT(*) AS c FROM prediction_records WHERE user_id = ?", (user_id,)
    ).fetchone()["c"]
    journals = db.execute(
        "SELECT COUNT(*) AS c FROM journal_entries WHERE user_id = ?", (user_id,)
    ).fetchone()["c"]
    habits = db.execute(
        "SELECT COUNT(*) AS c FROM habits WHERE user_id = ?", (user_id,)
    ).fetchone()["c"]
    return {
        "has_prediction": preds > 0,
        "has_journal": journals > 0,
        "has_habit": habits > 0,
        "started": preds > 0 or journals > 0 or habits > 0,
        "completed": preds > 0 and journals > 0,
    }


# Keys from the analyzer's result dict that get their own extra JSON blob
# (analysis_extra) rather than a dedicated column -- see the migration
# comment above. Anything an analyzer returns beyond the original 5 core
# fields (emotion_label/confidence/overall_sentiment/sentiment_score/
# crisis_flag/scores) lands here automatically, so older analyzers (plain
# lexical, VADER-only, transformer-only) that don't return these keys at
# all just store an empty blob -- no special-casing needed.
_JOURNAL_EXTRA_KEYS = (
    "secondary_emotion", "sentiment_breakdown", "sentiment_breakdown_source",
    "low_confidence", "analysis_engine",
)


# ---- Journal entries --------------------------------------------------
def save_journal_entry(user_id: int, entry_text: str, analysis: dict, input_method: str = "text"):
    db = get_db()
    extra = {k: analysis[k] for k in _JOURNAL_EXTRA_KEYS if k in analysis}
    cur = db.execute(
        """INSERT INTO journal_entries
           (user_id, created_at, entry_text, emotion_label, confidence,
            overall_sentiment, sentiment_score, crisis_flag, input_method,
            analysis_extra)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id, _now(), encrypt_text(entry_text), analysis["emotion_label"],
            analysis["confidence"], analysis["overall_sentiment"],
            analysis["sentiment_score"], int(analysis["crisis_flag"]),
            input_method if input_method in ("text", "voice", "voice_edited") else "text",
            json.dumps(extra) if extra else None,
        ),
    )
    db.commit()
    return get_journal_entry_by_id(cur.lastrowid)


def get_journal_entry_by_id(entry_id: int):
    row = get_db().execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    return _journal_row_to_dict(row) if row else None


def get_journal_entries(user_id: int, limit: int = 30):
    rows = get_db().execute(
        "SELECT * FROM journal_entries WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [_journal_row_to_dict(r) for r in rows]


def get_journal_entries_since(user_id: int, since_iso: str):
    rows = get_db().execute(
        "SELECT * FROM journal_entries WHERE user_id = ? AND created_at >= ? ORDER BY created_at ASC",
        (user_id, since_iso),
    ).fetchall()
    return [_journal_row_to_dict(r) for r in rows]


def _journal_row_to_dict(r):
    extra = {}
    if "analysis_extra" in r.keys() and r["analysis_extra"]:
        try:
            extra = json.loads(r["analysis_extra"])
        except (TypeError, ValueError):
            extra = {}

    d = {
        "id": r["id"],
        "created_at": r["created_at"],
        "entry_text": decrypt_text(r["entry_text"]),
        "emotion_label": r["emotion_label"],
        "confidence": r["confidence"],
        "overall_sentiment": r["overall_sentiment"],
        "sentiment_score": r["sentiment_score"],
        "crisis_flag": bool(r["crisis_flag"]),
        "input_method": r["input_method"] if "input_method" in r.keys() else "text",
        # Defaults below cover entries saved before the hybrid analyzer
        # existed -- they render exactly as a plain-lexical result would.
        "secondary_emotion": None,
        "sentiment_breakdown": None,
        "sentiment_breakdown_source": None,
        "low_confidence": False,
        "analysis_engine": "lexical_only",
    }
    d.update(extra)
    return d


# ---- Dashboard aggregation ---------------------------------------------
def get_dashboard_data(user_id: int, days: int = 30) -> dict:
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    db = get_db()

    journal_rows = db.execute(
        "SELECT created_at, emotion_label, sentiment_score FROM journal_entries "
        "WHERE user_id = ? AND created_at >= ? ORDER BY created_at ASC",
        (user_id, since),
    ).fetchall()

    pred_rows = db.execute(
        "SELECT created_at, results_json FROM prediction_records "
        "WHERE user_id = ? AND created_at >= ? ORDER BY created_at ASC",
        (user_id, since),
    ).fetchall()

    mood_trend = [
        {"date": r["created_at"][:10], "emotion": r["emotion_label"], "sentiment_score": r["sentiment_score"]}
        for r in journal_rows
    ]

    wellbeing_trend = []
    for r in pred_rows:
        results = json.loads(r["results_json"])
        score = results.get("wellbeing_score", {}).get("value")
        if score is not None:
            wellbeing_trend.append({"date": r["created_at"][:10], "wellbeing_score": score})

    emotion_counts = {}
    for r in journal_rows:
        emotion_counts[r["emotion_label"]] = emotion_counts.get(r["emotion_label"], 0) + 1

    avg_sentiment = (
        round(sum(r["sentiment_score"] for r in journal_rows) / len(journal_rows), 3)
        if journal_rows else None
    )
    most_common_emotion = max(emotion_counts, key=emotion_counts.get) if emotion_counts else None

    # Streak: consecutive days with >=1 journal entry, counting backward
    # from today (or from yesterday if today has no entry yet -- so the
    # streak doesn't reset to 0 just because you haven't journaled *yet*
    # today).
    entry_date_set = {r["created_at"][:10] for r in journal_rows}
    streak = 0
    if entry_date_set:
        today = datetime.now(timezone.utc).date()
        cursor = today if today.isoformat() in entry_date_set else today - timedelta(days=1)
        while cursor.isoformat() in entry_date_set:
            streak += 1
            cursor -= timedelta(days=1)

    return {
        "mood_trend": mood_trend,
        "wellbeing_trend": wellbeing_trend,
        "emotion_distribution": emotion_counts,
        "average_sentiment": avg_sentiment,
        "most_common_emotion": most_common_emotion,
        "journal_streak_days": streak,
        "total_journal_entries": len(journal_rows),
        "total_predictions": len(pred_rows),
        "calendar": _build_calendar(journal_rows, days),
    }


def _build_calendar(journal_rows, days: int) -> list[dict]:
    """One entry per day for the last `days` days: {date, count, avg_sentiment}."""
    from datetime import datetime, timedelta, timezone

    by_date = {}
    for r in journal_rows:
        d = r["created_at"][:10]
        by_date.setdefault(d, []).append(r["sentiment_score"])

    today = datetime.now(timezone.utc).date()
    out = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        scores = by_date.get(d, [])
        out.append({
            "date": d,
            "count": len(scores),
            "avg_sentiment": round(sum(scores) / len(scores), 3) if scores else None,
        })
    return out


# ---- Habit Builder -------------------------------------------------------
def create_habit(user_id: int, name: str):
    db = get_db()
    cur = db.execute(
        "INSERT INTO habits (user_id, name, created_at) VALUES (?, ?, ?)",
        (user_id, name, _now()),
    )
    db.commit()
    return cur.lastrowid


def get_habits(user_id: int):
    return get_db().execute(
        "SELECT * FROM habits WHERE user_id = ? ORDER BY created_at ASC", (user_id,)
    ).fetchall()


def checkin_habit(habit_id: int, user_id: int):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    db = get_db()
    # Ownership check
    habit = db.execute("SELECT id FROM habits WHERE id = ? AND user_id = ?", (habit_id, user_id)).fetchone()
    if habit is None:
        return None
    try:
        db.execute(
            "INSERT INTO habit_checkins (habit_id, user_id, checkin_date, created_at) VALUES (?, ?, ?, ?)",
            (habit_id, user_id, today, _now()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        pass  # already checked in today -- idempotent
    return today


def get_habit_status(user_id: int):
    """Habits with today's checked-in status and current streak."""
    from datetime import datetime, timedelta, timezone
    db = get_db()
    habits = get_habits(user_id)
    today = datetime.now(timezone.utc).date()
    out = []
    for h in habits:
        checkins = db.execute(
            "SELECT checkin_date FROM habit_checkins WHERE habit_id = ? ORDER BY checkin_date DESC",
            (h["id"],),
        ).fetchall()
        dates = {c["checkin_date"] for c in checkins}
        checked_today = today.isoformat() in dates
        cursor = today if checked_today else today - timedelta(days=1)
        streak = 0
        while cursor.isoformat() in dates:
            streak += 1
            cursor -= timedelta(days=1)
        out.append({
            "id": h["id"], "name": h["name"], "checked_today": checked_today,
            "streak": streak, "total_checkins": len(dates),
        })
    return out


# ---- Admin / plan management ---------------------------------------------
def set_user_plan(user_id: int, plan: str, stripe_customer_id: str | None = None,
                   stripe_subscription_id: str | None = None):
    db = get_db()
    db.execute(
        "UPDATE users SET plan = ?, stripe_customer_id = COALESCE(?, stripe_customer_id), "
        "stripe_subscription_id = COALESCE(?, stripe_subscription_id) WHERE id = ?",
        (plan, stripe_customer_id, stripe_subscription_id, user_id),
    )
    db.commit()


def get_user_by_stripe_customer(stripe_customer_id: str):
    return get_db().execute(
        "SELECT * FROM users WHERE stripe_customer_id = ?", (stripe_customer_id,)
    ).fetchone()


def log_subscription_event(user_id: int | None, stripe_event_id: str, event_type: str, raw_payload: str):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO subscription_events (user_id, stripe_event_id, event_type, raw_payload, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, stripe_event_id, event_type, raw_payload, _now()),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # duplicate webhook delivery -- Stripe retries, this makes it idempotent


def get_admin_stats():
    db = get_db()
    total_users = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    by_plan = db.execute("SELECT plan, COUNT(*) c FROM users GROUP BY plan").fetchall()
    total_journal = db.execute("SELECT COUNT(*) c FROM journal_entries").fetchone()["c"]
    total_predictions = db.execute("SELECT COUNT(*) c FROM prediction_records").fetchone()["c"]
    crisis_flags = db.execute("SELECT COUNT(*) c FROM journal_entries WHERE crisis_flag = 1").fetchone()["c"]
    recent_users = db.execute(
        "SELECT id, name, email, plan, created_at FROM users ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    return {
        "total_users": total_users,
        "plan_breakdown": {r["plan"]: r["c"] for r in by_plan},
        "total_journal_entries": total_journal,
        "total_predictions": total_predictions,
        "crisis_flags_total": crisis_flags,
        "recent_users": [dict(r) for r in recent_users],
    }


def list_all_users(limit: int = 100):
    rows = get_db().execute(
        "SELECT id, name, email, plan, is_admin, created_at FROM users ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def set_user_admin(user_id: int, is_admin: bool):
    db = get_db()
    db.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id))
    db.commit()


# ---- Coupons --------------------------------------------------------------
def create_coupon(code: str, discount_percent: int, max_uses: int = 1, expires_at: str | None = None):
    db = get_db()
    db.execute(
        "INSERT INTO coupons (code, discount_percent, max_uses, uses_count, expires_at, created_at) "
        "VALUES (?, ?, ?, 0, ?, ?)",
        (code.upper(), discount_percent, max_uses, expires_at, _now()),
    )
    db.commit()


def redeem_coupon(code: str, user_id: int):
    from datetime import datetime, timezone
    db = get_db()
    coupon = db.execute("SELECT * FROM coupons WHERE code = ?", (code.upper(),)).fetchone()
    if coupon is None:
        return {"ok": False, "error": "Invalid coupon code."}
    if coupon["expires_at"] and coupon["expires_at"] < datetime.now(timezone.utc).isoformat():
        return {"ok": False, "error": "This coupon has expired."}
    if coupon["uses_count"] >= coupon["max_uses"]:
        return {"ok": False, "error": "This coupon has reached its usage limit."}
    already = db.execute(
        "SELECT 1 FROM coupon_redemptions WHERE coupon_id = ? AND user_id = ?", (coupon["id"], user_id)
    ).fetchone()
    if already:
        return {"ok": False, "error": "You've already used this coupon."}

    db.execute(
        "INSERT INTO coupon_redemptions (coupon_id, user_id, created_at) VALUES (?, ?, ?)",
        (coupon["id"], user_id, _now()),
    )
    db.execute("UPDATE coupons SET uses_count = uses_count + 1 WHERE id = ?", (coupon["id"],))
    db.commit()
    return {"ok": True, "discount_percent": coupon["discount_percent"]}


def list_coupons():
    return [dict(r) for r in get_db().execute("SELECT * FROM coupons ORDER BY created_at DESC").fetchall()]


# ---- Feedback & testimonials -----------------------------------------------
def submit_feedback(user_id: int, message: str, rating: int | None):
    db = get_db()
    db.execute(
        "INSERT INTO feedback (user_id, message, rating, created_at) VALUES (?, ?, ?, ?)",
        (user_id, message, rating, _now()),
    )
    db.commit()


def list_feedback(limit: int = 50):
    rows = get_db().execute(
        "SELECT f.*, u.name as user_name FROM feedback f JOIN users u ON f.user_id = u.id "
        "ORDER BY f.created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def submit_testimonial(user_id: int, quote: str):
    db = get_db()
    db.execute(
        "INSERT INTO testimonials (user_id, quote, approved, created_at) VALUES (?, ?, 0, ?)",
        (user_id, quote, _now()),
    )
    db.commit()


def approve_testimonial(testimonial_id: int, approved: bool = True):
    db = get_db()
    db.execute("UPDATE testimonials SET approved = ? WHERE id = ?", (int(approved), testimonial_id))
    db.commit()


def list_testimonials(approved_only: bool = True):
    q = "SELECT t.*, u.name as user_name FROM testimonials t JOIN users u ON t.user_id = u.id"
    if approved_only:
        q += " WHERE t.approved = 1"
    q += " ORDER BY t.created_at DESC"
    return [dict(r) for r in get_db().execute(q).fetchall()]


# ---- Referrals --------------------------------------------------------------
def get_referral_stats(user_id: int):
    db = get_db()
    user = get_user_by_id(user_id)
    referred = db.execute(
        "SELECT name, created_at FROM users WHERE referred_by_user_id = ? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    return {
        "referral_code": user["referral_code"],
        "total_referred": len(referred),
        "referred_users": [dict(r) for r in referred],
    }


def get_predictions_count_today(user_id: int) -> int:
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    return get_db().execute(
        "SELECT COUNT(*) c FROM prediction_records WHERE user_id = ? AND created_at LIKE ?",
        (user_id, f"{today}%"),
    ).fetchone()["c"]


# ---- Notifications ----------------------------------------------------
def create_notification_if_new(user_id: int, message: str, kind: str, dedupe_key: str):
    """dedupe_key scopes uniqueness -- e.g. f'journal_reminder:{date}' so the
    same reminder isn't inserted twice for the same day."""
    db = get_db()
    try:
        db.execute(
            "INSERT INTO notifications (user_id, message, kind, dedupe_key, read, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (user_id, message, kind, dedupe_key, _now()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        pass  # already created for this dedupe key


def get_unread_notifications(user_id: int, limit: int = 20):
    rows = get_db().execute(
        "SELECT * FROM notifications WHERE user_id = ? AND read = 0 ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_notification_read(notification_id: int, user_id: int):
    db = get_db()
    db.execute(
        "UPDATE notifications SET read = 1 WHERE id = ? AND user_id = ?", (notification_id, user_id)
    )
    db.commit()


def mark_all_notifications_read(user_id: int):
    db = get_db()
    db.execute("UPDATE notifications SET read = 1 WHERE user_id = ?", (user_id,))
    db.commit()


def get_user_activity_summary(user_id: int):
    """Raw signals used for both notification rules and the churn heuristic."""
    from datetime import datetime, timezone
    db = get_db()

    last_journal = db.execute(
        "SELECT created_at FROM journal_entries WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,)
    ).fetchone()
    last_prediction = db.execute(
        "SELECT created_at FROM prediction_records WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,)
    ).fetchone()

    def days_since(iso_str):
        if not iso_str:
            return None
        dt = datetime.fromisoformat(iso_str)
        return (datetime.now(timezone.utc) - dt).days

    return {
        "days_since_last_journal": days_since(last_journal["created_at"] if last_journal else None),
        "days_since_last_prediction": days_since(last_prediction["created_at"] if last_prediction else None),
    }


# ---- Student Mode: subjects, exams, assignments ----------------------
def create_subject(user_id: int, name: str, exam_date: str | None):
    db = get_db()
    cur = db.execute(
        "INSERT INTO subjects (user_id, name, exam_date, created_at) VALUES (?, ?, ?, ?)",
        (user_id, name, exam_date, _now()),
    )
    db.commit()
    return cur.lastrowid


def get_subjects(user_id: int):
    rows = get_db().execute(
        "SELECT * FROM subjects WHERE user_id = ? ORDER BY (exam_date IS NULL), exam_date ASC", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def delete_subject(subject_id: int, user_id: int):
    db = get_db()
    db.execute("DELETE FROM subjects WHERE id = ? AND user_id = ?", (subject_id, user_id))
    db.commit()


def create_assignment(user_id: int, subject_id: int | None, title: str, due_date: str | None):
    db = get_db()
    cur = db.execute(
        "INSERT INTO assignments (user_id, subject_id, title, due_date, completed, created_at) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (user_id, subject_id, title, due_date, _now()),
    )
    db.commit()
    return cur.lastrowid


def get_assignments(user_id: int, include_completed: bool = True):
    q = ("SELECT a.*, s.name as subject_name FROM assignments a "
         "LEFT JOIN subjects s ON a.subject_id = s.id WHERE a.user_id = ?")
    if not include_completed:
        q += " AND a.completed = 0"
    q += " ORDER BY (a.due_date IS NULL), a.due_date ASC"
    rows = get_db().execute(q, (user_id,)).fetchall()
    return [dict(r) for r in rows]


def toggle_assignment(assignment_id: int, user_id: int):
    db = get_db()
    row = db.execute(
        "SELECT completed FROM assignments WHERE id = ? AND user_id = ?", (assignment_id, user_id)
    ).fetchone()
    if row is None:
        return None
    new_val = 0 if row["completed"] else 1
    db.execute("UPDATE assignments SET completed = ? WHERE id = ?", (new_val, assignment_id))
    db.commit()
    return bool(new_val)


# ---- Password reset -------------------------------------------------------
def create_password_reset_token(user_id: int, token_hash: str, expires_at: str):
    db = get_db()
    # Invalidate any previous unused tokens for this user first -- only one
    # active reset link should work at a time.
    db.execute("UPDATE password_reset_tokens SET used = 1 WHERE user_id = ? AND used = 0", (user_id,))
    db.execute(
        "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, used, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        (user_id, token_hash, expires_at, _now()),
    )
    db.commit()


def get_valid_reset_token(token_hash: str):
    from datetime import datetime, timezone
    row = get_db().execute(
        "SELECT * FROM password_reset_tokens WHERE token_hash = ? AND used = 0", (token_hash,)
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < datetime.now(timezone.utc).isoformat():
        return None
    return dict(row)


def consume_reset_token(token_hash: str, new_password: str):
    db = get_db()
    token_row = db.execute(
        "SELECT * FROM password_reset_tokens WHERE token_hash = ? AND used = 0", (token_hash,)
    ).fetchone()
    if token_row is None:
        return False
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), token_row["user_id"]),
    )
    db.execute("UPDATE password_reset_tokens SET used = 1 WHERE id = ?", (token_row["id"],))
    db.commit()
    return True


# ---- Long-Term AI Memory (Feature 1) --------------------------------------
def get_active_memory_facts(user_id: int, fact_type: str | None = None, limit: int | None = None):
    q = "SELECT * FROM memory_facts WHERE user_id = ? AND active = 1"
    params: list = [user_id]
    if fact_type:
        q += " AND fact_type = ?"
        params.append(fact_type)
    q += " ORDER BY occurrence_count DESC, last_seen DESC"
    if limit:
        q += " LIMIT ?"
        params.append(limit)
    rows = get_db().execute(q, params).fetchall()
    return [_memory_fact_row_to_dict(r) for r in rows]


def find_similar_active_fact(user_id: int, fact_type: str):
    """Candidates to fuzzy-match against in ml/memory.py -- returns all active
    facts of this type so the caller can score similarity in Python (sqlite
    has no good text-similarity primitive worth relying on here)."""
    rows = get_db().execute(
        "SELECT * FROM memory_facts WHERE user_id = ? AND fact_type = ? AND active = 1",
        (user_id, fact_type),
    ).fetchall()
    return [_memory_fact_row_to_dict(r) for r in rows]


def _memory_fact_row_to_dict(r):
    d = dict(r)
    d["fact_text"] = decrypt_text(d.get("fact_text"))
    d["normalized_text"] = decrypt_text(d.get("normalized_text"))
    return d


def insert_memory_fact(user_id: int, fact_type: str, fact_text: str, normalized_text: str,
                        confidence: float, source: str = "journal"):
    db = get_db()
    now = _now()
    cur = db.execute(
        """INSERT INTO memory_facts
           (user_id, fact_type, fact_text, normalized_text, occurrence_count,
            confidence, source, active, first_seen, last_seen)
           VALUES (?, ?, ?, ?, 1, ?, ?, 1, ?, ?)""",
        (user_id, fact_type, encrypt_text(fact_text), encrypt_text(normalized_text),
         confidence, source, now, now),
    )
    db.commit()
    return cur.lastrowid


def reinforce_memory_fact(fact_id: int, bump_confidence: float = 0.05):
    db = get_db()
    db.execute(
        """UPDATE memory_facts
           SET occurrence_count = occurrence_count + 1,
               confidence = MIN(0.98, confidence + ?),
               active = 1,
               last_seen = ?
           WHERE id = ?""",
        (bump_confidence, _now(), fact_id),
    )
    db.commit()


def deactivate_memory_fact(fact_id: int):
    db = get_db()
    db.execute("UPDATE memory_facts SET active = 0 WHERE id = ?", (fact_id,))
    db.commit()


def delete_memory_fact(user_id: int, fact_id: int) -> bool:
    """User-initiated hard delete of a single memory (routes/memory.py).
    Scoped to user_id in the WHERE clause -- same ownership-check pattern
    as checkin_habit() -- so one user can never delete another user's
    memory even by guessing an id. Distinct from deactivate_memory_fact()
    above, which is the system's own soft-decay path and stays reversible;
    a user clicking "delete" should mean actually gone. Returns True if a
    row was deleted, False if no matching (owned) fact existed."""
    db = get_db()
    cur = db.execute("DELETE FROM memory_facts WHERE id = ? AND user_id = ?", (fact_id, user_id))
    db.commit()
    return cur.rowcount > 0


def clear_all_memory(user_id: int) -> int:
    """User-initiated full reset ("Clear All Memories"). Deletes every
    memory fact AND period summary for this user -- summaries are also
    derived personalization data, so a full clear should remove those too.
    Returns the number of facts deleted (summaries aren't shown in the UI
    count, but are wiped alongside)."""
    db = get_db()
    cur = db.execute("DELETE FROM memory_facts WHERE user_id = ?", (user_id,))
    deleted = cur.rowcount
    db.execute("DELETE FROM memory_summaries WHERE user_id = ?", (user_id,))
    db.commit()
    return deleted


def prune_stale_memory_facts(user_id: int, cutoff_iso: str, min_occurrences: int = 2):
    """Deactivate (never delete) weak, un-reinforced facts older than cutoff.
    Facts reinforced enough times survive regardless of age -- repetition is
    what makes something a real pattern rather than a one-off mention."""
    db = get_db()
    db.execute(
        """UPDATE memory_facts SET active = 0
           WHERE user_id = ? AND active = 1 AND last_seen < ? AND occurrence_count < ?""",
        (user_id, cutoff_iso, min_occurrences),
    )
    db.commit()


def cap_active_memory_facts(user_id: int, cap: int):
    """Keep only the top `cap` active facts (by occurrence_count, then
    recency); deactivate the rest so prompt context stays bounded no matter
    how long a user's history gets."""
    db = get_db()
    rows = db.execute(
        """SELECT id FROM memory_facts WHERE user_id = ? AND active = 1
           ORDER BY occurrence_count DESC, last_seen DESC""",
        (user_id,),
    ).fetchall()
    overflow_ids = [r["id"] for r in rows[cap:]]
    if overflow_ids:
        db.executemany("UPDATE memory_facts SET active = 0 WHERE id = ?", [(i,) for i in overflow_ids])
        db.commit()


def insert_memory_summary(user_id: int, period_start: str, period_end: str,
                           summary_text: str, entry_count: int):
    db = get_db()
    db.execute(
        """INSERT INTO memory_summaries (user_id, period_start, period_end, summary_text, entry_count, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, period_start, period_end, summary_text, entry_count, _now()),
    )
    db.commit()


def get_recent_memory_summaries(user_id: int, limit: int = 3):
    rows = get_db().execute(
        "SELECT * FROM memory_summaries WHERE user_id = ? ORDER BY period_end DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_journal_entry_count(user_id: int) -> int:
    return get_db().execute(
        "SELECT COUNT(*) c FROM journal_entries WHERE user_id = ?", (user_id,)
    ).fetchone()["c"]


def get_journal_entries_between(user_id: int, start_iso: str, end_iso: str):
    rows = get_db().execute(
        "SELECT * FROM journal_entries WHERE user_id = ? AND created_at >= ? AND created_at < ? ORDER BY created_at ASC",
        (user_id, start_iso, end_iso),
    ).fetchall()
    return [_journal_row_to_dict(r) for r in rows]


# ---- Early Risk Detection (Feature 2) --------------------------------------
def insert_risk_snapshot(user_id: int, category: str, level: str, score: int, reasons_json: str):
    db = get_db()
    db.execute(
        """INSERT INTO risk_snapshots (user_id, category, level, score, reasons_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, category, level, score, reasons_json, _now()),
    )
    db.commit()


def get_latest_risk_snapshot_time(user_id: int):
    row = get_db().execute(
        "SELECT created_at FROM risk_snapshots WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return row["created_at"] if row else None


def get_risk_history(user_id: int, category: str | None = None, days: int = 90):
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = "SELECT * FROM risk_snapshots WHERE user_id = ? AND created_at >= ?"
    params: list = [user_id, since]
    if category:
        q += " AND category = ?"
        params.append(category)
    q += " ORDER BY created_at ASC"
    rows = get_db().execute(q, params).fetchall()
    return [dict(r) for r in rows]


def get_latest_risk_profile(user_id: int):
    """Most recent snapshot per category."""
    rows = get_db().execute(
        """SELECT r.* FROM risk_snapshots r
           INNER JOIN (
               SELECT category, MAX(created_at) AS max_created
               FROM risk_snapshots WHERE user_id = ? GROUP BY category
           ) latest ON r.category = latest.category AND r.created_at = latest.max_created
           WHERE r.user_id = ?""",
        (user_id, user_id),
    ).fetchall()
    return [dict(r) for r in rows]


def get_habit_checkins_by_week(user_id: int, weeks: int = 8):
    """Count of habit check-ins per ISO week for the last `weeks` weeks --
    used as the productivity/consistency proxy signal for burnout risk."""
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).date().isoformat()
    rows = get_db().execute(
        """SELECT checkin_date FROM habit_checkins
           WHERE user_id = ? AND checkin_date >= ? ORDER BY checkin_date ASC""",
        (user_id, since),
    ).fetchall()
    by_week: dict = {}
    for r in rows:
        d = datetime.fromisoformat(r["checkin_date"])
        wk = d.isocalendar()[:2]  # (iso_year, iso_week)
        by_week[wk] = by_week.get(wk, 0) + 1
    # Return in chronological order as a plain list of counts
    return [by_week[k] for k in sorted(by_week.keys())]


# ---- Personalized Recovery Plans (Feature 3) ------------------------------
ACTIVITY_TYPES = (
    "journal", "reflection", "breathing", "timer", "checkin",
    "habit", "ai_conversation", "progress_review", "quiz", "assessment",
)


def infer_activity_type(task_text: str, auto_signal: str | None) -> str:
    """Maps a plan template's (task_text, auto_signal) to one of
    ACTIVITY_TYPES, so the Activity Engine knows which interactive UI to
    render. Keyword heuristic over the existing PLAN_LIBRARY task text --
    deliberately not a hardcoded per-task table, so new template tasks get
    a sensible interactive activity for free. Used both to backfill
    pre-Activity-Engine rows and (via ml.recovery_plans) to assign new
    tasks at plan-creation time."""
    t = (task_text or "").lower()
    if auto_signal == "journal" or "journal" in t or "write" in t:
        return "journal"
    if "breath" in t:
        return "breathing"
    if "talk through" in t or "ai guided" in t or "ai conversation" in t:
        return "ai_conversation"
    if "screen-free" in t or "no-phone" in t or "no phone" in t or (
        "minute" in t and ("walk" in t or "break" in t)
    ):
        return "timer"
    if auto_signal == "habit":
        return "habit"
    if "type of thought" in t or "identify" in t and "thought" in t:
        return "quiz"
    if "grounding" in t or "reframe" in t or "rewrite" in t or "interpretation" in t or "fact" in t and "prediction" in t:
        return "reflection"
    if "final" in t and "review" in t or "progress review" in t:
        return "progress_review"
    return "checkin"


def get_recent_activity_results(user_id: int, activity_type: str, since_iso: str):
    """Completed activities of a given type, across ALL of this user's
    plans (not just the active one), completed at/after since_iso.
    Feeds the personalization loop: e.g. recent check-in anxiety scores
    influence which plan gets recommended next -- real stored numbers,
    never inferred."""
    rows = get_db().execute(
        """SELECT t.result_json FROM recovery_plan_tasks t
           JOIN recovery_plans p ON p.id = t.plan_id
           WHERE p.user_id = ? AND t.activity_type = ? AND t.state = 'completed'
                 AND t.completed_at >= ?""",
        (user_id, activity_type, since_iso),
    ).fetchall()
    out = []
    for r in rows:
        if r["result_json"]:
            try:
                out.append(json.loads(r["result_json"]))
            except (TypeError, ValueError):
                pass
    return out


def get_active_recovery_plan(user_id: int):
    row = get_db().execute(
        "SELECT * FROM recovery_plans WHERE user_id = ? AND status = 'active' "
        "ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def get_recovery_plan(plan_id: int, user_id: int):
    row = get_db().execute(
        "SELECT * FROM recovery_plans WHERE id = ? AND user_id = ?", (plan_id, user_id)
    ).fetchone()
    return dict(row) if row else None


def get_recovery_plan_history(user_id: int, limit: int = 10):
    rows = get_db().execute(
        "SELECT * FROM recovery_plans WHERE user_id = ? AND status != 'active' "
        "ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_recovery_plan_tasks(plan_id: int):
    rows = get_db().execute(
        "SELECT * FROM recovery_plan_tasks WHERE plan_id = ? ORDER BY day_number ASC",
        (plan_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def create_recovery_plan(user_id: int, plan_type: str, title: str, duration_days: int,
                          activities: list[tuple[int, str, str | None, str]], source: str = "manual",
                          started_at: str | None = None):
    """activities: list of (day_number, task_text, auto_signal, activity_type),
    day_number in [1, duration_days] -- multiple activities may share the
    same day_number (a day can hold several activities: e.g. a check-in, a
    breathing session, and a reflection all on Day 1). Abandons any
    currently-active plan for this user first (only one active plan at a
    time keeps the UI focused rather than overwhelming)."""
    from datetime import timedelta
    db = get_db()
    now = _now()
    started_at = started_at or now
    ends_at = (datetime.fromisoformat(started_at) + timedelta(days=duration_days)).isoformat()

    db.execute(
        "UPDATE recovery_plans SET status = 'abandoned' WHERE user_id = ? AND status = 'active'",
        (user_id,),
    )
    cur = db.execute(
        """INSERT INTO recovery_plans
           (user_id, plan_type, title, duration_days, status, source, started_at, ends_at, created_at)
           VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
        (user_id, plan_type, title, duration_days, source, started_at, ends_at, now),
    )
    plan_id = cur.lastrowid
    db.executemany(
        "INSERT INTO recovery_plan_tasks (plan_id, day_number, task_text, auto_signal, activity_type) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (plan_id, day_number, text, signal, activity_type or infer_activity_type(text, signal))
            for day_number, text, signal, activity_type in activities
        ],
    )
    db.commit()
    return plan_id


def set_recovery_task_completed(task_id: int, plan_id: int, completed: bool):
    """Legacy manual-checklist toggle, kept for backward API compatibility.
    The Activity Engine UI uses complete_recovery_activity() instead, which
    requires an actual activity result -- this one still just flips the
    checkbox, so it also keeps `state` in sync for anything reading the
    new column."""
    db = get_db()
    db.execute(
        "UPDATE recovery_plan_tasks SET completed = ?, completed_at = ?, state = ? WHERE id = ? AND plan_id = ?",
        (
            1 if completed else 0, _now() if completed else None,
            "completed" if completed else "not_started",
            task_id, plan_id,
        ),
    )
    db.commit()


def get_recovery_task_for_user(task_id: int, user_id: int):
    """Ownership-checked activity fetch: joins through recovery_plans so a
    task_id can never be read/acted on unless it belongs to a plan owned
    by user_id. Returns None if the task doesn't exist or belongs to
    someone else -- callers must treat both the same way (404), never
    revealing which."""
    row = get_db().execute(
        """SELECT t.*, p.user_id AS plan_user_id, p.status AS plan_status,
                  p.title AS plan_title, p.id AS plan_id
           FROM recovery_plan_tasks t
           JOIN recovery_plans p ON p.id = t.plan_id
           WHERE t.id = ? AND p.user_id = ?""",
        (task_id, user_id),
    ).fetchone()
    return dict(row) if row else None


def start_recovery_task(task_id: int, plan_id: int):
    """Marks an activity in_progress the first time it's opened. No-op if
    it's already in_progress/completed (idempotent, refresh-safe)."""
    db = get_db()
    db.execute(
        "UPDATE recovery_plan_tasks SET state = 'in_progress', started_at = COALESCE(started_at, ?) "
        "WHERE id = ? AND plan_id = ? AND state = 'not_started'",
        (_now(), task_id, plan_id),
    )
    db.commit()


def complete_recovery_task(task_id: int, plan_id: int, result: dict):
    """Marks an activity completed with its real, persisted result
    payload. Also flips the legacy `completed`/`completed_at` columns so
    every existing progress-percent/history calculation (which reads
    those columns) keeps working unchanged."""
    db = get_db()
    now = _now()
    db.execute(
        "UPDATE recovery_plan_tasks SET state = 'completed', completed = 1, completed_at = ?, "
        "result_json = ? WHERE id = ? AND plan_id = ?",
        (now, json.dumps(result), task_id, plan_id),
    )
    db.commit()


def skip_recovery_task(task_id: int, plan_id: int):
    db = get_db()
    db.execute(
        "UPDATE recovery_plan_tasks SET state = 'skipped' WHERE id = ? AND plan_id = ? AND state != 'completed'",
        (task_id, plan_id),
    )
    db.commit()


def set_recovery_plan_status(plan_id: int, status: str):
    db = get_db()
    db.execute("UPDATE recovery_plans SET status = ? WHERE id = ?", (status, plan_id))
    db.commit()


def get_journal_dates_between(user_id: int, start_iso: str, end_iso: str) -> set:
    rows = get_db().execute(
        "SELECT created_at FROM journal_entries WHERE user_id = ? AND created_at >= ? AND created_at < ?",
        (user_id, start_iso, end_iso),
    ).fetchall()
    return {r["created_at"][:10] for r in rows}


def get_habit_checkin_dates_between(user_id: int, start_iso: str, end_iso: str) -> set:
    rows = get_db().execute(
        "SELECT DISTINCT checkin_date FROM habit_checkins WHERE user_id = ? "
        "AND checkin_date >= ? AND checkin_date < ?",
        (user_id, start_iso[:10], end_iso[:10]),
    ).fetchall()
    return {r["checkin_date"] for r in rows}
