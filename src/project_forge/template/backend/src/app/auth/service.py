from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

from app.auth.models import IssuedSession, SessionPrincipal, User, Workspace
from app.auth.security import (
    generate_token,
    hash_password,
    hash_token,
    token_matches,
    verify_password,
)
from app.domain.base import utc_now
from app.uow.factory import UnitOfWorkFactory
from app.uow.unit import UnitOfWork


class AuthenticationError(PermissionError):
    pass


class AuthService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory, session_ttl_seconds: int) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._session_ttl = timedelta(seconds=session_ttl_seconds)

    async def _issue(self, unit_of_work: UnitOfWork, user: User) -> IssuedSession:
        session_token = generate_token()
        csrf_token = generate_token()
        now = utc_now()
        session_id = uuid4()
        expires_at = now + self._session_ttl
        await unit_of_work.auth.add_session(
            session_id=session_id,
            user_id=user.user_id,
            token_hash=hash_token(session_token),
            csrf_hash=hash_token(csrf_token),
            expires_at=expires_at,
            created_at=now,
        )
        return IssuedSession(
            principal=SessionPrincipal(
                session_id=session_id,
                user_id=user.user_id,
                email=user.email,
                csrf_hash=hash_token(csrf_token),
                expires_at=expires_at,
            ),
            session_token=session_token,
            csrf_token=csrf_token,
        )

    async def signup(self, email: str, password: str, workspace_name: str) -> IssuedSession:
        normalized_email = email.strip().lower()
        password_hash = await asyncio.to_thread(hash_password, password)
        now = utc_now()
        user = User(
            user_id=uuid4(), email=normalized_email, password_hash=password_hash, created_at=now
        )
        workspace = Workspace(workspace_id=uuid4(), name=workspace_name, created_at=now)
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.auth.add_user(user)
            await unit_of_work.auth.add_workspace(workspace, user.user_id)
            return await self._issue(unit_of_work, user)

    async def login(self, email: str, password: str) -> IssuedSession:
        async with self._unit_of_work_factory() as unit_of_work:
            user = await unit_of_work.auth.find_user_by_email(email.strip().lower())
            valid = bool(
                user
                and await asyncio.to_thread(verify_password, user.password_hash, password)
            )
            if not valid or user is None:
                raise AuthenticationError("invalid credentials")
            return await self._issue(unit_of_work, user)

    async def resolve(self, session_token: str) -> SessionPrincipal:
        async with self._unit_of_work_factory() as unit_of_work:
            principal = await unit_of_work.auth.resolve_session(
                hash_token(session_token), utc_now()
            )
            if principal is None:
                raise AuthenticationError("invalid or expired session")
            return principal

    async def logout(self, principal: SessionPrincipal, csrf_token: str) -> None:
        self.require_csrf(principal, csrf_token)
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.auth.delete_session(principal.session_id)

    @staticmethod
    def require_csrf(principal: SessionPrincipal, csrf_token: str) -> None:
        if not token_matches(csrf_token, principal.csrf_hash):
            raise AuthenticationError("invalid CSRF token")

    async def create_workspace(self, user_id: UUID, name: str) -> Workspace:
        workspace = Workspace(workspace_id=uuid4(), name=name, created_at=utc_now())
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.auth.add_workspace(workspace, user_id)

    async def list_workspaces(self, user_id: UUID) -> tuple[Workspace, ...]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.auth.list_workspaces(user_id)
