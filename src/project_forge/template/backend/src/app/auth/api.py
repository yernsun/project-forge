from __future__ import annotations

import secrets
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import AwareDatetime, ConfigDict, EmailStr, Field, SecretStr, field_validator

from app.api.dependencies import UnitOfWorkFactoryDep, prevent_auth_caching
from app.api.models import StrictApiModel
from app.auth.errors import (
    AuthenticationRequiredError,
    CsrfValidationError,
    OriginNotAllowedError,
)
from app.auth.models import IssuedSession, SessionPrincipal, Workspace
from app.auth.service import AuthService
from app.domain.base import to_camel
from app.settings import Settings, get_settings


class AuthApiModel(StrictApiModel):
    """Authentication DTOs never apply implicit whitespace changes to passwords."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=False,
    )


class SignupRequest(AuthApiModel):
    email: EmailStr = Field(description="Login email")
    password: SecretStr = Field(
        min_length=12, max_length=200, description="Plaintext password", repr=False
    )
    workspace_name: str = Field(min_length=1, max_length=120, description="Initial workspace")

    @field_validator("workspace_name")
    @classmethod
    def normalize_workspace_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("workspace name cannot be blank")
        return normalized


class LoginRequest(AuthApiModel):
    email: EmailStr = Field(description="Login email")
    password: SecretStr = Field(
        min_length=1, max_length=200, description="Plaintext password", repr=False
    )


class SessionResponse(StrictApiModel):
    user_id: UUID = Field(description="Authenticated user ID")
    email: EmailStr = Field(description="Authenticated email")
    expires_at: AwareDatetime = Field(description="Session expiry")


class WorkspaceRequest(StrictApiModel):
    name: str = Field(min_length=1, max_length=120, description="Workspace name")


class WorkspaceResponse(StrictApiModel):
    workspace_id: UUID = Field(description="Workspace ID")
    name: str = Field(description="Workspace name")
    created_at: AwareDatetime = Field(description="Workspace creation time")


class WorkspaceListResponse(StrictApiModel):
    workspaces: tuple[WorkspaceResponse, ...] = Field(description="Accessible workspaces")


class ErrorResponse(StrictApiModel):
    code: str = Field(description="Stable machine-readable error code")
    message: str = Field(description="Safe human-readable error message")


# FastAPI response metadata is intentionally heterogeneous and therefore uses Any.
AUTH_VALIDATION_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "Request validation failed"},
}
AUTH_REQUIRED_RESPONSES: dict[int | str, dict[str, Any]] = {
    **AUTH_VALIDATION_RESPONSES,
    401: {"model": ErrorResponse, "description": "Authentication required"},
}
AUTH_UNSAFE_RESPONSES: dict[int | str, dict[str, Any]] = {
    **AUTH_REQUIRED_RESPONSES,
    403: {"model": ErrorResponse, "description": "Origin, CSRF, or authorization denied"},
}
AUTH_SCOPED_READ_RESPONSES: dict[int | str, dict[str, Any]] = {
    **AUTH_REQUIRED_RESPONSES,
    403: {"model": ErrorResponse, "description": "Workspace authorization denied"},
}
RATE_LIMIT_RESPONSE: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "Authentication rate limit exceeded",
    "headers": {
        "Retry-After": {
            "description": "Seconds until the fixed window resets",
            "schema": {"type": "integer", "minimum": 1},
        }
    },
}


router = APIRouter(
    prefix="/api/v1",
    tags=["auth"],
    dependencies=[Depends(prevent_auth_caching)],
    responses=AUTH_VALIDATION_RESPONSES,
)


def _service(unit_of_work_factory: UnitOfWorkFactoryDep) -> AuthService:
    return AuthService(unit_of_work_factory, get_settings())


def _set_session_cookies(response: Response, issued: IssuedSession, settings: Settings) -> None:
    max_age = settings.session_ttl_seconds
    response.set_cookie(
        settings.session_cookie_name,
        issued.session_token.get_secret_value(),
        max_age=max_age,
        httponly=True,
        secure=settings.cookies_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        issued.csrf_token.get_secret_value(),
        max_age=max_age,
        httponly=False,
        secure=settings.cookies_secure,
        samesite="strict",
        path="/",
    )


def _source_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    referer = request.headers.get("referer")
    if not referer:
        return None
    parsed = urlsplit(referer)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def require_allowed_origin(request: Request) -> None:
    if _source_origin(request) not in get_settings().allowed_origins:
        raise OriginNotAllowedError()


AllowedOriginDep = Annotated[None, Depends(require_allowed_origin)]


async def get_current_session(
    request: Request,
    unit_of_work_factory: UnitOfWorkFactoryDep,
) -> SessionPrincipal:
    session_token = request.cookies.get(get_settings().session_cookie_name)
    if not session_token:
        raise AuthenticationRequiredError()
    return await _service(unit_of_work_factory).resolve(session_token)


CurrentSessionDep = Annotated[SessionPrincipal, Depends(get_current_session)]


async def get_unsafe_session(
    request: Request,
    unit_of_work_factory: UnitOfWorkFactoryDep,
    principal: CurrentSessionDep,
) -> SessionPrincipal:
    require_allowed_origin(request)
    settings = get_settings()
    csrf_header = request.headers.get("X-CSRF-Token")
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
    if not csrf_header or not csrf_cookie:
        raise CsrfValidationError()
    if not secrets.compare_digest(csrf_header, csrf_cookie):
        raise CsrfValidationError()
    _service(unit_of_work_factory).require_csrf(principal, csrf_header)
    return principal


UnsafeSessionDep = Annotated[SessionPrincipal, Depends(get_unsafe_session)]


def _response(principal: SessionPrincipal) -> SessionResponse:
    return SessionResponse(
        user_id=principal.user_id,
        email=principal.email,
        expires_at=principal.expires_at,
    )


def _workspace_response(workspace: Workspace) -> WorkspaceResponse:
    return WorkspaceResponse(
        workspace_id=workspace.workspace_id,
        name=workspace.name,
        created_at=workspace.created_at,
    )


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown-client"


@router.post(
    "/auth/signup",
    status_code=status.HTTP_201_CREATED,
    operation_id="signup",
    responses={
        403: {"model": ErrorResponse, "description": "Origin denied or signup disabled"},
        409: {"model": ErrorResponse, "description": "Email already exists"},
        429: RATE_LIMIT_RESPONSE,
    },
)
async def signup(
    request: SignupRequest,
    raw_request: Request,
    response: Response,
    unit_of_work_factory: UnitOfWorkFactoryDep,
    _: AllowedOriginDep,
) -> SessionResponse:
    issued = await _service(unit_of_work_factory).signup(
        str(request.email),
        request.password.get_secret_value(),
        request.workspace_name,
        _client_key(raw_request),
    )
    _set_session_cookies(response, issued, get_settings())
    return _response(issued.principal)


@router.post(
    "/auth/login",
    operation_id="login",
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        403: {"model": ErrorResponse, "description": "Origin denied"},
        429: RATE_LIMIT_RESPONSE,
    },
)
async def login(
    request: LoginRequest,
    raw_request: Request,
    response: Response,
    unit_of_work_factory: UnitOfWorkFactoryDep,
    _: AllowedOriginDep,
) -> SessionResponse:
    issued = await _service(unit_of_work_factory).login(
        str(request.email),
        request.password.get_secret_value(),
        _client_key(raw_request),
    )
    _set_session_cookies(response, issued, get_settings())
    return _response(issued.principal)


@router.get(
    "/auth/session",
    operation_id="getSession",
    responses=AUTH_REQUIRED_RESPONSES,
)
async def session(principal: CurrentSessionDep) -> SessionResponse:
    return _response(principal)


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="logout",
    responses=AUTH_UNSAFE_RESPONSES,
)
async def logout(
    response: Response,
    unit_of_work_factory: UnitOfWorkFactoryDep,
    principal: UnsafeSessionDep,
) -> None:
    await _service(unit_of_work_factory).logout(principal)
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.cookies_secure,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        secure=settings.cookies_secure,
        httponly=False,
        samesite="strict",
    )


@router.get(
    "/workspaces",
    operation_id="listWorkspaces",
    responses=AUTH_REQUIRED_RESPONSES,
)
async def list_workspaces(
    unit_of_work_factory: UnitOfWorkFactoryDep, principal: CurrentSessionDep
) -> WorkspaceListResponse:
    workspaces = await _service(unit_of_work_factory).list_workspaces(principal.user_id)
    return WorkspaceListResponse(
        workspaces=tuple(_workspace_response(workspace) for workspace in workspaces)
    )


@router.post(
    "/workspaces",
    status_code=status.HTTP_201_CREATED,
    operation_id="createWorkspace",
    responses=AUTH_UNSAFE_RESPONSES,
)
async def create_workspace(
    request: WorkspaceRequest,
    unit_of_work_factory: UnitOfWorkFactoryDep,
    principal: UnsafeSessionDep,
) -> WorkspaceResponse:
    workspace = await _service(unit_of_work_factory).create_workspace(
        principal.user_id, request.name
    )
    return _workspace_response(workspace)
