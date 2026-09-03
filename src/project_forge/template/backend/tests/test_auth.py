from __future__ import annotations

import json
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from argon2.low_level import Type
from click import unstyle
from fastapi import FastAPI, Response
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from psycopg.errors import UniqueViolation
from pydantic import ValidationError
from starlette.requests import Request
from typer.testing import CliRunner

import app.auth.api as auth_api
import app.auth.service as auth_service_module
from app.api.errors import install_error_handlers
from app.api.observability import RequestContextMiddleware, current_request_id
from app.auth.api import SignupRequest, _set_session_cookies, get_unsafe_session
from app.auth.errors import (
    AuthenticationRequiredError,
    AuthRateLimitedError,
    CsrfValidationError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidSessionError,
    OriginNotAllowedError,
    SignupDisabledError,
    WorkspaceAccessDeniedError,
)
from app.auth.models import (
    IssuedSession,
    PasswordCredential,
    SessionPrincipal,
    UserIdentity,
    UserStatus,
    UserWithCredential,
    Workspace,
)
from app.auth.repository import PostgresAuthRepository
from app.auth.security import (
    PasswordVerification,
    generate_token,
    hash_password,
    hash_token,
    hmac_subject,
    token_matches,
    verify_password,
)
from app.auth.service import AuthService, RateLimitSpec, fixed_window
from app.cli import app as cli_app
from app.domain.base import utc_now
from app.main import app as fastapi_app
from app.repositories.base import RepositoryConnection
from app.settings import (
    COOKIE_PREFIX,
    DEVELOPMENT_RATE_LIMIT_SECRET,
    Settings,
    get_settings,
)
from app.uow.factory import UnitOfWorkFactory


def test_opaque_tokens_are_hashed_and_constant_time_checked() -> None:
    token = generate_token()
    digest = hash_token(token)
    assert token not in digest
    assert token_matches(token, digest)
    assert not token_matches(token + "x", digest)


def test_argon2id_password_round_trip_and_dummy_path() -> None:
    digest = hash_password("correct horse battery staple")
    assert digest.startswith("$argon2id$")
    assert verify_password(digest, "correct horse battery staple").valid
    assert not verify_password(digest, "wrong password").valid
    assert not verify_password(None, "wrong password").valid

    legacy = PasswordHasher(
        time_cost=1,
        memory_cost=8 * 1024,
        parallelism=1,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    ).hash("correct horse battery staple")
    assert verify_password(legacy, "correct horse battery staple").needs_rehash


def test_hmac_rate_limit_subjects_do_not_store_raw_identity() -> None:
    first = hmac_subject("a" * 32, "login:email", "person@example.com")
    second = hmac_subject("a" * 32, "login:client", "person@example.com")
    assert len(first) == 64
    assert "person@example.com" not in first
    assert first != second


def test_auth_request_preserves_password_whitespace_and_normalizes_workspace() -> None:
    request = SignupRequest.model_validate(
        {
            "email": "person@example.com",
            "password": "  long password  ",
            "workspaceName": "  Example  ",
        }
    )
    assert request.password.get_secret_value() == "  long password  "
    assert request.workspace_name == "Example"
    assert "long password" not in repr(request)


def test_auth_request_rejects_invalid_email_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SignupRequest.model_validate(
            {
                "email": "not-an-email",
                "password": "correct horse battery staple",
                "workspaceName": "Example",
            }
        )
    with pytest.raises(ValidationError):
        SignupRequest.model_validate(
            {
                "email": "person@example.com",
                "password": "correct horse battery staple",
                "workspaceName": "Example",
                "admin": True,
            }
        )


def test_production_auth_settings_fail_closed() -> None:
    with pytest.raises(ValidationError, match="secure session cookies"):
        Settings(
            app_env="production",
            database_url="postgresql://safe:secret@db/app",
            allowed_origins_csv="https://app.example.com",
            session_cookie_secure=False,
            auth_rate_limit_secret="x" * 32,
            forwarded_allow_ips_csv="172.20.0.20",
        )
    with pytest.raises(ValidationError, match="unique 32-byte"):
        Settings(
            app_env="production",
            database_url="postgresql://safe:secret@db/app",
            allowed_origins_csv="https://app.example.com",
            session_cookie_secure=True,
            auth_rate_limit_secret=DEVELOPMENT_RATE_LIMIT_SECRET,
            forwarded_allow_ips_csv="172.20.0.20",
        )


