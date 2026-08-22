from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response, status
from pydantic import Field, field_validator

from app.api.dependencies import UnitOfWorkFactoryDep
from app.api.models import StrictApiModel
from app.auth.models import IssuedSession, SessionPrincipal, Workspace
from app.auth.service import AuthenticationError, AuthService
from app.settings import Settings, get_settings

SESSION_COOKIE = "session"
CSRF_COOKIE = "csrf"

router = APIRouter(prefix="/api/v1", tags=["auth"])


class SignupRequest(StrictApiModel):
    email: str = Field(min_length=3, max_length=320, description="Login email")
    password: str = Field(min_length=12, max_length=200, description="Plaintext password")
    workspace_name: str = Field(min_length=1, max_length=120, description="Initial workspace")

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.count("@") != 1:
            raise ValueError("invalid email")
        return normalized


class LoginRequest(StrictApiModel):
    email: str = Field(min_length=3, max_length=320, description="Login email")
    password: str = Field(min_length=1, max_length=200, description="Plaintext password")


class SessionResponse(StrictApiModel):
    user_id: str = Field(description="Authenticated user ID")
    email: str = Field(description="Authenticated email")
    expires_at: str = Field(description="ISO session expiry")


class WorkspaceRequest(StrictApiModel):
    name: str = Field(min_length=1, max_length=120, description="Workspace name")


class WorkspaceListResponse(StrictApiModel):
    workspaces: tuple[Workspace, ...] = Field(description="Accessible workspaces")


def _service(unit_of_work_factory: UnitOfWorkFactoryDep) -> AuthService:
    settings = get_settings()
    return AuthService(unit_of_work_factory, settings.session_ttl_seconds)


def _set_session_cookies(response: Response, issued: IssuedSession, settings: Settings) -> None:
    max_age = settings.session_ttl_seconds
    response.set_cookie(
        SESSION_COOKIE,
        issued.session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )


def require_allowed_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None or origin not in get_settings().allowed_origins:
        raise AuthenticationError("request origin is not allowed")


async def get_current_session(
    unit_of_work_factory: UnitOfWorkFactoryDep,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> SessionPrincipal:
    if not session_token:
        raise AuthenticationError("authentication required")
    return await _service(unit_of_work_factory).resolve(session_token)


CurrentSessionDep = Annotated[SessionPrincipal, Depends(get_current_session)]


def _response(principal: SessionPrincipal) -> SessionResponse:
    return SessionResponse(
        user_id=str(principal.user_id),
        email=principal.email,
        expires_at=principal.expires_at.isoformat(),
    )


@router.post("/auth/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    request: SignupRequest,
    response: Response,
    unit_of_work_factory: UnitOfWorkFactoryDep,
    _: Annotated[None, Depends(require_allowed_origin)],
) -> SessionResponse:
    issued = await _service(unit_of_work_factory).signup(
        request.email, request.password, request.workspace_name
    )
    _set_session_cookies(response, issued, get_settings())
    return _response(issued.principal)


@router.post("/auth/login")
async def login(
    request: LoginRequest,
    response: Response,
    unit_of_work_factory: UnitOfWorkFactoryDep,
    _: Annotated[None, Depends(require_allowed_origin)],
) -> SessionResponse:
    issued = await _service(unit_of_work_factory).login(request.email, request.password)
    _set_session_cookies(response, issued, get_settings())
    return _response(issued.principal)


@router.get("/auth/session")
async def session(principal: CurrentSessionDep) -> SessionResponse:
    return _response(principal)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    unit_of_work_factory: UnitOfWorkFactoryDep,
    principal: CurrentSessionDep,
    _: Annotated[None, Depends(require_allowed_origin)],
    csrf_token: Annotated[str, Header(alias="X-CSRF-Token")],
    csrf_cookie: Annotated[str, Cookie(alias=CSRF_COOKIE)],
) -> None:
    if not secrets.compare_digest(csrf_token, csrf_cookie):
        raise AuthenticationError("CSRF header and cookie differ")
    await _service(unit_of_work_factory).logout(principal, csrf_token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.get("/workspaces")
async def list_workspaces(
    unit_of_work_factory: UnitOfWorkFactoryDep, principal: CurrentSessionDep
) -> WorkspaceListResponse:
    workspaces = await _service(unit_of_work_factory).list_workspaces(principal.user_id)
    return WorkspaceListResponse(workspaces=workspaces)


@router.post("/workspaces", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    request: WorkspaceRequest,
    unit_of_work_factory: UnitOfWorkFactoryDep,
    principal: CurrentSessionDep,
    _: Annotated[None, Depends(require_allowed_origin)],
    csrf_token: Annotated[str, Header(alias="X-CSRF-Token")],
    csrf_cookie: Annotated[str, Cookie(alias=CSRF_COOKIE)],
) -> Workspace:
    if not secrets.compare_digest(csrf_token, csrf_cookie):
        raise AuthenticationError("CSRF header and cookie differ")
    service = _service(unit_of_work_factory)
    service.require_csrf(principal, csrf_token)
    return await service.create_workspace(principal.user_id, request.name)
