from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from psycopg import sql
from redis.asyncio import Redis

from app.db.migration_engine import MigrationRunner
from app.db.migrations.core import CORE
from app.db.migrations.event_idempotency import EVENT_IDEMPOTENCY
from app.db.migrations.events import EVENTS
from app.db.pool import create_pool
from app.events.models import EventEnvelope
from app.events.repository import ProcessedMessageRepository
from app.events.worker import StreamConsumer
from app.uow.factory import UnitOfWorkFactory
from app.uow.unit import UnitOfWork


def test_event_envelope_serializes_camel_case() -> None:
    envelope = EventEnvelope.new("example.created", {"itemId": "42"})
    payload = envelope.model_dump(by_alias=True, mode="json")
    assert payload["eventType"] == "example.created"
    assert payload["schemaVersion"] == 1
    assert "event_type" not in payload


class _ProcessedMessages:
    def __init__(self) -> None:
        self.seen: set[tuple[str, UUID]] = set()

    async def mark_once(self, consumer_name: str, event_id: UUID) -> bool:
        key = (consumer_name, event_id)
        if key in self.seen:
            return False
        self.seen.add(key)
        return True


class _UnitOfWork:
    def __init__(self, processed_messages: _ProcessedMessages) -> None:
        self.processed_messages = processed_messages

    async def __aenter__(self) -> _UnitOfWork:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _UnitOfWorkFactory:
    def __init__(self, processed_messages: _ProcessedMessages) -> None:
        self.processed_messages = processed_messages

    def __call__(self) -> _UnitOfWork:
        return _UnitOfWork(self.processed_messages)


class _Redis:
    def __init__(self) -> None:
        self.acked: list[tuple[str, str, str]] = []

    async def xack(self, stream: str, group: str, message_id: str) -> int:
        self.acked.append((stream, group, message_id))
        return 1

    async def hdel(self, _key: str, _message_id: str) -> int:
        return 1


class _FailingRedis(_Redis):
    def __init__(self, attempts: int) -> None:
        super().__init__()
        self.attempts = attempts
        self.dlq: list[tuple[str, dict[str, object]]] = []

    async def hincrby(self, _key: str, _message_id: str, _amount: int) -> int:
        return self.attempts

    async def xadd(self, stream: str, fields: dict[str, object]) -> str:
        self.dlq.append((stream, fields))
        return "2000-0"


@pytest.mark.asyncio
async def test_same_event_under_two_stream_ids_is_applied_once_and_both_are_acked() -> None:
    envelope = EventEnvelope.new("example.created", {"itemId": "42"})
    fields = {b"payload": envelope.model_dump_json(by_alias=True).encode()}
    processed_messages = _ProcessedMessages()
    redis = _Redis()
    handler = AsyncMock()
    consumer = StreamConsumer(
        cast(Redis, redis),
        cast(UnitOfWorkFactory, _UnitOfWorkFactory(processed_messages)),
        stream="events",
        group="example-projector",
        consumer="test-consumer",
        handler=cast(Callable[[UnitOfWork, EventEnvelope], Awaitable[None]], handler),
    )

    await consumer.process("1000-0", fields)
    await consumer.process("1001-0", fields)

    assert handler.await_count == 1
    assert processed_messages.seen == {("example-projector", envelope.event_id)}
    assert redis.acked == [
        ("events", "example-projector", "1000-0"),
        ("events", "example-projector", "1001-0"),
    ]


@pytest.mark.asyncio
async def test_exhausted_stream_message_is_parked_in_dlq_and_acked() -> None:
    envelope = EventEnvelope.new("example.failed", {"itemId": "42"})
    fields = {b"payload": envelope.model_dump_json(by_alias=True).encode()}
    redis = _FailingRedis(attempts=2)
    handler = AsyncMock(side_effect=RuntimeError("sensitive failure detail"))
    consumer = StreamConsumer(
        cast(Redis, redis),
        cast(UnitOfWorkFactory, _UnitOfWorkFactory(_ProcessedMessages())),
        stream="events",
        group="example-projector",
        consumer="test-consumer",
        handler=cast(Callable[[UnitOfWork, EventEnvelope], Awaitable[None]], handler),
        max_attempts=2,
    )

    await consumer.process("1000-0", fields)

    assert redis.acked == [("events", "example-projector", "1000-0")]
    assert redis.dlq[0][0] == "events.dlq"
    assert redis.dlq[0][1]["errorCode"] == "RuntimeError"
    assert "sensitive failure detail" not in str(redis.dlq)


