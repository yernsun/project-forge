from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb

from app.domain.base import utc_now
from app.events.models import EventEnvelope, OutboxRecord, OutboxStatus
from app.repositories.base import BaseRepository


class OutboxRepository(BaseRepository, Protocol):
    """Persistence contract for transactional outbox records."""

    async def append(self, envelope: EventEnvelope) -> None: ...

    async def claim(self, worker_id: str, limit: int = 100) -> tuple[OutboxRecord, ...]: ...

    async def mark_published(self, event_id: UUID) -> None: ...

    async def release_with_backoff(
        self,
        event_id: UUID,
        attempts: int,
        *,
        error_code: str,
        max_attempts: int,
    ) -> bool: ...

    async def status(self, now: datetime) -> OutboxStatus: ...

    async def retry_failed(self, *, now: datetime, limit: int) -> tuple[UUID, ...]: ...


class ProcessedMessageRepository(BaseRepository, Protocol):
    """Persistence contract for consumer idempotency."""

    async def mark_once(self, consumer_name: str, event_id: UUID) -> bool: ...


class PostgresOutboxRepository(BaseRepository):
    """Psycopg outbox implementation created only by UnitOfWork."""

    async def append(self, envelope: EventEnvelope) -> None:
        await self.connection.execute(
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
            prepare=True,
        )

    async def claim(self, worker_id: str, limit: int = 100) -> tuple[OutboxRecord, ...]:
        now = utc_now()
        rows = await self.connection.fetch_all(
            sql.SQL(
                "WITH candidates AS ("
                " SELECT event_id FROM outbox_events"
                " WHERE published_at IS NULL AND failed_at IS NULL"
                "   AND available_at <= %(now)s"
                "   AND (locked_at IS NULL OR locked_at < %(stale_before)s)"
                " ORDER BY created_at, event_id FOR UPDATE SKIP LOCKED LIMIT %(limit)s"
                ") UPDATE outbox_events o SET locked_at = %(now)s, locked_by = %(worker_id)s,"
                " attempts = o.attempts + 1 FROM candidates c WHERE o.event_id = c.event_id"
                " RETURNING o.event_id, o.event_type, o.schema_version, o.payload,"
                " o.created_at, o.attempts"
            ),
            {
                "now": now,
                "stale_before": now - timedelta(minutes=5),
                "limit": limit,
                "worker_id": worker_id,
            },
            prepare=True,
        )
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
        await self.connection.execute(
            sql.SQL(
                "UPDATE outbox_events SET published_at = %(now)s, locked_at = NULL, "
                "locked_by = NULL WHERE event_id = %(event_id)s"
            ),
            {"now": utc_now(), "event_id": event_id},
            prepare=True,
        )

    async def release_with_backoff(
        self,
        event_id: UUID,
        attempts: int,
        *,
        error_code: str,
        max_attempts: int,
    ) -> bool:
        """Release for retry or park after the bounded attempt count; return parked state."""

        now = utc_now()
        if attempts >= max_attempts:
            await self.connection.execute(
                sql.SQL(
                    "UPDATE outbox_events SET failed_at = %(now)s, "
                    "last_failed_at = %(now)s, last_error_code = %(error_code)s, "
                    "locked_at = NULL, locked_by = NULL WHERE event_id = %(event_id)s"
                ),
                {"now": now, "error_code": error_code[:200], "event_id": event_id},
                prepare=True,
            )
            return True
        delay_seconds = min(300, 2 ** min(attempts, 8))
        await self.connection.execute(
            sql.SQL(
                "UPDATE outbox_events SET available_at = %(available_at)s, "
                "last_failed_at = %(now)s, last_error_code = %(error_code)s, "
                "locked_at = NULL, locked_by = NULL WHERE event_id = %(event_id)s"
            ),
            {
                "available_at": now + timedelta(seconds=delay_seconds),
                "now": now,
                "error_code": error_code[:200],
                "event_id": event_id,
            },
            prepare=True,
        )
        return False

    async def status(self, now: datetime) -> OutboxStatus:
        row = await self.connection.fetch_one(
            sql.SQL(
                "SELECT "
                "count(*) FILTER (WHERE published_at IS NULL AND failed_at IS NULL "
                "AND available_at <= %(now)s) AS ready, "
                "count(*) FILTER (WHERE published_at IS NULL AND failed_at IS NULL "
                "AND available_at > %(now)s) AS deferred, "
                "count(*) FILTER (WHERE published_at IS NULL AND failed_at IS NOT NULL) "
                "AS failed, "
                "count(*) FILTER (WHERE published_at IS NOT NULL) AS published "
                "FROM outbox_events"
            ),
            {"now": now},
            prepare=True,
        )
        if row is None:
            raise RuntimeError("outbox status query returned no row")
        return OutboxStatus.model_validate(row)

    async def retry_failed(self, *, now: datetime, limit: int) -> tuple[UUID, ...]:
        rows = await self.connection.fetch_all(
            sql.SQL(
                "WITH candidates AS ("
                " SELECT event_id FROM outbox_events"
                " WHERE published_at IS NULL AND failed_at IS NOT NULL"
                " ORDER BY failed_at, event_id FOR UPDATE SKIP LOCKED LIMIT %(limit)s"
                ") UPDATE outbox_events o SET failed_at = NULL, attempts = 0, "
                "available_at = %(now)s, locked_at = NULL, locked_by = NULL, "
                "last_error_code = NULL FROM candidates c WHERE o.event_id = c.event_id "
                "RETURNING o.event_id"
            ),
            {"now": now, "limit": limit},
            prepare=True,
        )
        return tuple(row["event_id"] for row in rows)


class PostgresProcessedMessageRepository(BaseRepository):
    """Psycopg idempotency implementation created only by UnitOfWork."""

    async def mark_once(self, consumer_name: str, event_id: UUID) -> bool:
        """Persist the stable business event ID, never the Redis stream entry ID."""

        row = await self.connection.fetch_one(
            sql.SQL(
                "INSERT INTO processed_messages (consumer_name, event_id, processed_at) "
                "VALUES (%(consumer_name)s, %(event_id)s, %(processed_at)s) "
                "ON CONFLICT DO NOTHING RETURNING event_id"
            ),
            {
                "consumer_name": consumer_name,
                "event_id": str(event_id),
                "processed_at": utc_now(),
            },
            prepare=True,
        )
        return row is not None
