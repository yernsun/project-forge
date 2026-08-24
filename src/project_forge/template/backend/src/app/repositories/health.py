from __future__ import annotations

from app.db.migration_engine import MigrationRunner
from app.db.registry import MIGRATIONS
from app.db.types import DbConnection


class HealthRepository:
    def __init__(self, connection: DbConnection) -> None:
        self._connection = connection

    async def is_ready(self) -> bool:
        await MigrationRunner(self._connection, MIGRATIONS).validate_current()
        return True