def test_production_uses_host_cookies_and_disables_signup_by_default() -> None:
    settings = Settings(
        app_env="production",
        database_url="postgresql://safe:secret@db/app",
        allowed_origins_csv="https://app.example.com/",
        session_cookie_secure=True,
        auth_rate_limit_secret="x" * 32,
        forwarded_allow_ips_csv="172.20.0.20,172.20.1.0/24",
    )
    assert settings.session_cookie_name == f"__Host-{COOKIE_PREFIX}-session"
    assert settings.csrf_cookie_name == f"__Host-{COOKIE_PREFIX}-csrf"
    assert settings.allowed_origins == frozenset({"https://app.example.com"})
    assert settings.forwarded_allow_ips == ("172.20.0.20", "172.20.1.0/24")
    assert not settings.is_signup_enabled

    development = Settings(session_cookie_secure=True)
    assert development.session_cookie_name == f"{COOKIE_PREFIX}-session"
    assert development.csrf_cookie_name == f"{COOKIE_PREFIX}-csrf"


def test_issued_cookie_attributes_are_host_only_strict_and_secret_aware() -> None:
    settings = Settings(
        app_env="production",
        database_url="postgresql://safe:secret@db/app",
        allowed_origins_csv="https://app.example.com",
        session_cookie_secure=True,
        auth_rate_limit_secret="x" * 32,
        forwarded_allow_ips_csv="172.20.0.20",
    )
    now = utc_now()
    issued = IssuedSession(
        principal=SessionPrincipal(
            session_id="a7a9fda8-874b-44fb-8b05-489a263f8032",
            user_id="8a08795c-33c2-4adf-9f49-ddf32fddeef1",
            email="person@example.com",
            csrf_hash=hash_token("csrf-token"),
            expires_at=now.replace(year=now.year + 1),
        ),
        session_token=generate_token(),
        csrf_token=generate_token(),
    )
    response = Response()

    _set_session_cookies(response, issued, settings)

    cookies = response.headers.getlist("set-cookie")
    session_cookie = next(value for value in cookies if settings.session_cookie_name in value)
    csrf_cookie = next(value for value in cookies if settings.csrf_cookie_name in value)
    for value in cookies:
        assert "Secure" in value
        assert "SameSite=strict" in value
        assert "Path=/" in value
        assert "Domain=" not in value
    assert "HttpOnly" in session_cookie
    assert "HttpOnly" not in csrf_cookie


def _dependency_names(route: APIRoute) -> set[str]:
    names: set[str] = set()

    def collect(dependant: object) -> None:
        dependencies = getattr(dependant, "dependencies", ())
        for dependency in dependencies:
            call = getattr(dependency, "call", None)
            name = getattr(call, "__name__", None)
            if isinstance(name, str):
                names.add(name)
            collect(dependency)

    collect(route.dependant)
    return names


def _emitted_routes() -> list[APIRoute]:
    routes: list[APIRoute] = []
    for included in fastapi_app.routes:
        if isinstance(included, APIRoute):
            routes.append(included)
        original_router = getattr(included, "original_router", None)
        routes.extend(
            route for route in getattr(original_router, "routes", ()) if isinstance(route, APIRoute)
        )
    return routes


def test_every_emitted_unsafe_route_uses_the_shared_security_dependency() -> None:
    public_auth_paths = {"/api/v1/auth/signup", "/api/v1/auth/login"}
    unsafe_methods = {"POST", "PUT", "PATCH", "DELETE"}
    routes = _emitted_routes()
    emitted_unsafe = [route for route in routes if route.methods & unsafe_methods]
    assert emitted_unsafe
    for route in emitted_unsafe:
        dependencies = _dependency_names(route)
        if route.path in public_auth_paths:
            assert "require_allowed_origin" in dependencies
        else:
            assert "get_unsafe_session" in dependencies


def test_every_auth_related_route_uses_the_shared_no_store_dependency() -> None:
    routes = [
        route
        for route in _emitted_routes()
        if route.path == "/api/v1/workspaces"
        or route.path.startswith(("/api/v1/auth/", "/api/v1/workspaces/"))
    ]
    assert routes
    for route in routes:
        assert "prevent_auth_caching" in _dependency_names(route)


