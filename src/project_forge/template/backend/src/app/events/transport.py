from __future__ import annotations

from redis.asyncio import Redis

from app.events.models import EventEnvelope


class RedisEventTransport:
    def __init__(self, redis: Redis, stream: str = "events") -> None:
        self._redis = redis
        self._stream = stream

    async def publish(self, envelope: EventEnvelope) -> str:
        message_id = await self._redis.xadd(
            self._stream,
            {
                "eventId": str(envelope.event_id),
                "eventType": envelope.event_type,
                "schemaVersion": str(envelope.schema_version),
                "createdAt": envelope.created_at.isoformat(),
                "payload": envelope.model_dump_json(by_alias=True),
            },
        )
        return message_id.decode() if isinstance(message_id, bytes) else str(message_id)
