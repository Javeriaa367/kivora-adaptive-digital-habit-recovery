import os
import secrets

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _load_secret_key() -> str:
    """Fail closed in production: a deploy without SECRET_KEY is rejected
    outright rather than silently using a known default that would let
    anyone forge session cookies. In local dev (no FLASK_ENV=production),
    fall back to a fresh random key per boot -- sessions just don't
    survive restarts, which is the safe trade for a dev box."""
    secret = os.environ.get("SECRET_KEY")
    if secret:
        return secret
    env = os.environ.get("FLASK_ENV", "").lower()
    if env in ("production", "prod") or os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN"):
        raise RuntimeError(
            "SECRET_KEY must be set in production. Generate one with "
            "`openssl rand -hex 32` and set it as an environment variable / secret."
        )
    return secrets.token_hex(32)


def _secure_cookie_default() -> bool:
    """SESSION_COOKIE_SECURE must be ON whenever the app is served over
    HTTPS (Cloud Run, or an explicit FLASK_ENV=production). It must be OFF
    locally: the Flask dev server runs on plain HTTP, where browsers drop
    Secure cookies entirely -- the session never persists, so the CSRF
    token stored in it never matches and every POST fails with
    "session expired" (302 back to the form). An explicit
    SESSION_COOKIE_SECURE env var always wins."""
    override = os.environ.get("SESSION_COOKIE_SECURE")
    if override is not None:
        return override == "1"
    env = os.environ.get("FLASK_ENV", "").lower()
    on_cloud_run = bool(os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN"))
    if env in ("production", "prod") or on_cloud_run:
        return True
    return False


def _check_encryption_key_configured() -> None:
    """crypto_fields.py already fails closed in production if ENCRYPTION_KEY
    is unset (same precedent as SECRET_KEY above) -- importing it here just
    forces that check to run at config/app-boot time rather than lazily on
    first journal write, so a bad production deploy fails at startup, not
    on a real user's first journal entry."""
    import crypto_fields  # noqa: F401


class Config:
    SECRET_KEY = _load_secret_key()
    _check_encryption_key_configured()
    DATABASE_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "app.db"))
    ML_ARTIFACTS_DIR = os.path.join(BASE_DIR, "ml", "artifacts")

    # Session cookie hardening
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _secure_cookie_default()
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7  # 7 days

    # CSRF (see security.py) -- always on; only tests/dev that opt out set
    # this to False.
    CSRF_ENABLED = True

    # Durable persistence (database/persistence.py). Cloud Run's filesystem
    # is ephemeral, so the SQLite file must be backed up to a durable store
    # and restored on boot. Set at least one of the two store selectors in
    # production -- a production/Cloud Run boot with neither fails closed
    # at startup (same precedent as SECRET_KEY above):
    #   PERSISTENCE_BACKUP_BUCKET   -- GCS bucket, synced via gsutil
    #   PERSISTENCE_BACKUP_DIR      -- local directory / mounted volume
    # The write -> backup window is PERSISTENCE_BACKUP_INTERVAL seconds.
    PERSISTENCE_BACKUP_BUCKET = os.environ.get("PERSISTENCE_BACKUP_BUCKET", "")
    PERSISTENCE_BACKUP_DIR = os.environ.get("PERSISTENCE_BACKUP_DIR", "")
    PERSISTENCE_BACKUP_INTERVAL = int(os.environ.get("PERSISTENCE_BACKUP_INTERVAL", "120"))
