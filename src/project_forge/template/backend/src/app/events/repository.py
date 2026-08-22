from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb

from app.db.types import DbConnection
from app.domain.base import utc_now
from app.events.models import EventEnvelope, OutboxRecord


class OutboxRepository:
    def __init__(self, connection: DbConnection) -> None:
        self._connection = connection

    async def append(self, envelope: EventEnvelope) -> None:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    "INSERT INTO outbox_events ("
                    "event_id, event_type, schema_version, payload, created_at, available_at"
                    ") VALUES ("
                    "%(event_id)s, %(event_type)s, %(schema_version)s, %(payload)s, "
                    "%(created_at)s, %(available_at)s)"
                ),
                {
                    "event_id": envelope.event_id,
                    "event_type": envelope.event_type,
                    "schema_version": envelope.schema_version,
                    "payload": Jsonb(envelope.payload),
                    "created_at": envelope.created_at,
                    "available_at": envelope.created_at,
                },
            )

    async def claim(self, worker_id: str, limit: int = 100) -> tuple[OutboxRecord, ...]:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    "WITH candidates AS ("
                    " SELECT event_id FROM outbox_events"
                    " WHERE published_at IS NULL AND available_at <= %(now)s"
                    "   AND (locked_at IS NULL OR locked_at < %(stale_before)s)"
                    " ORDER BY created_at, event_id FOR UPDATE SKIP LOCKED LIMIT %(limit)s"
                    ") UPDATE outbox_events o SET locked_at = %(now)s, locked_by = %(worker_id)s,"
                    " attempts = o.attempts + 1 FROM candidates c WHERE o.event_id = c.event_id"
                    " RETURNING o.event_id, o.event_type, o.schema_version, o.payload,"
                    " o.created_at, o.attempts"
                ),
                {
                    "now": utc_now(),
                    "stale_before": utc_now() - timedelta(minutes=5),
                    "limit": limit,
                    "worker_id": worker_id,
                },
                prepare=False,
            )
            rows = await cursor.fetchall()
        return tuple(
            OutboxRecord(
                envelope=EventEnvelope(
                    event_id=row["event_id"],
                    event_type=row["event_type"],
                    schema_version=row["schema_version"],
                    payload=row["payload"],
                    created_at=row["created_at"],
                ),
                attempts=row["attempts"],
            )
            for row in rows
        )

    async def mark_published(self, event_id: UUID) -> None:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    "UPDATE outbox_events SET published_at = %(now)s, locked_at = NULL, "
                    "locked_by = NULL WHERE event_id = %(event_id)s"
                ),
                {"now": utc_now(), "event_id": event_id},
            )

    async def release_with_backoff(self, event_id: UUID, attempts: int) -> None:
        delay_seconds = min(300, 2 ** min(attempts, 8))
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    "UPDATE outbox_events SET available_at = %(available_at)s, locked_at = NULL, "
                    "locked_by = NULL WHERE event_id = %(event_id)s"
                ),
                {
                    "available_at": utc_now() + timedelta(seconds=delay_seconds),
                    "event_id": event_id,
                },
            )


class ProcessedMessageRepository:
    def __init__(self, connection: DbConnection) -> None:
        self._connection = connection

    async def mark_once(self, consumer_name: str, message_id: str) -> bool:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL(
                    "INSERT INTO processed_messages (consumer_name, message_id, processed_at) "
                    "VALUES (%(consumer_name)s, %(message_id)s, %(processed_at)s) "
                    "ON CONFLICT DO NOTHING RETURNING message_id"
                ),
                {
                    "consumer_name": consumer_name,
                    "message_id": message_id,
                    "processed_at": utc_now(),
                },
            )
            row = await cursor.fetchone()
        return row is not None
