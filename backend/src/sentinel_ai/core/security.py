"""Password hashing, password policy, and session-token primitives (ADR-0002).

Nothing here logs or returns a secret except the freshly generated raw tokens, which the
caller sends to the client exactly once and never stores.
"""

import hashlib
import hmac
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

_hasher = PasswordHasher()  # Argon2id with the library's current recommended parameters

# Small built-in deny list; not a substitute for a breach corpus (see OPEN_QUESTIONS Q33).
_COMMON_PASSWORDS = frozenset(
    {
        "password1234",
        "password12345",
        "123456789012",
        "1234567890123",
        "qwertyuiop12",
        "qwerty123456",
        "letmein12345",
        "administrator",
        "changeme1234",
        "welcome12345",
        "iloveyou1234",
        "passwordpassword",
        "sentinelai1234",
        "sentinel-ai-123",
    }
)

EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    return len(email) <= 320 and EMAIL_PATTERN.match(email) is not None


def password_policy_violations(password: str, *, email: str | None = None) -> list[str]:
    """Return human-readable policy violations (empty list means acceptable)."""
    problems: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > PASSWORD_MAX_LENGTH:
        problems.append(f"must be at most {PASSWORD_MAX_LENGTH} characters")
    if password and len(set(password)) < 5:
        problems.append("is too repetitive")
    if password.lower() in _COMMON_PASSWORDS:
        problems.append("is too common")
    if email:
        local = normalize_email(email).split("@", 1)[0]
        if len(local) >= 4 and local in password.lower():
            problems.append("must not contain your email name")
    return problems


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


# A real Argon2id hash of a throwaway value, verified when the account does not exist so
# unknown-user and wrong-password logins take comparable time.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def new_session_token() -> str:
    """256-bit opaque token."""
    return secrets.token_urlsafe(32)


def keyed_hash(pepper: str, purpose: str, value: str) -> bytes:
    """HMAC-SHA-256(pepper, purpose || value) -> 32 bytes (matches the bytea CHECK)."""
    return hmac.new(pepper.encode(), f"{purpose}:{value}".encode(), hashlib.sha256).digest()


def session_token_hash(pepper: str, token: str) -> bytes:
    return keyed_hash(pepper, "session", token)


def csrf_token_for(pepper: str, session_token: str) -> str:
    """CSRF token derived from the session token, so it can be re-issued by GET /auth/me
    without being stored (only its hash is stored). Useless without the session cookie."""
    return keyed_hash(pepper, "csrf-token", session_token).hex()


def csrf_token_hash(pepper: str, csrf_token: str) -> bytes:
    return keyed_hash(pepper, "csrf-hash", csrf_token)


def constant_time_equal(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)
