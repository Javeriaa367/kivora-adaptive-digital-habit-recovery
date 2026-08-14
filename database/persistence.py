"""
Durable persistence for the SQLite database.

Cloud Run's local filesystem is ephemeral: every redeploy (and every
scale-to-zero cold start) wipes `app.db`. That made the product's core
data -- journals, memories, recovery plans -- guaranteed lossy in its
intended deployment. This module fixes that WITHOUT rewriting the
stdlib-SQLite data layer:

  * A backup is a consistent snapshot taken through sqlite3's online
    backup API (``Connection.backup``) -- safe to run while the app is
    actively writing, no downtime, no corrupted snapshots.
  * Backups go to a durable ``BackupStore``:
      - ``LocalDirStore``  -- copies into a local directory (dev, tests,
                              or a mounted persistent volume in prod).
      - ``GcsStore``       -- Google Cloud Storage via the
                              ``google-cloud-storage`` client, using Cloud
                              Run's Application Default Credentials (the
                              production store).
  * On boot, ``database.db.init_db`` restores the newest backup whenever
    the local DB file is missing, so a redeploy finds all user data
    intact instead of a blank database.
  * While running, the newest write is backed up within
    ``PERSISTENCE_BACKUP_INTERVAL`` seconds of the last request
    (after_request hook), and a shutdown backup runs on SIGTERM/SIGINT
    (what Cloud Run sends when an instance is replaced).

Configuration (env vars, read by config.py):

  PERSISTENCE_BACKUP_BUCKET    -- GCS bucket name (production).
  PERSISTENCE_BACKUP_DIR       -- local directory / mounted volume path.
  PERSISTENCE_BACKUP_INTERVAL  -- seconds between scheduled backups
                                  (default 120).

A production boot (FLASK_ENV=production or K_SERVICE/CLOUD_RUN set) with
neither store configured fails closed at startup, the same precedent as
the SECRET_KEY check in config.py -- silently running without durable
storage is exactly the data-loss bug this module exists to prevent.

Backup objects are timestamped (UTC, microsecond precision) and sorted
lexicographically, so "newest" is always ``max``/the last item in a
sorted listing -- true for both the local directory and GCS.
"""
import os
import sqlite3
import threading
import time

BACKUP_SUFFIX = ".bak"


# ---- low-level snapshot helpers -------------------------------------------

def _snapshot(src_path: str, dst_path: str) -> None:
    """Consistent point-in-time copy of a live SQLite file. Uses the
    online backup API so it is safe while other connections are writing.
    Written to dst_path + '.tmp' first, then atomically renamed into
    place, so a failed backup never leaves a half-written restore point."""
    tmp = dst_path + ".tmp"
    src_conn = sqlite3.connect(src_path)
    try:
        dst_conn = sqlite3.connect(tmp)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    os.replace(tmp, dst_path)


def _copy_atomic(src_path: str, dst_path: str) -> None:
    """Copy a backup file into place atomically (restore path)."""
    tmp = dst_path + ".tmp"
    with open(src_path, "rb") as f_in, open(tmp, "wb") as f_out:
        while True:
            chunk = f_in.read(1 << 20)
            if not chunk:
                break
            f_out.write(chunk)
    os.replace(tmp, dst_path)


def _timestamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _backup_name(db_path: str) -> str:
    return os.path.basename(db_path) + "." + _timestamp() + BACKUP_SUFFIX


# ---- stores ---------------------------------------------------------------

class LocalDirStore:
    """Backups are timestamped copies in a local directory. Used in dev
    and tests, and in production when PERSISTENCE_BACKUP_DIR points at a
    mounted persistent volume instead of Cloud Run's ephemeral disk."""

    def __init__(self, directory: str):
        self.directory = directory

    def _files(self) -> list[str]:
        if not os.path.isdir(self.directory):
            return []
        return sorted(f for f in os.listdir(self.directory) if f.endswith(BACKUP_SUFFIX))

    def save(self, src_path: str) -> bool:
        os.makedirs(self.directory, exist_ok=True)
        dest = os.path.join(self.directory, _backup_name(src_path))
        _snapshot(src_path, dest)
        return True

    def latest(self, dest_path: str) -> bool:
        files = self._files()
        if not files:
            return False
        _copy_atomic(os.path.join(self.directory, files[-1]), dest_path)
        return True


