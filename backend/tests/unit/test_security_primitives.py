import time

from sentinel_ai.core import security
from sentinel_ai.core.permissions import (
    ROLE_PERMISSIONS,
    AccessLevel,
    Permission,
    Role,
    has_permission,
)
from sentinel_ai.core.ratelimit import RateLimiter

PEPPER = "p" * 40


def test_password_hash_is_argon2id_and_verifies() -> None:
    hashed = security.hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert security.verify_password(hashed, "correct horse battery")
    assert not security.verify_password(hashed, "wrong horse battery")
    assert not security.verify_password("not-a-hash", "anything")


def test_password_policy() -> None:
    assert security.password_policy_violations("short")
    assert security.password_policy_violations("a" * 20)  # too repetitive
    assert security.password_policy_violations("Password1234")  # common
    assert security.password_policy_violations("x" * 200)
    assert security.password_policy_violations("alice-is-here-1", email="alice@example.com")
    assert security.password_policy_violations("tr0ub4dor&3-horse") == []


def test_token_hashes_are_keyed_and_domain_separated() -> None:
    token = security.new_session_token()
    assert len(security.session_token_hash(PEPPER, token)) == 32
    assert security.session_token_hash(PEPPER, token) != security.session_token_hash(
        "q" * 40, token
    )
    csrf = security.csrf_token_for(PEPPER, token)
    assert csrf == security.csrf_token_for(PEPPER, token)  # re-derivable for /auth/me
    assert security.csrf_token_hash(PEPPER, csrf) != security.session_token_hash(PEPPER, csrf)
    assert security.new_session_token() != token


def test_permission_matrix_matches_documented_roles() -> None:
    assert ROLE_PERMISSIONS[Role.DEVELOPER] < ROLE_PERMISSIONS[Role.ADMIN]
    assert ROLE_PERMISSIONS[Role.ADMIN] < ROLE_PERMISSIONS[Role.SUPER_ADMIN]
    dev_denied = {
        Permission.APPROVE_HIGH_RISK,
        Permission.APPROVE_REMOTE_TARGET,
        Permission.APPROVE_PRODUCTION,
        Permission.FINDING_RISK_DECISION,
        Permission.USER_LIST,
        Permission.USER_MANAGE_DEVELOPERS,
        Permission.USER_MANAGE_PRIVILEGED,
        Permission.POLICY_GLOBAL,
        Permission.AUDIT_READ_ALL,
    }
    assert not any(has_permission("developer", p) for p in dev_denied)
    assert has_permission("admin", Permission.USER_MANAGE_DEVELOPERS)
    assert not has_permission("admin", Permission.USER_MANAGE_PRIVILEGED)
    assert not has_permission("admin", Permission.APPROVE_PRODUCTION)
    assert not has_permission("admin", Permission.POLICY_GLOBAL)
    assert all(has_permission("super_admin", p) for p in Permission)


def test_unknown_role_has_no_permissions() -> None:
    assert not any(has_permission("root", p) for p in Permission)
    assert not any(has_permission("", p) for p in Permission)


def test_access_levels_are_ordered() -> None:
    assert AccessLevel.READ < AccessLevel.RUN < AccessLevel.MANAGE


def test_rate_limiter_blocks_then_recovers() -> None:
    limiter = RateLimiter(2, window_seconds=0.2)
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")  # independent key
    time.sleep(0.25)
    assert limiter.allow("a")
