from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
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
from app.db.repository_connection import PsycopgRepositoryConnection
from app.events import worker as worker_module
from app.events.models import EventEnvelope, OutboxRecord, OutboxStatus
from app.events.repository import (
    PostgresOutboxRepository,
    PostgresProcessedMessageRepository,
)
from app.events.service import OutboxService
from app.events.transport import RedisEventTransport
from app.events.worker import StreamConsumer
from app.repositories.base import RepositoryConnection
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
async def test_outbox_repository_covers_delivery_retry_and_status_paths() -> None:
    connection = AsyncMock()
    repository = PostgresOutboxRepository(cast(RepositoryConnection, connection))
    envelope = EventEnvelope.new("example.created", {"itemId": "42"})

    await repository.append(envelope)
    connection.execute.assert_awaited_once()

    connection.fetch_all.return_value = [
        {
            "event_id": envelope.event_id,
            "event_type": envelope.event_type,
            "schema_version": envelope.schema_version,
            "payload": envelope.payload,
            "created_at": envelope.created_at,
            "attempts": 1,
        }
    ]
    claimed = await repository.claim("worker-1", limit=5)
    assert claimed == (OutboxRecord(envelope=envelope, attempts=1),)

    await repository.mark_published(envelope.event_id)
    assert await repository.release_with_backoff(
        envelope.event_id,
        5,
        error_code="x" * 300,
        max_attempts=5,
    )
    assert not await repository.release_with_backoff(
        envelope.event_id,
        1,
        error_code="temporary",
        max_attempts=5,
    )

    connection.fetch_one.return_value = {
        "ready": 1,
        "deferred": 2,
        "failed": 3,
        "published": 4,
    }
    assert await repository.status(envelope.created_at) == OutboxStatus(
        ready=1, deferred=2, failed=3, published=4
    )
    connection.fetch_one.return_value = None
    with pytest.raises(RuntimeError, match="returned no row"):
        await repository.status(envelope.created_at)

    connection.fetch_all.return_value = [{"event_id": envelope.event_id}]
    assert await repository.retry_failed(now=envelope.created_at, limit=10) == (
        envelope.event_id,
    )

    processed = PostgresProcessedMessageRepository(
        cast(RepositoryConnection, connection)
    )
    connection.fetch_one.side_effect = [{"event_id": str(envelope.event_id)}, None]
    assert await processed.mark_once("projector", envelope.event_id)
    assert not await processed.mark_once("projector", envelope.event_id)


class _OutboxUnitOfWork:
    def __init__(self, repository: object) -> None:
        self.outbox = repository

    async def __aenter__(self) -> _OutboxUnitOfWork:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _OutboxFactory:
    def __init__(self, repository: object) -> None:
        self.repository = repository

    def __call__(self) -> _OutboxUnitOfWork:
        return _OutboxUnitOfWork(self.repository)


@pytest.mark.asyncio
async def test_outbox_service_and_transport_delegate_all_operations() -> None:
    envelope = EventEnvelope.new("example.created", {"itemId": "42"})
    record = OutboxRecord(envelope=envelope, attempts=1)
    repository = SimpleNamespace(
        claim=AsyncMock(return_value=(record,)),
        mark_published=AsyncMock(),
        release_with_backoff=AsyncMock(return_value=True),
        status=AsyncMock(return_value=OutboxStatus(ready=1, deferred=0, failed=0, published=2)),
        retry_failed=AsyncMock(return_value=(envelope.event_id,)),
    )
    service = OutboxService(
        cast(UnitOfWorkFactory, _OutboxFactory(repository))
    )
    assert await service.claim("worker", 7) == (record,)
    await service.mark_published(envelope.event_id)
    assert await service.release(
        envelope.event_id,
        2,
        error_code="TimeoutError",
        max_attempts=5,
    )
    assert (await service.status()).published == 2
    assert await service.retry_failed(3) == (envelope.event_id,)

    redis = SimpleNamespace(xadd=AsyncMock(side_effect=[b"1000-0", "1001-0"]))
    transport = RedisEventTransport(cast(Redis, redis), stream="domain-events")
    assert await transport.publish(envelope) == "1000-0"
    assert await transport.publish(envelope) == "1001-0"
    assert redis.xadd.await_args_list[0].args[0] == "domain-events"


def _consumer(redis: object, *, handler: AsyncMock | None = None) -> StreamConsumer:
    return StreamConsumer(
        cast(Redis, redis),
        cast(UnitOfWorkFactory, _UnitOfWorkFactory(_ProcessedMessages())),
        stream="events",
        group="example-projector",
        consumer="test-consumer",
        handler=cast(
            Callable[[UnitOfWork, EventEnvelope], Awaitable[None]],
            handler or AsyncMock(),
        ),
        max_attempts=2,
    )