def test_production_rejects_non_origin_allowlist_values() -> None:
    with pytest.raises(ValidationError, match="without credentials or paths"):
        Settings(
            app_env="production",
            database_url="postgresql://safe:secret@db/app",
            allowed_origins_csv="https://app.example.com/login",
            session_cookie_secure=True,
            auth_rate_limit_secret="x" * 32,
        )


@pytest.mark.parametrize(
    "value", ["", "*", "0.0.0.0/0", "::/0", "not-an-ip", "172.20.0.1/24"]
)
def test_production_requires_explicit_valid_trusted_proxies(value: str) -> None:
    with pytest.raises(ValidationError, match=r"trusted proxy|FORWARDED_ALLOW_IPS"):
        Settings(
            app_env="production",
            database_url="postgresql://safe:secret@db/app",
            allowed_origins_csv="https://app.example.com",
            session_cookie_secure=True,
            auth_rate_limit_secret="x" * 32,
            forwarded_allow_ips_csv=value,
        )


def _request(*, csrf_cookie: str | None, csrf_header: str | None) -> Request:
    allowed_origin = sorted(get_settings().allowed_origins)[0]
    headers = [(b"origin", allowed_origin.encode())]
    cookies = [b"session=fake-session"]
    if csrf_cookie is not None:
        cookies.append(f"{get_settings().csrf_cookie_name}={csrf_cookie}".encode())
    headers.append((b"cookie", b"; ".join(cookies)))
    if csrf_header is not None:
        headers.append((b"x-csrf-token", csrf_header.encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/workspaces",
            "raw_path": b"/api/v1/workspaces",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("localhost", 8000),
        }
    )


@pytest.mark.asyncio
async def test_unsafe_session_requires_header_cookie_and_session_binding() -> None:
    csrf = generate_token()
    now = utc_now()
    principal = SessionPrincipal(
        session_id="a7a9fda8-874b-44fb-8b05-489a263f8032",
        user_id="8a08795c-33c2-4adf-9f49-ddf32fddeef1",
        email="person@example.com",
        csrf_hash=hash_token(csrf),
        expires_at=now.replace(year=now.year + 1),
    )
    factory = cast(UnitOfWorkFactory, object())
    resolved = await get_unsafe_session(
        _request(csrf_cookie=csrf, csrf_header=csrf), factory, principal
    )
    assert resolved is principal
    with pytest.raises(CsrfValidationError):
        await get_unsafe_session(_request(csrf_cookie=csrf, csrf_header=None), factory, principal)
    with pytest.raises(CsrfValidationError):
        await get_unsafe_session(
            _request(csrf_cookie=csrf, csrf_header=csrf + "different"),
            factory,
            principal,
        )


def _api_request(
    *,
    headers: tuple[tuple[bytes, bytes], ...] = (),
    session_token: str | None = None,
    with_client: bool = True,
) -> Request:
    request_headers = list(headers)
    if session_token is not None:
        request_headers.append(
            (
                b"cookie",
                f"{get_settings().session_cookie_name}={session_token}".encode(),
            )
        )
    scope: dict[str, object] = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/auth/login",
        "raw_path": b"/api/v1/auth/login",
        "query_string": b"",
        "headers": request_headers,
        "server": ("localhost", 8000),
    }
    if with_client:
        scope["client"] = ("127.0.0.1", 12345)
    return Request(scope)


def test_auth_origin_resolution_and_workspace_name_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(allowed_origins_csv="http://localhost:5173")
    monkeypatch.setattr(auth_api, "get_settings", lambda: settings)
    origin = _api_request(headers=((b"origin", b"http://localhost:5173/"),))
    assert auth_api._source_origin(origin) == "http://localhost:5173"
    auth_api.require_allowed_origin(origin)

    referer = _api_request(
        headers=((b"referer", b"http://localhost:5173/workspaces/one"),)
    )
    assert auth_api._source_origin(referer) == "http://localhost:5173"
    assert auth_api._source_origin(_api_request()) is None
    invalid_referer = _api_request(headers=((b"referer", b"mailto:person@example.com"),))
    assert auth_api._source_origin(invalid_referer) is None
    with pytest.raises(OriginNotAllowedError):
        auth_api.require_allowed_origin(
            _api_request(headers=((b"origin", b"http://attacker.invalid"),))
        )
    with pytest.raises(ValidationError, match="workspace name cannot be blank"):
        SignupRequest.model_validate(
            {
                "email": "person@example.com",
                "password": "correct horse battery staple",
                "workspaceName": "   ",
            }
        )


