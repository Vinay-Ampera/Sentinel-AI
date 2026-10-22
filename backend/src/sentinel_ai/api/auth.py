import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from sentinel_ai.api.deps import (
    check_origin,
    current_principal,
    get_db,
    get_settings_dep,
    request_context,
)
from sentinel_ai.core import security
from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError
from sentinel_ai.schemas.identity import (
    LoginRequest,
    PasswordChangeRequest,
    SessionOut,
    UserOut,
)
from sentinel_ai.services import auth
from sentinel_ai.services.audit import RequestContext
from sentinel_ai.services.auth import Principal

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_absolute_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, Any]:
    check_origin(request, settings)
    limiter = request.app.state.login_limiter
    if not limiter.allow(ctx.ip_address or "unknown"):
        raise DomainError(429, "rate_limited", "Too many sign-in attempts; try again shortly")
    result = auth.login(db, settings, ctx, body.email, body.password.get_secret_value())
    _set_session_cookie(response, settings, result.session_token)
    return {"user": UserOut.from_record(result.user), "csrf_token": result.csrf_token}


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    auth.logout(db, ctx, principal)
    response = Response(status_code=204)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


@router.get("/me")
def me(
    request: Request,
    principal: Principal = Depends(current_principal),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    token = request.cookies[settings.session_cookie_name]
    return {
        "user": UserOut.from_record(principal.user),
        "csrf_token": security.csrf_token_for(settings.pepper(), token),
    }


@router.post("/password")
def change_password(
    body: PasswordChangeRequest,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> dict[str, int]:
    revoked = auth.change_password(
        db, ctx, principal, body.current.get_secret_value(), body.new.get_secret_value()
    )
    return {"other_sessions_revoked": revoked}


@router.get("/sessions")
def list_sessions(
    principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
) -> dict[str, list[SessionOut]]:
    return {
        "items": [
            SessionOut.from_record(s, principal.session_id)
            for s in auth.list_sessions(db, principal)
        ]
    }


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(request_context),
) -> Response:
    auth.revoke_own_session(db, ctx, principal, session_id)
    return Response(status_code=204)
