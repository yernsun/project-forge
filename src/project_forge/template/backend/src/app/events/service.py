from __future__ import annotations

from uuid import UUID

from app.events.models import OutboxRecord
from app.uow.factory import UnitOfWorkFactory


class OutboxService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def claim(self, worker_id: str, limit: int = 100) -> tuple[OutboxRecord, ...]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.outbox.claim(worker_id, limit)

    async def mark_published(self, event_id: UUID) -> None:
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.outbox.mark_published(event_id)

    async def release(self, event_id: UUID, attempts: int) -> None:
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.outbox.release_with_backoff(event_id, attempts)
