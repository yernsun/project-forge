from __future__ import annotations

from app.db.types import DbPool
from app.uow.unit import UnitOfWork


class UnitOfWorkFactory:
    def __init__(self, pool: DbPool) -> None:
        self._pool = pool

    def __call__(self) -> UnitOfWork:
        return UnitOfWork(self._pool)
