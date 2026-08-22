from __future__ import annotations

from datetime import datetime
from uuid import UUID

from psycopg import sql

from app.auth.models import SessionPrincipal, User, Workspace
from app.db.types import DbConnection


class AuthRepository:
    def __init__(self, connection: DbConnection) -> None:
        self._connection = connection

    async def add_user(self, user: User) -> User:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    "INSERT INTO users (user_id, email, password_hash, created_at) "
                    "VALUES (%(user_id)s, %(email)s, %(password_hash)s, %(created_at)s) "
                    "RETURNING user_id, email, password_hash, created_at"
                ),
                user.model_dump(mode="python"),
            )
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("INSERT did not return a user")
        return User.model_validate(row)

    async def find_user_by_email(self, email: str) -> User | None:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    "SELECT user_id, email, password_hash, created_at "
                    "FROM users WHERE email = %(email)s"
                ),
                {"email": email},
                prepare=True,
            )
            row = await cursor.fetchone()
        return User.model_validate(row) if row else None

    async def add_workspace(self, workspace: Workspace, owner_id: UUID) -> Workspace:
        values = workspace.model_dump(mode="python") | {"owner_id": owner_id}
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    "INSERT INTO workspaces (workspace_id, name, created_at) "
                    "VALUES (%(workspace_id)s, %(name)s, %(created_at)s)"
                ),
                values,
            )
            await cursor.execute(
                sql.SQL(
                    "INSERT INTO workspace_members (workspace_id, user_id, created_at) "
                    "VALUES (%(workspace_id)s, %(owner_id)s, %(created_at)s)"
                ),
                values,
            )
        return workspace

    async def list_workspaces(self, user_id: UUID) -> tuple[Workspace, ...]:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    "SELECT w.workspace_id, w.name, w.created_at FROM workspaces w "
                    "JOIN workspace_members m ON m.workspace_id = w.workspace_id "
                    "WHERE m.user_id = %(user_id)s ORDER BY w.created_at, w.workspace_id"
                ),
                {"user_id": user_id},
                prepare=True,
            )
            rows = await cursor.fetchall()
        return tuple(Workspace.model_validate(row) for row in rows)

    async def is_workspace_member(self, user_id: UUID, workspace_id: UUID) -> bool:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    "SELECT EXISTS (SELECT 1 FROM workspace_members "
                    "WHERE user_id = %(user_id)s AND workspace_id = %(workspace_id)s) AS allowed"
                ),
                {"user_id": user_id, "workspace_id": workspace_id},
                prepare=True,
            )
            row = await cursor.fetchone()
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
        async with self._connection.cursor() as cursor:
            await cursor.execute(
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
            )

    async def resolve_session(self, token_hash: str, now: datetime) -> SessionPrincipal | None:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    "SELECT s.session_id, s.user_id, u.email, s.csrf_hash, s.expires_at "
                    "FROM sessions s JOIN users u ON u.user_id = s.user_id "
                    "WHERE s.token_hash = %(token_hash)s AND s.expires_at > %(now)s"
                ),
                {"token_hash": token_hash, "now": now},
                prepare=True,
            )
            row = await cursor.fetchone()
        return SessionPrincipal.model_validate(row) if row else None

    async def delete_session(self, session_id: UUID) -> None:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("DELETE FROM sessions WHERE session_id = %(session_id)s"),
                {"session_id": session_id},
                prepare=True,
            )
