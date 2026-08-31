from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from psycopg import sql
from psycopg.errors import UniqueViolation

from app.auth.errors import EmailAlreadyExistsError
from app.auth.models import (
    PasswordCredential,
    SessionPrincipal,
    UserIdentity,
    UserWithCredential,
    Workspace,
)
from app.repositories.base import BaseRepository, RepositoryRow


def _identity_from_row(row: RepositoryRow) -> UserIdentity:
    return UserIdentity.model_validate(
        {
            "user_id": row["user_id"],
            "email": row["email"],
            "status": row["status"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


class AuthRepository(BaseRepository, Protocol):
    """Persistence contract for users, sessions, workspaces, and auth limits."""

    async def add_user(
        self, identity: UserIdentity, credential: PasswordCredential
    ) -> UserIdentity: ...

    async def find_user_by_email(self, email: str) -> UserWithCredential | None: ...

    async def update_password_hash(
        self, user_id: UUID, password_hash: str, updated_at: datetime
    ) -> None: ...

    async def add_workspace(self, workspace: Workspace, owner_id: UUID) -> Workspace: ...

    async def list_workspaces(self, user_id: UUID) -> tuple[Workspace, ...]: ...

    async def is_workspace_member(self, user_id: UUID, workspace_id: UUID) -> bool: ...

    async def add_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        token_hash: str,
        csrf_hash: str,
        expires_at: datetime,
        created_at: datetime,
    ) -> None: ...

    async def resolve_session(
        self, token_hash: str, now: datetime
    ) -> SessionPrincipal | None: ...

    async def delete_session(self, session_id: UUID) -> None: ...

    async def consume_rate_limit(
        self,
        *,
        scope: str,
        subject_hash: str,
        window_started_at: datetime,
        expires_at: datetime,
    ) -> int: ...

    async def clear_rate_limit(
        self, *, scope: str, subject_hash: str, window_started_at: datetime
    ) -> None: ...

    async def purge_expired(self, now: datetime) -> tuple[int, int]: ...

    async def count_expired(self, now: datetime) -> tuple[int, int]: ...


class PostgresAuthRepository(BaseRepository):
    """Psycopg implementation created only by UnitOfWork."""

    async def add_user(
        self, identity: UserIdentity, credential: PasswordCredential
    ) -> UserIdentity:
        values = identity.model_dump(mode="python") | credential.model_dump(mode="python")
        try:
            row = await self.connection.fetch_one(
                sql.SQL(
                    "INSERT INTO users ("
                    "user_id, email, password_hash, status, version, created_at, updated_at, "
                    "password_updated_at"
                    ") VALUES ("
                    "%(user_id)s, %(email)s, %(password_hash)s, %(status)s, %(version)s, "
                    "%(created_at)s, %(updated_at)s, %(password_updated_at)s"
                    ") RETURNING user_id, email, status, version, created_at, updated_at"
                ),
                values,
                prepare=True,
            )
        except UniqueViolation as error:
            raise EmailAlreadyExistsError() from error
        if row is None:
            raise RuntimeError("INSERT did not return a user")
        return _identity_from_row(row)

    async def find_user_by_email(self, email: str) -> UserWithCredential | None:
        row = await self.connection.fetch_one(
            sql.SQL(
                "SELECT user_id, email, password_hash, status, version, created_at, "
                "updated_at, password_updated_at "
                "FROM users WHERE lower(email) = lower(%(email)s)"
            ),
            {"email": email},
            prepare=True,
        )
        if row is None:
            return None
        return UserWithCredential(
            identity=_identity_from_row(row),
            credential=PasswordCredential.model_validate(
                {
                    "user_id": row["user_id"],
                    "password_hash": row["password_hash"],
                    "password_updated_at": row["password_updated_at"],
                }
            ),
        )

    async def update_password_hash(
        self, user_id: UUID, password_hash: str, updated_at: datetime
    ) -> None:
        await self.connection.execute(
            sql.SQL(
                "UPDATE users SET password_hash = %(password_hash)s, "
                "password_updated_at = %(updated_at)s, updated_at = %(updated_at)s, "
                "version = version + 1 WHERE user_id = %(user_id)s"
            ),
            {
                "user_id": user_id,
                "password_hash": password_hash,
                "updated_at": updated_at,
            },
            prepare=True,
        )

    async def add_workspace(self, workspace: Workspace, owner_id: UUID) -> Workspace:
        values = workspace.model_dump(mode="python") | {"owner_id": owner_id}
        await self.connection.execute(
            sql.SQL(
                "INSERT INTO workspaces (workspace_id, name, created_at) "
                "VALUES (%(workspace_id)s, %(name)s, %(created_at)s)"
            ),
            values,
            prepare=True,
        )
        await self.connection.execute(
            sql.SQL(
                "INSERT INTO workspace_members (workspace_id, user_id, created_at) "
                "VALUES (%(workspace_id)s, %(owner_id)s, %(created_at)s)"
            ),
            values,
            prepare=True,
        )
        return workspace

    async def list_workspaces(self, user_id: UUID) -> tuple[Workspace, ...]:
        rows = await self.connection.fetch_all(
            sql.SQL(
                "SELECT w.workspace_id, w.name, w.created_at FROM workspaces w "
                "JOIN workspace_members m ON m.workspace_id = w.workspace_id "
                "WHERE m.user_id = %(user_id)s ORDER BY w.created_at, w.workspace_id"
            ),
            {"user_id": user_id},
            prepare=True,
        )
        return tuple(Workspace.model_validate(row) for row in rows)

    async def is_workspace_member(self, user_id: UUID, workspace_id: UUID) -> bool:
        row = await self.connection.fetch_one(
            sql.SQL(
                "SELECT EXISTS (SELECT 1 FROM workspace_members "
                "WHERE user_id = %(user_id)s AND workspace_id = %(workspace_id)s) AS allowed"
            ),
            {"user_id": user_id, "workspace_id": workspace_id},
            prepare=True,
        )
        return bool(row and row["allowed"])

    async def add_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        token_hash: str,
        csrf_hash: str,
        expires_at: datetime,
        created_at: datetime,
    ) -> None:
        await self.connection.execute(
            sql.SQL(
                "INSERT INTO sessions ("
                "session_id, user_id, token_hash, csrf_hash, expires_at, created_at"
                ") VALUES ("
                "%(session_id)s, %(user_id)s, %(token_hash)s, %(csrf_hash)s, "
                "%(expires_at)s, %(created_at)s)"
            ),
            {
                "session_id": session_id,
                "user_id": user_id,
                "token_hash": token_hash,
                "csrf_hash": csrf_hash,
                "expires_at": expires_at,
                "created_at": created_at,
            },
            prepare=True,
        )

    async def resolve_session(self, token_hash: str, now: datetime) -> SessionPrincipal | None:
        row = await self.connection.fetch_one(
            sql.SQL(
                "SELECT s.session_id, s.user_id, u.email, s.csrf_hash, s.expires_at "
                "FROM sessions s JOIN users u ON u.user_id = s.user_id "
                "WHERE s.token_hash = %(token_hash)s AND s.expires_at > %(now)s "
                "AND u.status = 'ACTIVE'"
            ),
            {"token_hash": token_hash, "now": now},
            prepare=True,
        )
        return SessionPrincipal.model_validate(row) if row else None

    async def delete_session(self, session_id: UUID) -> None:
        await self.connection.execute(
            sql.SQL("DELETE FROM sessions WHERE session_id = %(session_id)s"),
            {"session_id": session_id},
            prepare=True,
        )

    async def consume_rate_limit(
        self,
        *,
        scope: str,
        subject_hash: str,
        window_started_at: datetime,
        expires_at: datetime,
    ) -> int:
        row = await self.connection.fetch_one(
            sql.SQL(
                "INSERT INTO auth_rate_limits ("
                "scope, subject_hash, window_started_at, attempt_count, expires_at"
                ") VALUES ("
                "%(scope)s, %(subject_hash)s, %(window_started_at)s, 1, %(expires_at)s"
                ") "
                "ON CONFLICT (scope, subject_hash, window_started_at) DO UPDATE "
                "SET attempt_count = auth_rate_limits.attempt_count + 1, "
                "expires_at = EXCLUDED.expires_at RETURNING attempt_count"
            ),
            {
                "scope": scope,
                "subject_hash": subject_hash,
                "window_started_at": window_started_at,
                "expires_at": expires_at,
            },
            prepare=True,
        )
        if row is None:
            raise RuntimeError("rate-limit UPSERT did not return a count")
        return int(row["attempt_count"])

    async def clear_rate_limit(
        self, *, scope: str, subject_hash: str, window_started_at: datetime
    ) -> None:
        await self.connection.execute(
            sql.SQL(
                "DELETE FROM auth_rate_limits WHERE scope = %(scope)s "
                "AND subject_hash = %(subject_hash)s "
                "AND window_started_at = %(window_started_at)s"
            ),
            {
                "scope": scope,
                "subject_hash": subject_hash,
                "window_started_at": window_started_at,
            },
            prepare=True,
        )

    async def purge_expired(self, now: datetime) -> tuple[int, int]:
        sessions = await self.connection.execute(
            sql.SQL("DELETE FROM sessions WHERE expires_at <= %(now)s"),
            {"now": now},
            prepare=True,
        )
        rate_limits = await self.connection.execute(
            sql.SQL("DELETE FROM auth_rate_limits WHERE expires_at <= %(now)s"),
            {"now": now},
            prepare=True,
        )
        return sessions, rate_limits

    async def count_expired(self, now: datetime) -> tuple[int, int]:
        session_row = await self.connection.fetch_one(
            sql.SQL("SELECT count(*) AS count FROM sessions WHERE expires_at <= %(now)s"),
            {"now": now},
            prepare=True,
        )
        rate_limit_row = await self.connection.fetch_one(
            sql.SQL(
                "SELECT count(*) AS count FROM auth_rate_limits WHERE expires_at <= %(now)s"
            ),
            {"now": now},
            prepare=True,
        )
        if session_row is None or rate_limit_row is None:
            raise RuntimeError("expired-auth count query returned no row")
        return int(session_row["count"]), int(rate_limit_row["count"])