@pytest.mark.asyncio
async def test_auth_api_dependencies_and_routes_delegate_without_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(allowed_origins_csv="http://localhost:5173")
    monkeypatch.setattr(auth_api, "get_settings", lambda: settings)
    now = utc_now()
    principal = SessionPrincipal(
        session_id=uuid4(),
        user_id=uuid4(),
        email="person@example.com",
        csrf_hash=hash_token("csrf-token"),
        expires_at=now.replace(year=now.year + 1),
    )
    issued = IssuedSession(
        principal=principal,
        session_token=generate_token(),
        csrf_token=generate_token(),
    )
    workspace = Workspace(workspace_id=uuid4(), name="Example", created_at=now)
    service = type(
        "FakeAuthService",
        (),
        {
            "signup": AsyncMock(return_value=issued),
            "login": AsyncMock(return_value=issued),
            "resolve": AsyncMock(return_value=principal),
            "logout": AsyncMock(),
            "list_workspaces": AsyncMock(return_value=(workspace,)),
            "create_workspace": AsyncMock(return_value=workspace),
            "require_csrf": Mock(),
        },
    )()
    monkeypatch.setattr(auth_api, "_service", lambda _factory: service)
    factory = cast(UnitOfWorkFactory, object())

    with pytest.raises(AuthenticationRequiredError):
        await auth_api.get_current_session(_api_request(), factory)
    resolved = await auth_api.get_current_session(
        _api_request(session_token="opaque-session"), factory
    )
    assert resolved is principal
    service.resolve.assert_awaited_once_with("opaque-session")

    raw_request = _api_request(
        headers=((b"origin", b"http://localhost:5173"),)
    )
    assert auth_api._client_key(raw_request) == "127.0.0.1"
    assert auth_api._client_key(_api_request(with_client=False)) == "unknown-client"

    signup_response = Response()
    signup_result = await auth_api.signup(
        auth_api.SignupRequest(
            email="new@example.com",
            password="correct horse battery staple",
            workspace_name="Example",
        ),
        raw_request,
        signup_response,
        factory,
        None,
    )
    assert signup_result.user_id == principal.user_id
    assert len(signup_response.headers.getlist("set-cookie")) == 2

    login_response = Response()
    login_result = await auth_api.login(
        auth_api.LoginRequest(email="person@example.com", password="password"),
        raw_request,
        login_response,
        factory,
        None,
    )
    assert login_result.email == principal.email
    assert (await auth_api.session(principal)).user_id == principal.user_id

    logout_response = Response()
    await auth_api.logout(logout_response, factory, principal)
    service.logout.assert_awaited_once_with(principal)
    assert len(logout_response.headers.getlist("set-cookie")) == 2

    listed = await auth_api.list_workspaces(factory, principal)
    assert listed.workspaces[0].workspace_id == workspace.workspace_id
    created = await auth_api.create_workspace(
        auth_api.WorkspaceRequest(name="Example"), factory, principal
    )
    assert created.workspace_id == workspace.workspace_id


class _RateRepository:
    async def consume_rate_limit(self, **_: object) -> int:
        return 2


class _RateUnitOfWork:
    auth = _RateRepository()


class _RateContext:
    def __init__(self, exits: list[type[BaseException] | None]) -> None:
        self._exits = exits

    async def __aenter__(self) -> _RateUnitOfWork:
        return _RateUnitOfWork()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object,
    ) -> None:
        self._exits.append(exc_type)


class _RateFactory:
    def __init__(self) -> None:
        self.exits: list[type[BaseException] | None] = []

    def __call__(self) -> _RateContext:
        return _RateContext(self.exits)


@pytest.mark.asyncio
async def test_rate_limit_transaction_commits_before_rejection() -> None:
    factory = _RateFactory()
    settings = Settings(auth_rate_limit_secret="x" * 32)
    service = AuthService(cast(UnitOfWorkFactory, factory), settings)
    with pytest.raises(AuthRateLimitedError):
        await service._consume_rate_limit(
            RateLimitSpec(
                scope="login:email_ip",
                subject="person@example.com|127.0.0.1",
                maximum=1,
                window_seconds=300,
            )
        )
    assert factory.exits == [None]


