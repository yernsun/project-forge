from __future__ import annotations

from typing import cast

import pytest
from argon2 import PasswordHasher
from argon2.low_level import Type
from fastapi import FastAPI, Response
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request
from typer.testing import CliRunner

from app.api.errors import install_error_handlers
from app.auth.api import SignupRequest, _set_session_cookies, get_unsafe_session
from app.auth.errors import (
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
from app.auth.security import (
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
from app.settings import COOKIE_PREFIX, Settings, get_settings
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
            forwarded_allow_ips_csv="10.0.0.10",
        )
    with pytest.raises(ValidationError, match="unique 32-byte"):
        Settings(
            app_env="production",
            database_url="postgresql://safe:secret@db/app",
            allowed_origins_csv="https://app.example.com",
            session_cookie_secure=True,
        )


def test_production_uses_host_cookies_and_disables_signup_by_default() -> None:
    settings = Settings(
        app_env="production",
        database_url="postgresql://safe:secret@db/app",
        allowed_origins_csv="https://app.example.com/",
        session_cookie_secure=True,
        auth_rate_limit_secret="x" * 32,
        forwarded_allow_ips_csv="10.0.0.10,10.0.1.0/24",
    )
    assert settings.session_cookie_name == f"__Host-{COOKIE_PREFIX}-session"
    assert settings.csrf_cookie_name == f"__Host-{COOKIE_PREFIX}-csrf"
    assert settings.allowed_origins == frozenset({"https://app.example.com"})
    assert settings.forwarded_allow_ips == ("10.0.0.10", "10.0.1.0/24")
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
        forwarded_allow_ips_csv="10.0.0.10",
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
    "value", ["", "*", "0.0.0.0/0", "::/0", "not-an-ip", "10.0.0.1/24"]
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
    headers = [(b"origin", b"http://localhost:5173")]
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


def test_auth_validation_errors_redact_input_and_disable_caching() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/api/v1/auth/signup")
    async def validate_signup(_request: SignupRequest) -> None:
        return None

    secret = "too-short"
    response = TestClient(app).post(
        "/api/v1/auth/signup",
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
    assert "--dry-run" in result.stdout


def test_fixed_window_is_stable_within_the_window() -> None:
    now = utc_now()
    start, end = fixed_window(now, 60)
    assert start <= now < end
    assert (end - start).total_seconds() == 60


class _LifecycleRepository:
    def __init__(
        self, user: UserWithCredential | None, *, rate_counts: tuple[int, ...] = ()
    ) -> None:
        self.user = user
        self._rate_counts = list(rate_counts)
        self.rate_calls: list[dict[str, object]] = []
        self.cleared_scopes: list[str] = []

    async def consume_rate_limit(self, **values: object) -> int:
        self.rate_calls.append(values)
        return self._rate_counts.pop(0) if self._rate_counts else 1

    async def find_user_by_email(self, _email: str) -> UserWithCredential | None:
        return self.user

    async def clear_rate_limit(self, **values: object) -> None:
        self.cleared_scopes.append(str(values["scope"]))

    async def update_password_hash(self, *_args: object) -> None:
        return None

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
