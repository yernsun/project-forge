from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from psycopg import sql

from app.repositories.base import BaseRepository, RepositoryConnection


class HealthRepository(BaseRepository, Protocol):
    """Persistence contract for database readiness."""

    async def is_ready(self) -> bool: ...


class PostgresHealthRepository(BaseRepository):
    """Validate connectivity and the complete migration checksum set."""

    def __init__(
        self,
        connection: RepositoryConnection,
        *,
        expected_migrations: Mapping[str, str],
    ) -> None:
        super().__init__(connection)
        self._expected_migrations = dict(expected_migrations)

    async def is_ready(self) -> bool:
        tracking = await self.connection.fetch_one(
            sql.SQL("SELECT to_regclass(%(table_name)s) AS table_name"),
            {"table_name": "schema_migrations"},
            prepare=True,
        )
        if not tracking or not tracking["table_name"]:
            return False

        rows = await self.connection.fetch_all(
            sql.SQL(
                "SELECT migration_id, checksum FROM schema_migrations "
                "ORDER BY migration_id"
            ),
            prepare=True,
        )
        applied = {str(row["migration_id"]): str(row["checksum"]) for row in rows}
        return applied == self._expected_migrations
