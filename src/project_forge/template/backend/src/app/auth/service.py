from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.auth.errors import (
    AuthRateLimitedError,
    CsrfValidationError,
    InvalidCredentialsError,
    InvalidSessionError,
    SignupDisabledError,
)
from app.auth.models import (
    IssuedSession,
    PasswordCredential,
    SessionPrincipal,
    UserIdentity,
    UserStatus,
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
from app.domain.base import utc_now
from app.settings import Settings
from app.uow.factory import UnitOfWorkFactory
from app.uow.unit import UnitOfWork


def canonical_email(email: str) -> str:
    return email.strip().casefold()


def fixed_window(now: datetime, seconds: int) -> tuple[datetime, datetime]:
    epoch = int(now.timestamp())
    start_epoch = epoch - (epoch % seconds)
    start = datetime.fromtimestamp(start_epoch, UTC)
    return start, start + timedelta(seconds=seconds)


@dataclass(frozen=True, slots=True)
class RateLimitSpec:
    scope: str
    subject: str
    maximum: int
    window_seconds: int


@dataclass(frozen=True, slots=True)
class ConsumedRateLimit:
    scope: str
    subject_hash: str
    window_started_at: datetime
    reset_at: datetime
    count: int
    maximum: int


class AuthService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory, settings: Settings) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._settings = settings
        self._session_ttl = timedelta(seconds=settings.session_ttl_seconds)

    async def _issue(self, unit_of_work: UnitOfWork, user: UserIdentity) -> IssuedSession:
        session_token = generate_token()
        csrf_token = generate_token()
        csrf_hash = hash_token(csrf_token)
        now = utc_now()
        session_id = uuid4()
        expires_at = now + self._session_ttl
        await unit_of_work.auth.add_session(
            session_id=session_id,
            user_id=user.user_id,
            token_hash=hash_token(session_token),
            csrf_hash=csrf_hash,
            expires_at=expires_at,
            created_at=now,
        )
        return IssuedSession(
            principal=SessionPrincipal(
                session_id=session_id,
                user_id=user.user_id,
                email=user.email,
                csrf_hash=csrf_hash,
                expires_at=expires_at,
            ),
            session_token=session_token,
            csrf_token=csrf_token,
        )

    async def _consume_rate_limit(self, spec: RateLimitSpec) -> ConsumedRateLimit:
        """Commit one counter before deciding whether to reject its caller."""

        now = utc_now()
        secret = self._settings.auth_rate_limit_secret.get_secret_value()
        # This UoW exits successfully and commits even when the caller is rejected below.
        async with self._unit_of_work_factory() as unit_of_work:
            window_start, window_end = fixed_window(now, spec.window_seconds)
            subject_hash = hmac_subject(secret, spec.scope, spec.subject)
            count = await unit_of_work.auth.consume_rate_limit(
                scope=spec.scope,
                subject_hash=subject_hash,
                window_started_at=window_start,
                expires_at=window_end,
            )
        consumed = ConsumedRateLimit(
            scope=spec.scope,
            subject_hash=subject_hash,
            window_started_at=window_start,
            reset_at=window_end,
            count=count,
            maximum=spec.maximum,
        )
        if consumed.count > consumed.maximum:
            retry_after = max(1, math.ceil((consumed.reset_at - now).total_seconds()))
            raise AuthRateLimitedError(retry_after_seconds=retry_after)
        return consumed

    async def signup(
        self, email: str, password: str, workspace_name: str, client_key: str
    ) -> IssuedSession:
        if not self._settings.is_signup_enabled:
            raise SignupDisabledError()
        normalized_email = canonical_email(email)
        await self._consume_rate_limit(
            RateLimitSpec(
                scope="signup:ip",
                subject=client_key,
                maximum=self._settings.auth_signup_ip_limit,
                window_seconds=self._settings.auth_signup_ip_window_seconds,
            )
        )
        password_hash = await asyncio.to_thread(hash_password, password)
        now = utc_now()
        identity = UserIdentity(
            user_id=uuid4(),
            email=normalized_email,
            status=UserStatus.ACTIVE,
            version=1,
            created_at=now,
            updated_at=now,
        )
        credential = PasswordCredential(
            user_id=identity.user_id,
            password_hash=password_hash,
            password_updated_at=now,
        )
        workspace = Workspace(workspace_id=uuid4(), name=workspace_name, created_at=now)
        async with self._unit_of_work_factory() as unit_of_work:
            created = await unit_of_work.auth.add_user(identity, credential)
            await unit_of_work.auth.add_workspace(workspace, created.user_id)
            return await self._issue(unit_of_work, created)

    async def login(self, email: str, password: str, client_key: str) -> IssuedSession:
        normalized_email = canonical_email(email)
        await self._consume_rate_limit(
            RateLimitSpec(
                scope="login:ip",
                subject=client_key,
                maximum=self._settings.auth_login_ip_limit,
                window_seconds=self._settings.auth_login_ip_window_seconds,
            )
        )
        email_ip_bucket = await self._consume_rate_limit(
            RateLimitSpec(
                scope="login:email_ip",
                subject=f"{normalized_email}\0{client_key}",
                maximum=self._settings.auth_login_email_ip_limit,
                window_seconds=self._settings.auth_login_email_ip_window_seconds,
            )
        )
        async with self._unit_of_work_factory() as unit_of_work:
            user = await unit_of_work.auth.find_user_by_email(normalized_email)
            password_hash = user.credential.password_hash if user else None
            verification = await asyncio.to_thread(verify_password, password_hash, password)
            if (
                user is None
                or user.identity.status is not UserStatus.ACTIVE
                or not verification.valid
            ):
                raise InvalidCredentialsError()
            if verification.needs_rehash:
                replacement = await asyncio.to_thread(hash_password, password)
                await unit_of_work.auth.update_password_hash(
                    user.identity.user_id, replacement, utc_now()
                )
            await unit_of_work.auth.clear_rate_limit(
                scope=email_ip_bucket.scope,
                subject_hash=email_ip_bucket.subject_hash,
                window_started_at=email_ip_bucket.window_started_at,
            )
            return await self._issue(unit_of_work, user.identity)

    async def resolve(self, session_token: str) -> SessionPrincipal:
        async with self._unit_of_work_factory() as unit_of_work:
            principal = await unit_of_work.auth.resolve_session(
                hash_token(session_token), utc_now()
            )
            if principal is None:
                raise InvalidSessionError()
            return principal

    async def logout(self, principal: SessionPrincipal) -> None:
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.auth.delete_session(principal.session_id)

    @staticmethod
    def require_csrf(principal: SessionPrincipal, csrf_token: str) -> None:
        if not token_matches(csrf_token, principal.csrf_hash):
            raise CsrfValidationError()

    async def create_workspace(self, user_id: UUID, name: str) -> Workspace:
        workspace = Workspace(workspace_id=uuid4(), name=name, created_at=utc_now())
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.auth.add_workspace(workspace, user_id)

    async def list_workspaces(self, user_id: UUID) -> tuple[Workspace, ...]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.auth.list_workspaces(user_id)

    async def purge_expired(self, *, dry_run: bool = False) -> tuple[int, int]:
        now = utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            if dry_run:
                return await unit_of_work.auth.count_expired(now)
            return await unit_of_work.auth.purge_expired(now)
