from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.db.types import DbPool
from app.uow.unit import UnitOfWork


class UnitOfWorkFactory:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[UnitOfWork]:
        async with self._pool.connection() as connection, UnitOfWork(connection) as unit_of_work:
            yield unit_of_work
