"""Immutable forward-only migration DAG and runner."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from psycopg import sql

from app.db.types import DbConnection


class MigrationError(RuntimeError):
    pass


class MigrationState(StrEnum):
    APPLIED = "applied"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class Migration:
    migration_id: str
    dependencies: tuple[str, ...]
    up_sql: str

    @property
    def checksum(self) -> str:
        payload = f"{self.migration_id}\n{','.join(self.dependencies)}\n{self.up_sql}".encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class MigrationStatus:
    migration_id: str
    checksum: str
    state: MigrationState
    applied_at: datetime | None


TRACKING_TABLE = sql.SQL(
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        migration_id text PRIMARY KEY,
        checksum text NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now()
    )
    """
)


def ordered_migrations(migrations: tuple[Migration, ...]) -> tuple[Migration, ...]:
    by_id = {migration.migration_id: migration for migration in migrations}
    if len(by_id) != len(migrations):
        raise MigrationError("duplicate migration ID")
    for migration in migrations:
        missing = set(migration.dependencies) - by_id.keys()
        if missing:
            raise MigrationError(
                f"{migration.migration_id} has missing dependencies: {sorted(missing)}"
            )
    ordered: list[Migration] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(migration_id: str) -> None:
        if migration_id in visited:
            return
        if migration_id in visiting:
            raise MigrationError(f"migration cycle includes {migration_id}")
        visiting.add(migration_id)
        migration = by_id[migration_id]
        for dependency in sorted(migration.dependencies):
            visit(dependency)
        visiting.remove(migration_id)
        visited.add(migration_id)
        ordered.append(migration)

    for migration_id in sorted(by_id):
        visit(migration_id)
    return tuple(ordered)


class MigrationRunner:
    def __init__(self, connection: DbConnection, migrations: tuple[Migration, ...]) -> None:
        self._connection = connection
        self._migrations = ordered_migrations(migrations)

    async def _tracking_exists(self) -> bool:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("SELECT to_regclass(%(table_name)s) AS table_name"),
                {"table_name": "schema_migrations"},
            )
            row = await cursor.fetchone()
        return bool(row and row["table_name"])

    async def _applied(self) -> dict[str, tuple[str, datetime]]:
        if not await self._tracking_exists():
            return {}
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    "SELECT migration_id, checksum, applied_at "
                    "FROM schema_migrations ORDER BY migration_id"
                )
            )
            rows = await cursor.fetchall()
        return {row["migration_id"]: (row["checksum"], row["applied_at"]) for row in rows}

    async def validate_history(self) -> None:
        """Reject unknown or modified applied migrations without requiring a current schema."""

        if not await self._tracking_exists():
            raise MigrationError("database is not initialized; run `app migrate up`")
        applied = await self._applied()
        known = {migration.migration_id: migration for migration in self._migrations}
        unknown = set(applied) - known.keys()
        if unknown:
            raise MigrationError(f"database contains unknown migrations: {sorted(unknown)}")
        for migration_id, (checksum, _) in applied.items():
            if known[migration_id].checksum != checksum:
                raise MigrationError(f"checksum mismatch for applied migration {migration_id}")

    async def validate_current(self) -> None:
        """Require valid history with every migration in this application applied."""

        await self.validate_history()
        applied = await self._applied()
        pending = tuple(
            migration.migration_id
            for migration in self._migrations
            if migration.migration_id not in applied
        )
        if pending:
            raise MigrationError(
                f"database has pending migrations: {list(pending)}; run `app migrate up`"
            )

    async def validate(self) -> None:
        """Backward-compatible operator command: validate that the schema is current."""

        await self.validate_current()

    async def status(self) -> tuple[MigrationStatus, ...]:
        applied = await self._applied()
        return tuple(
            MigrationStatus(
                migration_id=migration.migration_id,
                checksum=migration.checksum,
                state=(
                    MigrationState.APPLIED
                    if migration.migration_id in applied
                    else MigrationState.PENDING
                ),
                applied_at=(applied.get(migration.migration_id) or ("", None))[1],
            )
            for migration in self._migrations
        )

    async def up(self) -> tuple[str, ...]:
        applied_ids: list[str] = []
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.execute(TRACKING_TABLE)
                await cursor.execute(
                    sql.SQL("SELECT pg_advisory_xact_lock(%(lock_key)s)"),
                    {"lock_key": 718_340_211},
                )
            await self.validate_history()
            applied = await self._applied()
            for migration in self._migrations:
                if migration.migration_id in applied:
                    continue
                async with self._connection.cursor() as cursor:
                    await cursor.execute(sql.SQL(migration.up_sql))
                    await cursor.execute(
                        sql.SQL(
                            "INSERT INTO schema_migrations (migration_id, checksum) "
                            "VALUES (%(migration_id)s, %(checksum)s)"
                        ),
                        {"migration_id": migration.migration_id, "checksum": migration.checksum},
                    )
                applied_ids.append(migration.migration_id)
        return tuple(applied_ids)