def test_auth_validation_errors_redact_input_and_disable_caching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    warnings: list[dict[str, object]] = []

    def capture_event(*_: object, **fields: object) -> None:
        warnings.append({"request_id": current_request_id(), **fields})

    monkeypatch.setattr("app.api.errors.log_event", capture_event)

    @app.post("/api/v1/auth/signup")
    async def validate_signup(_request: SignupRequest) -> None:
        return None

    secret = "too-short"
    response = TestClient(app).post(
        "/api/v1/auth/signup",
        headers={"X-Request-ID": "auth-validation-1"},
        json={
            "email": "person@example.com",
            "password": secret,
            "workspaceName": "Example",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "request_validation_failed",
        "message": "request validation failed",
    }
    assert secret not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-request-id"] == "auth-validation-1"
    assert warnings[0]["request_id"] == "auth-validation-1"
    assert secret not in str(warnings)
    assert "person@example.com" not in str(warnings)
    assert "Example" not in str(warnings)


def test_duplicate_request_ids_are_replaced() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/")
    async def index() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).get(
        "/",
        headers=[("X-Request-ID", "first"), ("X-Request-ID", "second")],
    )

    request_id = response.headers["x-request-id"]
    assert request_id not in {"first", "second", "first, second"}
    assert len(request_id) == 32


def test_general_validation_errors_keep_fastapi_contract_and_cache_policy() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/api/v1/items/{item_id}")
    async def validate_item_id(item_id: int) -> None:
        return None

    response = TestClient(app).get("/api/v1/items/not-an-integer")

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "int_parsing",
            "loc": ["path", "item_id"],
            "msg": "Input should be a valid integer, unable to parse string as an integer",
            "input": "not-an-integer",
        }
    ]
    assert "cache-control" not in response.headers


