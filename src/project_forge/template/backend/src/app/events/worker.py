from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import cast

import typer
from redis.asyncio import Redis

from app.db.pool import create_pool
from app.events.models import EventEnvelope
from app.events.service import OutboxService
from app.events.transport import RedisEventTransport
from app.observability import (
    LogEvent,
    LogOutcome,
    configure_logging,
    log_event,
    log_exception,
    operation_context,
)
from app.settings import get_settings
from app.uow.factory import UnitOfWorkFactory
from app.uow.unit import UnitOfWork

app = typer.Typer(no_args_is_help=True)
logger = logging.getLogger(__name__)


async def relay_forever(stop_event: asyncio.Event | None = None) -> None:
    settings = get_settings()
    stop = stop_event or asyncio.Event()
    pool = create_pool(settings.database_url)
    await pool.open()
    redis = Redis.from_url(settings.redis_url)
    service = OutboxService(UnitOfWorkFactory(pool))
    transport = RedisEventTransport(redis)
    worker_id = f"{settings.log_instance_id}:{os.getpid()}"
    try:
        while not stop.is_set():
            records = await service.claim(worker_id)
            for record in records:
                event_id = str(record.envelope.event_id)
                with operation_context(operation_id=event_id, event_id=event_id):
                    try:
                        await transport.publish(record.envelope)
                    except Exception as error:
                        parked = await service.release(
                            record.envelope.event_id,
                            record.attempts,
                            error_code=type(error).__name__,
                            max_attempts=settings.event_relay_max_attempts,
                        )
                        log_exception(
                            logger,
                            "outbox publish failed",
                            event=(
                                LogEvent.STREAM_OUTBOX_PARKED
                                if parked
                                else LogEvent.STREAM_OUTBOX_RETRY_SCHEDULED
                            ),
                            outcome=(LogOutcome.FAILED if parked else LogOutcome.RETRY),
                            error=error,
                            attempts=record.attempts,
                        )
                    else:
                        await service.mark_published(record.envelope.event_id)
                        log_event(
                            logger,
                            logging.INFO,
                            "outbox event published",
                            event=LogEvent.STREAM_OUTBOX_PUBLISHED,
                            outcome=LogOutcome.SUCCESS,
                            attempts=record.attempts,
                        )
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    stop.wait(), timeout=settings.event_relay_poll_seconds
                )
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
        payload = fields.get(b"payload")
        envelope: EventEnvelope | None = None
        event_id: str | None = None
        first_delivery = False
        with operation_context(message_id=message_id):
            try:
                if payload is None:
                    raise ValueError("stream message does not contain a payload")
                envelope = EventEnvelope.model_validate_json(payload)
                event_id = str(envelope.event_id)
                with operation_context(operation_id=event_id, event_id=event_id):
                    async with self._unit_of_work_factory() as unit_of_work:
                        first_delivery = await unit_of_work.processed_messages.mark_once(
                            self._group, envelope.event_id
                        )
                        if first_delivery:
                            await self._handler(unit_of_work, envelope)
            except Exception as error:
                with operation_context(operation_id=event_id, event_id=event_id):
                    attempts = await cast(
                        Awaitable[int],
                        self._redis.hincrby(
                            f"retry:{self._stream}:{self._group}", message_id, 1
                        ),
                    )
                    if attempts >= self._max_attempts:
                        await self._redis.xadd(
                            f"{self._stream}.dlq",
                            {
                                "messageId": message_id,
                                "payload": payload or b"",
                                "attempts": attempts,
                                "errorCode": type(error).__name__,
                            },
                        )
                        await self._redis.xack(self._stream, self._group, message_id)
                        await cast(
                            Awaitable[int],
                            self._redis.hdel(
                                f"retry:{self._stream}:{self._group}", message_id
                            ),
                        )
                        log_exception(
                            logger,
                            "stream message moved to DLQ",
                            event=LogEvent.STREAM_MESSAGE_DLQ,
                            outcome=LogOutcome.FAILED,
                            error=error,
                            stream=self._stream,
                            group=self._group,
                            attempts=attempts,
                        )
                        return
                    log_exception(
                        logger,
                        "stream message remains pending",
                        event=LogEvent.STREAM_MESSAGE_RETRY_PENDING,
                        outcome=LogOutcome.RETRY,
                        error=error,
                        stream=self._stream,
                        group=self._group,
                        attempts=attempts,
                    )
                raise
            try:
                await self._redis.xack(self._stream, self._group, message_id)
                await cast(
                    Awaitable[int],
                    self._redis.hdel(
                        f"retry:{self._stream}:{self._group}", message_id
                    ),
                )
            except Exception as error:
                log_exception(
                    logger,
                    "stream acknowledgement failed",
                    event=LogEvent.STREAM_MESSAGE_RETRY_PENDING,
                    outcome=LogOutcome.RETRY,
                    error=error,
                    stream=self._stream,
                    group=self._group,
                )
                raise
            if envelope is not None:
                with operation_context(operation_id=event_id, event_id=event_id):
                    log_event(
                        logger,
                        logging.INFO,
                        "stream message handled",
                        event=(
                            LogEvent.STREAM_MESSAGE_PROCESSED
                            if first_delivery
                            else LogEvent.STREAM_MESSAGE_DEDUPLICATED
                        ),
                        outcome=(
                            LogOutcome.SUCCESS if first_delivery else LogOutcome.SKIPPED
                        ),
                        stream=self._stream,
                        group=self._group,
                    )

    async def reclaim_stale(self, *, min_idle_ms: int = 300_000, count: int = 100) -> int:
        """Claim abandoned pending messages and process them under this consumer."""

        result = await self._redis.xautoclaim(
            self._stream,
            self._group,
            self._consumer,
            min_idle_ms,
            start_id="0-0",
            count=count,
        )
        messages = result[1]
        processed = 0
        for raw_message_id, fields in messages:
            message_id = (
                raw_message_id.decode() if isinstance(raw_message_id, bytes) else raw_message_id
            )
            with suppress(Exception):
                await self.process(message_id, fields)
            processed += 1
        return processed

    async def consume_new(self, *, block_ms: int = 1_000, count: int = 100) -> int:
        responses = await self._redis.xreadgroup(
            self._group,
            self._consumer,
            {self._stream: ">"},
            count=count,
            block=block_ms,
        )
        processed = 0
        for _stream, messages in responses:
            for raw_message_id, fields in messages:
                message_id = (
                    raw_message_id.decode()
                    if isinstance(raw_message_id, bytes)
                    else raw_message_id
                )
                with suppress(Exception):
                    await self.process(message_id, fields)
                processed += 1
        return processed

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        stop = stop_event or asyncio.Event()
        await self.ensure_group()
        while not stop.is_set():
            await self.reclaim_stale()
            await self.consume_new()

    async def replay_dlq(self, dlq_message_id: str) -> str | None:
        """Move one DLQ entry back to the source stream and delete it after enqueue."""

        dlq = f"{self._stream}.dlq"
        entries = await self._redis.xrange(
            dlq, min=dlq_message_id, max=dlq_message_id, count=1
        )
        if not entries:
            return None
        _entry_id, fields = entries[0]
        payload = fields.get(b"payload") or fields.get("payload")
        original_id = fields.get(b"messageId") or fields.get("messageId")
        if payload is None:
            raise ValueError("DLQ entry does not contain a payload")
        EventEnvelope.model_validate_json(payload)
        replayed = await self._redis.xadd(self._stream, {"payload": payload})
        await self._redis.xdel(dlq, dlq_message_id)
        if original_id is not None:
            normalized = original_id.decode() if isinstance(original_id, bytes) else original_id
            await cast(
                Awaitable[int],
                self._redis.hdel(f"retry:{self._stream}:{self._group}", normalized),
            )
        return replayed.decode() if isinstance(replayed, bytes) else str(replayed)


@app.command("relay")
def relay() -> None:
    async def run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(signum, stop.set)
        await relay_forever(stop)

    configure_logging(get_settings(), domain="event-relay")
    asyncio.run(run())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