@pytest.mark.asyncio
async def test_malformed_stream_payload_is_bounded_and_moved_to_dlq() -> None:
    raw_payload = b'{"eventId":"not-a-uuid"}'
    redis = _FailingRedis(attempts=2)
    handler = AsyncMock()
    consumer = StreamConsumer(
        cast(Redis, redis),
        cast(UnitOfWorkFactory, _UnitOfWorkFactory(_ProcessedMessages())),
        stream="events",
        group="example-projector",
        consumer="test-consumer",
        handler=cast(Callable[[UnitOfWork, EventEnvelope], Awaitable[None]], handler),
        max_attempts=2,
    )

    await consumer.process("1002-0", {b"payload": raw_payload})

    handler.assert_not_awaited()
    assert redis.acked == [("events", "example-projector", "1002-0")]
    assert redis.dlq == [
        (
            "events.dlq",
            {
                "messageId": "1002-0",
                "payload": raw_payload,
                "attempts": 2,
                "errorCode": "ValidationError",
            },
        )
    ]


class _ReclaimRedis(_Redis):
    def __init__(self, fields: dict[bytes, bytes]) -> None:
        super().__init__()
        self.fields = fields

    async def xautoclaim(
        self, *_args: object, **_kwargs: object
    ) -> tuple[str, list[tuple[bytes, dict[bytes, bytes]]], list[bytes]]:
        return "0-0", [(b"1000-0", self.fields)], []


@pytest.mark.asyncio
async def test_consumer_reclaims_and_processes_abandoned_pending_messages() -> None:
    envelope = EventEnvelope.new("example.reclaimed", {"itemId": "42"})
    fields = {b"payload": envelope.model_dump_json(by_alias=True).encode()}
    redis = _ReclaimRedis(fields)
    handler = AsyncMock()
    consumer = StreamConsumer(
        cast(Redis, redis),
        cast(UnitOfWorkFactory, _UnitOfWorkFactory(_ProcessedMessages())),
        stream="events",
        group="example-projector",
        consumer="test-consumer",
        handler=cast(Callable[[UnitOfWork, EventEnvelope], Awaitable[None]], handler),
    )

    assert await consumer.reclaim_stale() == 1
    handler.assert_awaited_once()
    assert redis.acked == [("events", "example-projector", "1000-0")]


@pytest.mark.asyncio
async def test_event_idempotency_migration_preserves_legacy_markers() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    schema_name = f"event_idempotency_{uuid4().hex}"
    pool = create_pool(database_url)
    await pool.open()
    try:
        async with pool.connection() as connection:
            try:
                await connection.execute(
                    sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
                )
                await connection.commit()
                await connection.execute(
                    sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name))
                )
                await connection.commit()

                assert await MigrationRunner(connection, (CORE, EVENTS)).up() == (
                    "0001_core",
                    "0030_events",
                )
                await connection.execute(
                    sql.SQL(
                        "INSERT INTO processed_messages "
                        "(consumer_name, message_id, processed_at) VALUES "
                        "('example-projector', '1000-0', now())"
                    )
                )
                await connection.commit()

                assert await MigrationRunner(
                    connection, (CORE, EVENTS, EVENT_IDEMPOTENCY)
                ).up() == ("0031_event_idempotency",)
                cursor = await connection.execute(
                    sql.SQL(
                        "SELECT event_id FROM processed_messages "
                        "WHERE consumer_name = 'example-projector'"
                    )
                )
                legacy = await cursor.fetchone()
                assert legacy is not None
                assert legacy["event_id"] == "1000-0"

                repository = ProcessedMessageRepository(connection)
                event_id = uuid4()
                assert await repository.mark_once("example-projector", event_id)
                assert not await repository.mark_once("example-projector", event_id)
                await connection.commit()
            finally:
                await connection.rollback()
                await connection.execute(sql.SQL("SET search_path TO public"))
                await connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(schema_name)
                    )
                )
                await connection.commit()
    finally:
        await pool.close()