def test_general_password_validation_errors_redact_only_the_secret_input() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/api/v1/public-signup")
    async def validate_public_signup(_request: SignupRequest) -> None:
        return None

    secret = "too-short"
    response = TestClient(app).post(
        "/api/v1/public-signup",
        json={
            "email": "person@example.com",
            "password": secret,
            "workspaceName": "Example",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == "[redacted]"
    assert secret not in response.text
    assert "cache-control" not in response.headers


def test_auth_related_openapi_uses_the_stable_validation_error_schema() -> None:
    schema = fastapi_app.openapi()
    operations = {"get", "post", "put", "patch", "delete"}
    checked = 0
    for path, path_item in schema["paths"].items():
        if path != "/api/v1/workspaces" and not path.startswith(
            ("/api/v1/auth/", "/api/v1/workspaces/")
        ):
            continue
        for method, operation in path_item.items():
            if method not in operations:
                continue
            response = operation["responses"]["422"]
            assert response["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
            checked += 1
    assert checked


def test_auth_errors_have_stable_status_code_and_no_store() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/limited")
    async def limited() -> None:
        raise AuthRateLimitedError(retry_after_seconds=17)

    response = TestClient(app).get("/limited")
    assert response.status_code == 429
    assert response.json() == {
        "code": "auth_rate_limited",
        "message": "too many authentication attempts",
    }
    assert response.headers["retry-after"] == "17"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (InvalidCredentialsError(), 401, "invalid_credentials"),
        (InvalidSessionError(), 401, "invalid_or_expired_session"),
        (OriginNotAllowedError(), 403, "origin_not_allowed"),
        (CsrfValidationError(), 403, "csrf_failed"),
        (WorkspaceAccessDeniedError(), 403, "workspace_access_denied"),
        (SignupDisabledError(), 403, "signup_disabled"),
        (EmailAlreadyExistsError(), 409, "email_already_exists"),
    ],
)
def test_signup_and_login_errors_have_explicit_http_contracts(
    error: Exception, status_code: int, code: str
) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/failure")
    async def failure() -> None:
        raise error

    response = TestClient(app).get("/failure")
    assert response.status_code == status_code
    assert response.json()["code"] == code
    assert response.headers["cache-control"] == "no-store"


def test_auth_purge_cli_exposes_dry_run() -> None:
    result = CliRunner().invoke(cli_app, ["auth", "purge-expired", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in unstyle(result.stdout)


def test_config_cli_reports_only_redacted_effective_settings() -> None:
    result = CliRunner().invoke(
        cli_app,
        ["config", "check", "--json"],
        env={"APP_ALLOWED_ORIGINS": "http://localhost:5173"},
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["environment"] == "development"
    assert summary["authentication"]["allowed_origins"] == ["http://localhost:5173"]
    assert "database_url" not in result.stdout
    assert DEVELOPMENT_RATE_LIMIT_SECRET not in result.stdout


def test_config_cli_sanitizes_invalid_environment_values() -> None:
    database_secret = "database-password-must-not-leak"
    rate_limit_secret = "rate-limit-secret-must-not-leak-123456789"
    result = CliRunner().invoke(
        cli_app,
        ["config", "check", "--json"],
        env={
            "APP_ENV": "production",
            "DATABASE_URL": f"postgresql://app:{database_secret}@db:5432/app",
            "APP_ALLOWED_ORIGINS": "http://172.20.0.10:8173",
            "APP_AUTH_RATE_LIMIT_SECRET": rate_limit_secret,
            "APP_SESSION_COOKIE_SECURE": "true",
            "FORWARDED_ALLOW_IPS": "127.0.0.1",
        },
    )

    assert result.exit_code == 2
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert report["errors"]
    assert database_secret not in result.output
    assert rate_limit_secret not in result.output
    assert "postgresql://" not in result.output


def test_fixed_window_is_stable_within_the_window() -> None:
    now = utc_now()
    start, end = fixed_window(now, 60)
    assert start <= now < end
    assert (end - start).total_seconds() == 60


@pytest.mark.asyncio
async def test_auth_repository_maps_rows_and_covers_persistence_failures() -> None:
    connection = AsyncMock()
    repository = PostgresAuthRepository(cast(RepositoryConnection, connection))
    user = _user()
    identity = user.identity
    credential = user.credential
    now = identity.created_at
    identity_row = identity.model_dump(mode="python") | credential.model_dump(mode="python")

    connection.fetch_one.return_value = identity_row
    assert await repository.add_user(identity, credential) == identity
    connection.fetch_one.return_value = None
    with pytest.raises(RuntimeError, match="did not return a user"):
        await repository.add_user(identity, credential)
    connection.fetch_one.side_effect = UniqueViolation("duplicate email")
    with pytest.raises(EmailAlreadyExistsError):
        await repository.add_user(identity, credential)
    connection.fetch_one.side_effect = None

    connection.fetch_one.return_value = identity_row
    found = await repository.find_user_by_email(identity.email)
    assert found is not None and found.identity == identity
    connection.fetch_one.return_value = None
    assert await repository.find_user_by_email("missing@example.com") is None

    await repository.update_password_hash(identity.user_id, "replacement", now)
    workspace = Workspace(workspace_id=uuid4(), name="Example", created_at=now)
    assert await repository.add_workspace(workspace, identity.user_id) == workspace
    connection.fetch_all.return_value = [workspace.model_dump(mode="python")]
    assert await repository.list_workspaces(identity.user_id) == (workspace,)
    connection.fetch_one.return_value = {"allowed": True}
    assert await repository.is_workspace_member(identity.user_id, workspace.workspace_id)
    connection.fetch_one.return_value = None
    assert not await repository.is_workspace_member(identity.user_id, workspace.workspace_id)

    session_id = uuid4()
    expires_at = now.replace(year=now.year + 1)
    await repository.add_session(
        session_id=session_id,
        user_id=identity.user_id,
        token_hash="token-hash",
        csrf_hash="csrf-hash",
        expires_at=expires_at,
        created_at=now,
    )
    principal_row = {
        "session_id": session_id,
        "user_id": identity.user_id,
        "email": identity.email,
        "csrf_hash": "csrf-hash",
        "expires_at": expires_at,
    }
    connection.fetch_one.return_value = principal_row
    assert (await repository.resolve_session("token-hash", now)) is not None
    connection.fetch_one.return_value = None
    assert await repository.resolve_session("expired", now) is None
    await repository.delete_session(session_id)

    connection.fetch_one.return_value = {"attempt_count": 2}
    assert await repository.consume_rate_limit(
        scope="login:ip",
        subject_hash="subject-hash",
        window_started_at=now,
        expires_at=expires_at,
    ) == 2
    connection.fetch_one.return_value = None
    with pytest.raises(RuntimeError, match="UPSERT did not return"):
        await repository.consume_rate_limit(
            scope="login:ip",
            subject_hash="subject-hash",
            window_started_at=now,
            expires_at=expires_at,
        )
    await repository.clear_rate_limit(
        scope="login:ip", subject_hash="subject-hash", window_started_at=now
    )

    connection.execute.side_effect = [2, 3]
    assert await repository.purge_expired(now) == (2, 3)
    connection.execute.side_effect = None
    connection.fetch_one.side_effect = [{"count": 4}, {"count": 5}]
    assert await repository.count_expired(now) == (4, 5)
    connection.fetch_one.side_effect = [None, {"count": 0}]
    with pytest.raises(RuntimeError, match="count query returned no row"):
        await repository.count_expired(now)


class _LifecycleRepository:
    def __init__(
        self, user: UserWithCredential | None, *, rate_counts: tuple[int, ...] = ()
    ) -> None:
        self.user = user
        self._rate_counts = list(rate_counts)
        self.rate_calls: list[dict[str, object]] = []
        self.cleared_scopes: list[str] = []
        self.updated_hashes: list[str] = []

    async def consume_rate_limit(self, **values: object) -> int:
        self.rate_calls.append(values)
        return self._rate_counts.pop(0) if self._rate_counts else 1

    async def find_user_by_email(self, _email: str) -> UserWithCredential | None:
        return self.user

    async def clear_rate_limit(self, **values: object) -> None:
        self.cleared_scopes.append(str(values["scope"]))

    async def update_password_hash(
        self, _user_id: object, password_hash: str, _now: object
    ) -> None:
        self.updated_hashes.append(password_hash)

    async def add_session(self, **_values: object) -> None:
        return None

    async def add_user(
        self, identity: UserIdentity, _credential: PasswordCredential
    ) -> UserIdentity:
        return identity

    async def add_workspace(self, workspace: Workspace, _owner_id: object) -> Workspace:
        return workspace


class _LifecycleUnitOfWork:
    def __init__(self, repository: _LifecycleRepository) -> None:
        self.auth = repository


class _LifecycleContext:
    def __init__(
        self,
        repository: _LifecycleRepository,
        exits: list[type[BaseException] | None],
    ) -> None:
        self._repository = repository
        self._exits = exits

    async def __aenter__(self) -> _LifecycleUnitOfWork:
        return _LifecycleUnitOfWork(self._repository)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object,
    ) -> None:
        self._exits.append(exc_type)


class _LifecycleFactory:
    def __init__(self, repository: _LifecycleRepository) -> None:
        self._repository = repository
        self.exits: list[type[BaseException] | None] = []

    def __call__(self) -> _LifecycleContext:
        return _LifecycleContext(self._repository, self.exits)


def _user() -> UserWithCredential:
    now = utc_now()
    identity = UserIdentity(
        user_id="8a08795c-33c2-4adf-9f49-ddf32fddeef1",
        email="person@example.com",
        status=UserStatus.ACTIVE,
        version=1,
        created_at=now,
        updated_at=now,
    )
    return UserWithCredential(
        identity=identity,
        credential=PasswordCredential(
            user_id=identity.user_id,
            password_hash=hash_password("correct horse battery staple"),
            password_updated_at=now,
        ),
    )


@pytest.mark.asyncio
async def test_login_uses_exact_buckets_and_clears_only_email_ip_on_success() -> None:
    repository = _LifecycleRepository(_user())
    factory = _LifecycleFactory(repository)
    service = AuthService(cast(UnitOfWorkFactory, factory), Settings())
    await service.login("person@example.com", "correct horse battery staple", "127.0.0.1")
    assert [call["scope"] for call in repository.rate_calls] == [
        "login:ip",
        "login:email_ip",
    ]
    windows = [
        (call["expires_at"] - call["window_started_at"]).total_seconds()  # type: ignore[operator]
        for call in repository.rate_calls
    ]
    assert windows == [300, 300]
    assert repository.cleared_scopes == ["login:email_ip"]
    assert factory.exits == [None, None, None]


@pytest.mark.asyncio
async def test_failed_login_keeps_both_rate_limit_buckets() -> None:
    repository = _LifecycleRepository(None)
    factory = _LifecycleFactory(repository)
    service = AuthService(cast(UnitOfWorkFactory, factory), Settings())
    with pytest.raises(InvalidCredentialsError):
        await service.login("missing@example.com", "wrong password", "127.0.0.1")
    assert [call["scope"] for call in repository.rate_calls] == [
        "login:ip",
        "login:email_ip",
    ]
    assert repository.cleared_scopes == []
    assert factory.exits == [None, None, InvalidCredentialsError]


@pytest.mark.asyncio
async def test_ip_limit_rejects_before_creating_an_email_ip_bucket() -> None:
    repository = _LifecycleRepository(None, rate_counts=(2,))
    factory = _LifecycleFactory(repository)
    service = AuthService(
        cast(UnitOfWorkFactory, factory),
        Settings(auth_login_ip_limit=1, auth_login_email_ip_limit=100),
    )

    with pytest.raises(AuthRateLimitedError):
        await service.login("new-target@example.com", "wrong password", "127.0.0.1")

    assert [call["scope"] for call in repository.rate_calls] == ["login:ip"]
    assert repository.cleared_scopes == []
    assert factory.exits == [None]


@pytest.mark.asyncio
async def test_signup_uses_only_the_hourly_ip_bucket() -> None:
    repository = _LifecycleRepository(None)
    factory = _LifecycleFactory(repository)
    service = AuthService(cast(UnitOfWorkFactory, factory), Settings(signup_enabled=True))
    await service.signup(
        "new@example.com",
        "correct horse battery staple",
        "Example",
        "127.0.0.1",
    )
    assert [call["scope"] for call in repository.rate_calls] == ["signup:ip"]
    call = repository.rate_calls[0]
    assert (call["expires_at"] - call["window_started_at"]).total_seconds() == 3600  # type: ignore[operator]


@pytest.mark.asyncio
async def test_signup_disabled_fails_before_database_or_hashing_work() -> None:
    repository = _LifecycleRepository(None)
    factory = _LifecycleFactory(repository)
    service = AuthService(cast(UnitOfWorkFactory, factory), Settings(signup_enabled=False))
    with pytest.raises(SignupDisabledError):
        await service.signup(
            "new@example.com",
            "correct horse battery staple",
            "Example",
            "127.0.0.1",
        )
    assert repository.rate_calls == []


@pytest.mark.asyncio
async def test_login_rehashes_and_session_workspace_cleanup_methods_delegate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _LifecycleRepository(_user())
    factory = _LifecycleFactory(repository)
    service = AuthService(cast(UnitOfWorkFactory, factory), Settings())
    monkeypatch.setattr(
        auth_service_module,
        "verify_password",
        lambda _password_hash, _password: PasswordVerification(
            valid=True, needs_rehash=True
        ),
    )
    monkeypatch.setattr(auth_service_module, "hash_password", lambda _password: "replacement")
    await service.login("person@example.com", "password", "127.0.0.1")
    assert repository.updated_hashes == ["replacement"]

    now = utc_now()
    principal = SessionPrincipal(
        session_id=uuid4(),
        user_id=uuid4(),
        email="person@example.com",
        csrf_hash=hash_token("csrf-token"),
        expires_at=now.replace(year=now.year + 1),
    )
    workspace = Workspace(workspace_id=uuid4(), name="Example", created_at=now)
    persistence = type(
        "AuthPersistence",
        (),
        {
            "resolve_session": AsyncMock(side_effect=[principal, None]),
            "delete_session": AsyncMock(),
            "add_workspace": AsyncMock(return_value=workspace),
            "list_workspaces": AsyncMock(return_value=(workspace,)),
            "count_expired": AsyncMock(return_value=(2, 3)),
            "purge_expired": AsyncMock(return_value=(4, 5)),
        },
    )()
    lifecycle = AuthService(
        cast(UnitOfWorkFactory, _LifecycleFactory(persistence)), Settings()
    )
    assert await lifecycle.resolve("opaque-token") is principal
    with pytest.raises(InvalidSessionError):
        await lifecycle.resolve("expired-token")
    await lifecycle.logout(principal)
    persistence.delete_session.assert_awaited_once_with(principal.session_id)
    assert await lifecycle.create_workspace(principal.user_id, "Example") == workspace
    assert await lifecycle.list_workspaces(principal.user_id) == (workspace,)
    assert await lifecycle.purge_expired(dry_run=True) == (2, 3)
    assert await lifecycle.purge_expired() == (4, 5)
    with pytest.raises(CsrfValidationError):
        lifecycle.require_csrf(principal, "wrong-token")
