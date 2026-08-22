from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable
from typing import cast

import typer
from redis.asyncio import Redis

from app.db.pool import create_pool
from app.events.models import EventEnvelope
from app.events.service import OutboxService
from app.events.transport import RedisEventTransport
from app.settings import get_settings
from app.uow.factory import UnitOfWorkFactory
from app.uow.unit import UnitOfWork

app = typer.Typer(no_args_is_help=True)


async def relay_forever(interval_seconds: float = 0.5) -> None:
    settings = get_settings()
    pool = create_pool(settings.database_url)
    await pool.open()
    redis = Redis.from_url(settings.redis_url)
    service = OutboxService(UnitOfWorkFactory(pool))
    transport = RedisEventTransport(redis)
    worker_id = socket.gethostname()
    try:
        while True:
            records = await service.claim(worker_id)
            for record in records:
                try:
                    await transport.publish(record.envelope)
                except Exception:
                    await service.release(record.envelope.event_id, record.attempts)
                else:
                    await service.mark_published(record.envelope.event_id)
            await asyncio.sleep(interval_seconds)
    finally:
        await redis.aclose()
        await pool.close()


class StreamConsumer:
    """ACK-after-commit consumer with bounded retry and DLQ behavior."""

    def __init__(
        self,
        redis: Redis,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        stream: str,
        group: str,
        consumer: str,
        handler: Callable[[UnitOfWork, EventEnvelope], Awaitable[None]],
        max_attempts: int = 5,
    ) -> None:
        self._redis = redis
        self._unit_of_work_factory = unit_of_work_factory
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._handler = handler
        self._max_attempts = max_attempts

    async def ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except Exception as error:
            if "BUSYGROUP" not in str(error):
                raise

    async def process(self, message_id: str, fields: dict[bytes, bytes]) -> None:
        envelope = EventEnvelope.model_validate_json(fields[b"payload"])
        try:
            async with self._unit_of_work_factory() as unit_of_work:
                first_delivery = await unit_of_work.processed_messages.mark_once(
                    self._group, message_id
                )
                if first_delivery:
                    await self._handler(unit_of_work, envelope)
        except Exception:
            attempts = await cast(
                Awaitable[int],
                self._redis.hincrby(f"retry:{self._stream}:{self._group}", message_id, 1),
            )
            if attempts >= self._max_attempts:
                await self._redis.xadd(
                    f"{self._stream}.dlq",
                    {"messageId": message_id, "payload": fields[b"payload"], "attempts": attempts},
                )
                await self._redis.xack(self._stream, self._group, message_id)
            raise
        else:
            await self._redis.xack(self._stream, self._group, message_id)
            await cast(
                Awaitable[int],
                self._redis.hdel(f"retry:{self._stream}:{self._group}", message_id),
            )


@app.command("relay")
def relay() -> None:
    asyncio.run(relay_forever())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
