from __future__ import annotations

from collections.abc import AsyncIterable, Iterable, Mapping, Sequence
from typing import Any, Protocol, TypeAlias

from psycopg import sql

RepositoryRow: TypeAlias = dict[str, Any]
RepositoryParameters: TypeAlias = Mapping[str, object]
CopyRow: TypeAlias = Sequence[object]
ExecutableQuery: TypeAlias = sql.SQL | sql.Composed


class RepositoryConnection(Protocol):
    """Task-bound SQL operations available to repositories inside one UoW."""

    async def execute(
        self,
        query: ExecutableQuery,
        parameters: RepositoryParameters | None = None,
        *,
        prepare: bool | None = None,
    ) -> int:
        """Execute one statement and return the affected row count."""

    async def fetch_one(
        self,
        query: ExecutableQuery,
        parameters: RepositoryParameters | None = None,
        *,
        prepare: bool | None = None,
    ) -> RepositoryRow | None:
        """Execute one statement and return at most one mapping row."""

    async def fetch_all(
        self,
        query: ExecutableQuery,
        parameters: RepositoryParameters | None = None,
        *,
        prepare: bool | None = None,
    ) -> tuple[RepositoryRow, ...]:
        """Execute one statement and return all mapping rows."""

    async def execute_many(
        self,
        query: ExecutableQuery,
        parameter_sets: Iterable[RepositoryParameters],
    ) -> int:
        """Execute one named-parameter statement for a bounded mapping iterable."""

    async def copy_rows(
        self,
        query: ExecutableQuery,
        rows: Iterable[CopyRow] | AsyncIterable[CopyRow],
    ) -> int:
        """Stream ordered row data through a fixed COPY FROM STDIN statement."""


class BaseRepository(Protocol):
    """Shared marker and constructor for generated repository boundaries."""

    connection: RepositoryConnection

    def __init__(self, connection: RepositoryConnection) -> None:
        self.connection = connection
