from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterable, Iterable, Mapping
from dataclasses import dataclass
from itertools import chain
from uuid import uuid4

from app.db.types import DbConnection
from app.observability.sql import record_sql_query
from app.repositories.base import (
    CopyRow,
    ExecutableQuery,
    RepositoryParameters,
    RepositoryRow,
)


@dataclass(slots=True)
class _ConnectionState:
    connection: DbConnection | None
    owner: asyncio.Task[object]
    transaction_id: str


class PsycopgRepositoryConnection:
    """Expose Psycopg only while the owning UoW transaction and task are active."""

    def __init__(
        self,
        connection: DbConnection,
        owner: asyncio.Task[object],
        *,
        transaction_id: str | None = None,
        repository: str = "unbound",
        _state: _ConnectionState | None = None,
    ) -> None:
        self._state = _state or _ConnectionState(
            connection=connection,
            owner=owner,
            transaction_id=transaction_id or uuid4().hex,
        )
        self._repository = repository

    def for_repository(self, repository: str) -> PsycopgRepositoryConnection:
        """Return a labelled view sharing this connection's lifetime guard."""

        return type(self)(
            self._require_connection(),
            self._state.owner,
            repository=repository,
            _state=self._state,
        )

    def finish(self) -> None:
        """Permanently detach the raw connection before it returns to the pool."""

        self._state.connection = None

    def _require_connection(self) -> DbConnection:
        connection = self._state.connection
        if connection is None:
            raise RuntimeError("repository connection is no longer active")
        if asyncio.current_task() is not self._state.owner:
            raise RuntimeError("repository connection cannot cross asyncio task boundaries")
        return connection

    def _query_facts(self, query: ExecutableQuery) -> tuple[str, str]:
        try:
            rendered = query.as_string()
        except Exception:  # pragma: no cover - only unsupported third-party composables
            rendered = "<unavailable>"
        stripped = rendered.lstrip()
        operation = stripped.split(maxsplit=1)[0].lower() if stripped else "unknown"
        return rendered, operation

    def _record(
        self,
        query: ExecutableQuery,
        *,
        started: float,
        rows: int | None,
        error: BaseException | None = None,
    ) -> None:
        rendered, operation = self._query_facts(query)
        record_sql_query(
            query=rendered,
            operation=operation,
            duration_ms=(time.perf_counter() - started) * 1000,
            rows=rows,
            transaction_id=self._state.transaction_id,
            repository=self._repository,
            error=error,
        )

    async def execute(
        self,
        query: ExecutableQuery,
        parameters: RepositoryParameters | None = None,
        *,
        prepare: bool | None = None,
    ) -> int:
        connection = self._require_connection()
        started = time.perf_counter()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(query, parameters, prepare=prepare)
                rows = max(cursor.rowcount, 0)
        except BaseException as error:
            self._record(query, started=started, rows=None, error=error)
            raise
        self._record(query, started=started, rows=rows)
        return rows

    async def fetch_one(
        self,
        query: ExecutableQuery,
        parameters: RepositoryParameters | None = None,
        *,
        prepare: bool | None = None,
    ) -> RepositoryRow | None:
        connection = self._require_connection()
        started = time.perf_counter()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(query, parameters, prepare=prepare)
                row = await cursor.fetchone()
        except BaseException as error:
            self._record(query, started=started, rows=None, error=error)
            raise
        self._record(query, started=started, rows=int(row is not None))
        return row

    async def fetch_all(
        self,
        query: ExecutableQuery,
        parameters: RepositoryParameters | None = None,
        *,
        prepare: bool | None = None,
    ) -> tuple[RepositoryRow, ...]:
        connection = self._require_connection()
        started = time.perf_counter()
        try:
            async with connection.cursor() as cursor:
                await cursor.execute(query, parameters, prepare=prepare)
                rows = tuple(await cursor.fetchall())
        except BaseException as error:
            self._record(query, started=started, rows=None, error=error)
            raise
        self._record(query, started=started, rows=len(rows))
        return rows

    async def execute_many(
        self,
        query: ExecutableQuery,
        parameter_sets: Iterable[RepositoryParameters],
    ) -> int:
        connection = self._require_connection()
        iterator = iter(parameter_sets)
        try:
            first = next(iterator)
        except StopIteration:
            return 0
        if not isinstance(first, Mapping):
            raise TypeError("execute_many parameter sets must be mappings")

        def checked_parameter_sets() -> Iterable[RepositoryParameters]:
            for parameters in chain((first,), iterator):
                if not isinstance(parameters, Mapping):
                    raise TypeError("execute_many parameter sets must be mappings")
                yield parameters

        started = time.perf_counter()
        try:
            async with connection.cursor() as cursor:
                await cursor.executemany(query, checked_parameter_sets())
                rows = max(cursor.rowcount, 0)
        except BaseException as error:
            self._record(query, started=started, rows=None, error=error)
            raise
        self._record(query, started=started, rows=rows)
        return rows

    async def copy_rows(
        self,
        query: ExecutableQuery,
        rows: Iterable[CopyRow] | AsyncIterable[CopyRow],
    ) -> int:
        connection = self._require_connection()
        started = time.perf_counter()
        if isinstance(rows, AsyncIterable):
            async_iterator = aiter(rows)
            try:
                first = await anext(async_iterator)
            except StopAsyncIteration:
                return 0
            try:
                async with connection.cursor() as cursor, cursor.copy(query) as copy:
                    await copy.write_row(first)
                    count = 1
                    async for row in async_iterator:
                        await copy.write_row(row)
                        count += 1
            except BaseException as error:
                self._record(query, started=started, rows=None, error=error)
                raise
            self._record(query, started=started, rows=count)
            return count

        sync_iterator = iter(rows)
        try:
            first = next(sync_iterator)
        except StopIteration:
            return 0
        try:
            async with connection.cursor() as cursor, cursor.copy(query) as copy:
                await copy.write_row(first)
                count = 1
                for row in sync_iterator:
                    await copy.write_row(row)
                    count += 1
        except BaseException as error:
            self._record(query, started=started, rows=None, error=error)
            raise
        self._record(query, started=started, rows=count)
        return count