class GcsStore:
    """Production store: Google Cloud Storage via the google-cloud-storage
    client, which authenticates with Application Default Credentials (Cloud
    Run's runtime service account is authorised by default -- no keys in the
    container). This is the intended store for Cloud Run. Requires
    `google-cloud-storage` in requirements.txt; a startup with the bucket
    configured but the package missing fails closed with a clear message."""

    def __init__(self, bucket: str):
        try:
            from google.cloud import storage
        except ImportError as e:  # pragma: no cover -- exercised on deploy
            raise RuntimeError(
                "PERSISTENCE_BACKUP_BUCKET is set but 'google-cloud-storage' is not "
                "installed. Add it to requirements.txt, or use PERSISTENCE_BACKUP_DIR."
            ) from e
        self._bucket = storage.Client().bucket(bucket.strip().strip("gs://"))
        self._prefix = "mindmetrics-backups"

    def save(self, src_path: str) -> bool:
        tmp = src_path + ".persistence-tmp"
        try:
            _snapshot(src_path, tmp)
            blob = self._bucket.blob(self._prefix + "/" + _backup_name(src_path))
            blob.upload_from_filename(tmp)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return True

    def latest(self, dest_path: str) -> bool:
        blobs = list(self._bucket.list_blobs(prefix=self._prefix + "/"))
        if not blobs:
            return False
        chosen = max(blobs, key=lambda b: b.name)
        tmp = dest_path + ".persistence-tmp"
        try:
            chosen.download_to_filename(tmp)
            os.replace(tmp, dest_path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return True


# ---- store selection / wiring ----------------------------------------------

def make_store(app) -> LocalDirStore | GcsStore | None:
    """Pick the durable store from app config. None means persistence is
    not configured (the local-dev default -- data is not backed up)."""
    bucket = (app.config.get("PERSISTENCE_BACKUP_BUCKET") or "").strip()
    if bucket:
        return GcsStore(bucket)
    directory = (app.config.get("PERSISTENCE_BACKUP_DIR") or "").strip()
    if directory:
        return LocalDirStore(directory)
    return None


def ensure_persistence_configured(app) -> None:
    """Fail closed in production when no durable store is configured."""
    if make_store(app) is not None:
        return
    if app.config.get("TESTING"):
        return
    env = os.environ.get("FLASK_ENV", "").lower()
    on_cloud_run = bool(os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN"))
    if env in ("production", "prod") or on_cloud_run:
        raise RuntimeError(
            "Durable persistence is not configured. Set PERSISTENCE_BACKUP_BUCKET "
            "(GCS bucket) or PERSISTENCE_BACKUP_DIR (mounted persistent volume) so "
            "user data survives Cloud Run redeploys."
        )


def _state(app) -> dict:
    return app.extensions.setdefault("mindmetrics_persistence", {
        "store": None,
        "last_backup": 0.0,
        "lock": threading.Lock(),
        "interval": int(app.config.get("PERSISTENCE_BACKUP_INTERVAL", 120)),
    })


def configure_persistence(app) -> None:
    """Wire persistence into a Flask app. Call before database.db.init_db
    so restore-on-boot can find the store. Registers the after-request
    scheduled backup and (outside tests) shutdown backup handlers."""
    store = make_store(app)
    ensure_persistence_configured(app)
    _state(app)["store"] = store

    app.after_request(_after_request_backup)

    if store is not None and not app.config.get("TESTING"):
        _register_shutdown_backup(app, store)


def _after_request_backup(response):
    from flask import current_app
    st = _state(current_app)
    if st["store"] is None:
        return response
    if time.monotonic() - st["last_backup"] >= st["interval"]:
        with st["lock"]:
            if time.monotonic() - st["last_backup"] >= st["interval"]:
                if backup_now(current_app, st["store"]):
                    st["last_backup"] = time.monotonic()
    return response


def _register_shutdown_backup(app, store) -> None:
    """Back up once when Cloud Run sends SIGTERM to retire an instance.
    The handler re-raises the signal with the default disposition so
    gunicorn's own graceful-shutdown path still runs."""
    import signal

    if threading.current_thread() is not threading.main_thread():
        return

    def _handler(signum, frame):
        try:
            backup_now(app, store)
        except Exception:  # never let a backup failure block shutdown
            app.logger.warning("shutdown backup failed", exc_info=True)
        finally:
            try:
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)
            except Exception:
                pass

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass  # not the main thread, or unsupported on this platform


# ---- public API used by database.db.init_db ---------------------------------

def backup_now(app, store=None) -> bool:
    """Write a consistent snapshot of the live DB to the durable store.
    Returns False when persistence is not configured (safe no-op)."""
    store = store or make_store(app)
    if store is None:
        return False
    db_path = app.config["DATABASE_PATH"]
    if not os.path.exists(db_path):
        return False
    try:
        return store.save(db_path)
    except Exception:
        app.logger.warning("database backup failed", exc_info=True)
        return False


def restore_latest(app, store=None) -> bool:
    """Restore the newest backup to DATABASE_PATH. Returns True when a
    backup was found and restored, False otherwise (never raises)."""
    store = store or make_store(app)
    if store is None:
        return False
    db_path = app.config["DATABASE_PATH"]
    for suffix in ("-wal", "-shm"):
        stale = db_path + suffix
        if os.path.exists(stale):
            os.remove(stale)
    try:
        return store.latest(db_path)
    except Exception:
        app.logger.warning("database restore failed", exc_info=True)
        return False


def maybe_restore_on_boot(app) -> bool:
    """Restore the newest backup when the local DB is missing or is a
    0-byte shell (crashed before schema creation). Returns True if a
    backup was restored."""
    db_path = app.config["DATABASE_PATH"]
    if os.path.exists(db_path):
        if os.path.getsize(db_path) == 0:
            os.remove(db_path)  # empty shell from a crashed first boot
        else:
            return False
    if restore_latest(app):
        app.logger.info("Restored database from backup after boot.")
        return True
    return False
