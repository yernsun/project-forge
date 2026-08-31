from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Iterable, Mapping
from itertools import chain

from app.db.types import DbConnection
from app.repositories.base import (
    CopyRow,
    ExecutableQuery,
    RepositoryParameters,
    RepositoryRow,
)


class PsycopgRepositoryConnection:
    """Expose Psycopg only while the owning UoW transaction and task are active."""

    def __init__(self, connection: DbConnection, owner: asyncio.Task[object]) -> None:
        self._connection: DbConnection | None = connection
        self._owner = owner

    def finish(self) -> None:
        """Permanently detach the raw connection before it returns to the pool."""

        self._connection = None

    def _require_connection(self) -> DbConnection:
        connection = self._connection
        if connection is None:
            raise RuntimeError("repository connection is no longer active")
        if asyncio.current_task() is not self._owner:
            raise RuntimeError("repository connection cannot cross asyncio task boundaries")
        return connection

    async def execute(
        self,
        query: ExecutableQuery,
        parameters: RepositoryParameters | None = None,
        *,
        prepare: bool | None = None,
    ) -> int:
        connection = self._require_connection()
        async with connection.cursor() as cursor:
            await cursor.execute(query, parameters, prepare=prepare)
            return max(cursor.rowcount, 0)

    async def fetch_one(
        self,
        query: ExecutableQuery,
        parameters: RepositoryParameters | None = None,
        *,
        prepare: bool | None = None,
    ) -> RepositoryRow | None:
        connection = self._require_connection()
        async with connection.cursor() as cursor:
            await cursor.execute(query, parameters, prepare=prepare)
            return await cursor.fetchone()

    async def fetch_all(
        self,
        query: ExecutableQuery,
        parameters: RepositoryParameters | None = None,
        *,
        prepare: bool | None = None,
    ) -> tuple[RepositoryRow, ...]:
        connection = self._require_connection()
        async with connection.cursor() as cursor:
            await cursor.execute(query, parameters, prepare=prepare)
            return tuple(await cursor.fetchall())

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

        async with connection.cursor() as cursor:
            await cursor.executemany(query, checked_parameter_sets())
            return max(cursor.rowcount, 0)

    async def copy_rows(
        self,
        query: ExecutableQuery,
        rows: Iterable[CopyRow] | AsyncIterable[CopyRow],
    ) -> int:
        connection = self._require_connection()
        if isinstance(rows, AsyncIterable):
            async_iterator = aiter(rows)
            try:
                first = await anext(async_iterator)
            except StopAsyncIteration:
                return 0
            async with connection.cursor() as cursor, cursor.copy(query) as copy:
                await copy.write_row(first)
                count = 1
                async for row in async_iterator:
                    await copy.write_row(row)
                    count += 1
                return count

        sync_iterator = iter(rows)
        try:
            first = next(sync_iterator)
        except StopIteration:
            return 0
        async with connection.cursor() as cursor, cursor.copy(query) as copy:
            await copy.write_row(first)
            count = 1
            for row in sync_iterator:
                await copy.write_row(row)
                count += 1
            return count
