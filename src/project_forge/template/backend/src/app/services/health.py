from __future__ import annotations

from app.uow.factory import UnitOfWorkFactory


class HealthService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def is_ready(self) -> bool:
        """Return false for infrastructure failure without exposing database details."""
        try:
            async with self._unit_of_work_factory() as unit_of_work:
                return await unit_of_work.health.is_ready()
        except Exception:
            # Readiness is deliberately a failure boundary. Application requests still surface
            # unexpected database failures through the normal error handlers and observability.
            return False
