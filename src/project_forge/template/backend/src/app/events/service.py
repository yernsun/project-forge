from __future__ import annotations

from uuid import UUID

from app.domain.base import utc_now
from app.events.models import OutboxRecord, OutboxStatus
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

    async def release(
        self,
        event_id: UUID,
        attempts: int,
        *,
        error_code: str,
        max_attempts: int,
    ) -> bool:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.outbox.release_with_backoff(
                event_id,
                attempts,
                error_code=error_code,
                max_attempts=max_attempts,
            )

    async def status(self) -> OutboxStatus:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.outbox.status(utc_now())

    async def retry_failed(self, limit: int) -> tuple[UUID, ...]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.outbox.retry_failed(now=utc_now(), limit=limit)
