"""Authentication, CSRF, and authorization dependencies.

``require_permission`` is the standard guard for protected routes: it authenticates the
session, enforces CSRF + Origin on state-changing methods, checks the role permission, and
audits denials. Project scope is checked separately with ``require_project_access``.
"""

import ipaddress
import uuid
from collections.abc import Callable, Iterator

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from sentinel_ai.core import security
from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.permissions import AccessLevel, Permission, has_permission
from sentinel_ai.services import audit, auth
from sentinel_ai.services import project_access as project_access_service
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.auth import Principal

# Declared so Swagger UI's "Authorize" dialog can send the CSRF token on unsafe methods.
csrf_header = APIKeyHeader(
    name="X-CSRF-Token",
    auto_error=False,
    description="Value of csrf_token from POST /auth/login or GET /auth/me",
)

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    if not settings.auth_configured:
        raise DomainError(503, "auth_not_configured", "Authentication is not configured")
    return settings


def get_db(request: Request) -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on any exception.
    Services that must persist a failure (login failure, denial audit) commit explicitly
    before raising."""
    with request.app.state.session_factory() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


def _peer_ip(request: Request) -> str | None:
    """Direct peer address if it is a valid IP (unix sockets/test clients yield other text)."""
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def request_context(request: Request) -> RequestContext:
    return RequestContext(
        request_id=getattr(request.state, "request_id", None),
        ip_address=_peer_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


def check_origin(request: Request, settings: Settings) -> None:
    """Reject cross-site browser requests: a present Origin must be an allowed origin.

    Outside production the API's own origin is also accepted, so the built-in Swagger UI
    (/docs, served from the API itself) can sign in. This does not weaken CSRF: a page on
    another site cannot send an Origin equal to the API's own. Production accepts only
    ``CORS_ALLOWED_ORIGINS``.
    """
    origin = request.headers.get("origin")
    if origin is None or origin in settings.cors_allowed_origins:
        return
    if settings.app_env != "production" and origin == _own_origin(request):
        return
    raise DomainError(403, "csrf_failed", "Request origin is not allowed")


def _own_origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def current_principal(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    csrf_token: str | None = Security(csrf_header),
) -> Principal:
    token = request.cookies.get(settings.session_cookie_name)
    principal = auth.authenticate_session(db, settings, token) if token else None
    if principal is None:
        raise DomainError(401, "unauthenticated", "Authentication required")
    if request.method in UNSAFE_METHODS:
        check_origin(request, settings)
        supplied = csrf_token or ""
        expected = principal.csrf_token_hash
        if not supplied or not security.constant_time_equal(
            security.csrf_token_hash(settings.pepper(), supplied), expected
        ):
            raise DomainError(403, "csrf_failed", "CSRF token missing or invalid")
    request.state.principal = principal
    return principal


def require_permission(permission: Permission) -> Callable[..., Principal]:
    def dependency(
        request: Request,
        principal: Principal = Depends(current_principal),
    ) -> Principal:
        if has_permission(principal.user.role_name, permission):
            return principal
        # Persist the denial with its own session; the request transaction rolls back.
        with request.app.state.session_factory() as audit_db:
            audit.record(
                audit_db,
                request_context(request),
                action="authz.denied",
                outcome="denied",
                actor_user_id=principal.user.id,
                detail={"permission": permission.value, "path": request.url.path},
            )
            audit_db.commit()
        raise DomainError(403, "forbidden", "You do not have permission to perform this action")

    return dependency


def require_project_access(minimum: AccessLevel) -> Callable[..., Principal]:
    """Guard for routes with a ``{project_id}`` path parameter. Combine with
    ``require_permission`` (role) on the same route: both must allow the action."""

    def dependency(
        project_id: uuid.UUID,
        principal: Principal = Depends(current_principal),
        db: Session = Depends(get_db),
        ctx: RequestContext = Depends(request_context),
    ) -> Principal:
        project_access_service.require_project_access(db, principal.user, project_id, minimum)
        if project_access_service.is_privileged_only(db, principal.user, project_id):
            audit.record(
                db,
                ctx,
                action="project.privileged_access",
                outcome="success",
                actor_user_id=principal.user.id,
                project_id=project_id,
                detail={"min_level": minimum.name.lower()},
            )
        return principal

    return dependency
