"""
Field-level encryption at rest for the two most sensitive text columns in
the schema: journal_entries.entry_text and memory_facts.fact_text /
normalized_text -- a user's raw journal writing and the personal facts the
memory system extracts from it. Everything else in the DB is metadata
(scores, timestamps, labels); these columns are the actual private
content, so they're encrypted before they ever reach SQLite/Postgres and
decrypted only in-process on read.

Uses Fernet (AES-128-CBC + HMAC, from the `cryptography` package) with a
single symmetric key loaded from the ENCRYPTION_KEY environment variable
(a urlsafe-base64 32-byte key, i.e. `Fernet.generate_key()`). Same
fail-closed precedent as SECRET_KEY in config.py: a production boot
without ENCRYPTION_KEY set refuses to start rather than silently storing
plaintext. In production this should come from a secrets manager / KMS;
Fernet here is deliberately swappable for a KMS-envelope scheme later
without touching call sites, since every caller only ever sees
encrypt_text()/decrypt_text().
"""
import base64
import os

from cryptography.fernet import Fernet, InvalidToken


def _load_encryption_key() -> bytes:
    key = os.environ.get("ENCRYPTION_KEY")
    if key:
        return key.encode() if isinstance(key, str) else key
    env = os.environ.get("FLASK_ENV", "").lower()
    if env in ("production", "prod") or os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN"):
        raise RuntimeError(
            "ENCRYPTION_KEY must be set in production so journal/memory "
            "content is encrypted at rest. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and set it as an "
            "environment variable / secret."
        )
    # Local dev/test: persist the encryption key to a local file so it
    # survives server restarts and doesn't break encrypted data access.
    # This allows existing journal/memory entries to remain readable
    # across process restarts while still keeping data encrypted at rest.
    key_file = os.path.join(os.path.dirname(__file__), ".encryption_key")
    if os.path.exists(key_file):
        try:
            with open(key_file, "rb") as f:
                return f.read()
        except Exception:
            pass  # fall through to generate new key
    
    # First time or file read failed: generate key and persist it
    new_key = Fernet.generate_key()
    try:
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        with open(key_file, "wb") as f:
            f.write(new_key)
        os.chmod(key_file, 0o600)  # restrict to owner only
    except Exception:
        pass  # if we can't write, just use the generated key for this session
    
    return new_key


_KEY = _load_encryption_key()
_FERNET = Fernet(_KEY)

# Sentinel prefix so we can tell an encrypted value apart from legacy
# plaintext already sitting in a DB from before this module existed --
# decrypt_text() passes those through unchanged instead of raising.
_PREFIX = "enc:v1:"


def encrypt_text(plaintext: str | None) -> str | None:
    """Encrypt a text field for storage. None/empty pass through unchanged
    (nothing sensitive to protect, and NOT NULL columns still work)."""
    if plaintext is None:
        return None
    token = _FERNET.encrypt(plaintext.encode("utf-8"))
    return _PREFIX + base64.urlsafe_b64encode(token).decode("ascii")


def decrypt_text(stored: str | None) -> str | None:
    """Decrypt a value written by encrypt_text(). If the value doesn't
    carry our prefix (pre-encryption legacy row, or a NULL/empty value),
    it's returned as-is rather than raising -- old data stays readable."""
    if not stored or not stored.startswith(_PREFIX):
        return stored
    try:
        token = base64.urlsafe_b64decode(stored[len(_PREFIX):].encode("ascii"))
        return _FERNET.decrypt(token).decode("utf-8")
    except (InvalidToken, ValueError):
        # Wrong/rotated key or corrupted data -- fail safe by surfacing a
        # clear marker instead of crashing the page that renders it.
        return "[unable to decrypt]"