@pytest.mark.asyncio
async def test_consumer_group_retry_and_polling_paths() -> None:
    group_redis = SimpleNamespace(xgroup_create=AsyncMock())
    await _consumer(group_redis).ensure_group()
    group_redis.xgroup_create.side_effect = RuntimeError("BUSYGROUP already exists")
    await _consumer(group_redis).ensure_group()
    group_redis.xgroup_create.side_effect = RuntimeError("connection lost")
    with pytest.raises(RuntimeError, match="connection lost"):
        await _consumer(group_redis).ensure_group()

    retry_redis = _FailingRedis(attempts=1)
    with pytest.raises(ValueError, match="does not contain a payload"):
        await _consumer(retry_redis).process("missing-0", {})
    assert retry_redis.acked == []

    envelope = EventEnvelope.new("example.created", {"itemId": "42"})
    fields = {b"payload": envelope.model_dump_json(by_alias=True).encode()}
    read_redis = SimpleNamespace(
        xreadgroup=AsyncMock(
            return_value=[(b"events", [(b"1000-0", fields), ("1001-0", fields)])]
        ),
        xack=AsyncMock(return_value=1),
        hdel=AsyncMock(return_value=1),
    )
    assert await _consumer(read_redis).consume_new(block_ms=2, count=2) == 2
    assert read_redis.xack.await_count == 2

    failing_read_redis = SimpleNamespace(
        xreadgroup=AsyncMock(return_value=[("events", [("1002-0", fields)])]),
        hincrby=AsyncMock(return_value=1),
        xack=AsyncMock(return_value=1),
        hdel=AsyncMock(return_value=1),
    )
    assert await _consumer(
        failing_read_redis,
        handler=AsyncMock(side_effect=RuntimeError("retry")),
    ).consume_new() == 1
    failing_read_redis.xack.assert_not_awaited()

    reclaim_redis = SimpleNamespace(
        xautoclaim=AsyncMock(return_value=("0-0", [("1003-0", fields)], [])),
        hincrby=AsyncMock(return_value=1),
        xack=AsyncMock(return_value=1),
        hdel=AsyncMock(return_value=1),
    )
    assert await _consumer(
        reclaim_redis,
        handler=AsyncMock(side_effect=RuntimeError("retry")),
    ).reclaim_stale() == 1


@pytest.mark.asyncio
async def test_consumer_run_loop_and_dlq_replay_paths() -> None:
    stop = asyncio.Event()
    consumer = _consumer(SimpleNamespace())
    consumer.ensure_group = AsyncMock()  # type: ignore[method-assign]

    async def reclaim_once() -> int:
        stop.set()
        return 0

    consumer.reclaim_stale = reclaim_once  # type: ignore[method-assign]
    consumer.consume_new = AsyncMock(return_value=0)  # type: ignore[method-assign]
    await consumer.run_forever(stop)
    consumer.ensure_group.assert_awaited_once()  # type: ignore[union-attr]
    consumer.consume_new.assert_awaited_once()  # type: ignore[union-attr]

    envelope = EventEnvelope.new("example.replay", {"itemId": "42"})
    payload = envelope.model_dump_json(by_alias=True).encode()
    redis = SimpleNamespace(
        xrange=AsyncMock(return_value=[]),
        xadd=AsyncMock(side_effect=[b"2000-0", "2001-0"]),
        xdel=AsyncMock(return_value=1),
        hdel=AsyncMock(return_value=1),
    )
    replay = _consumer(redis)
    assert await replay.replay_dlq("1000-0") is None

    redis.xrange.return_value = [(b"1000-0", {b"messageId": b"original-0"})]
    with pytest.raises(ValueError, match="does not contain a payload"):
        await replay.replay_dlq("1000-0")

    redis.xrange.return_value = [
        (b"1000-0", {b"payload": payload, b"messageId": b"original-0"})
    ]
    assert await replay.replay_dlq("1000-0") == "2000-0"
    redis.xrange.return_value = [
        ("1001-0", {"payload": payload.decode(), "messageId": "original-1"})
    ]
    assert await replay.replay_dlq("1001-0") == "2001-0"
    assert redis.xdel.await_count == 2
    assert redis.hdel.await_count == 2


@pytest.mark.asyncio
async def test_relay_forever_marks_success_and_releases_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    first = EventEnvelope.new("example.first", {"itemId": "1"})
    second = EventEnvelope.new("example.second", {"itemId": "2"})
    records = (
        OutboxRecord(envelope=first, attempts=1),
        OutboxRecord(envelope=second, attempts=2),
    )
    service = SimpleNamespace(
        mark_published=AsyncMock(),
        release=AsyncMock(return_value=False),
    )

    async def claim(_worker_id: str) -> tuple[OutboxRecord, ...]:
        stop.set()
        return records

    service.claim = claim
    pool = SimpleNamespace(open=AsyncMock(), close=AsyncMock())
    redis = SimpleNamespace(aclose=AsyncMock())
    transport = SimpleNamespace(
        publish=AsyncMock(side_effect=[None, RuntimeError("redis unavailable")])
    )
    settings = SimpleNamespace(
        database_url="postgresql://example",
        redis_url="redis://example",
        event_relay_max_attempts=5,
        event_relay_poll_seconds=0.01,
    )
    monkeypatch.setattr(worker_module, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_module, "create_pool", lambda _url: pool)
    monkeypatch.setattr(
        worker_module,
        "Redis",
        SimpleNamespace(from_url=lambda _url: redis),
    )
    monkeypatch.setattr(worker_module, "OutboxService", lambda _factory: service)
    monkeypatch.setattr(worker_module, "RedisEventTransport", lambda _redis: transport)

    await worker_module.relay_forever(stop)
    service.mark_published.assert_awaited_once_with(first.event_id)
    service.release.assert_awaited_once_with(
        second.event_id,
        2,
        error_code="RuntimeError",
        max_attempts=5,
    )
    redis.aclose.assert_awaited_once()
    pool.close.assert_awaited_once()


def test_relay_command_configures_logging_and_runs_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = AsyncMock()
    monkeypatch.setattr(worker_module, "configure_logging", lambda: None)
    monkeypatch.setattr(worker_module, "relay_forever", configured)
    worker_module.relay()
    configured.assert_awaited_once()


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

                owner = asyncio.current_task()
                if owner is None:
                    raise RuntimeError("integration test requires an asyncio task")
                guarded_connection = PsycopgRepositoryConnection(connection, owner)
                repository = PostgresProcessedMessageRepository(guarded_connection)
                event_id = uuid4()
                assert await repository.mark_once("example-projector", event_id)
                assert not await repository.mark_once("example-projector", event_id)
                guarded_connection.finish()
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
