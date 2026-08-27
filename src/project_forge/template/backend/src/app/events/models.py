from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, JsonValue

from app.domain.base import StrictDomainModel, utc_now


class EventEnvelope(StrictDomainModel):
    event_id: UUID = Field(description="Globally unique event ID")
    event_type: str = Field(min_length=1, max_length=200, description="Stable event type")
    schema_version: int = Field(default=1, ge=1, description="Payload schema version")
    payload: dict[str, JsonValue] = Field(description="Camel-case boundary payload")
    created_at: datetime = Field(description="UTC event time")

    @classmethod
    def new(cls, event_type: str, payload: dict[str, JsonValue]) -> EventEnvelope:
        return cls(
            event_id=uuid4(),
            event_type=event_type,
            schema_version=1,
            payload=payload,
            created_at=utc_now(),
        )


class OutboxRecord(StrictDomainModel):
    envelope: EventEnvelope = Field(description="Event to publish")
    attempts: int = Field(ge=0, description="Publish attempts")


class OutboxStatus(StrictDomainModel):
    ready: int = Field(ge=0, description="Rows eligible for immediate relay")
    deferred: int = Field(ge=0, description="Rows waiting for retry or held by a relay")
    failed: int = Field(ge=0, description="Rows parked after exhausting retries")
    published: int = Field(ge=0, description="Rows already published")
