from __future__ import annotations

import logging
import re
from enum import StrEnum
from typing import Any

from app.observability.formatters import safe_exception

_EVENT_PATTERN = re.compile(r"^[a-z0-9]+(?:[._][a-z0-9]+)+$")
_FIELD_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RESERVED_FIELDS = frozenset(
    {
        "domain",
        "environment",
        "error_type",
        "event",
        "event_domain",
        "exception",
        "instance",
        "outcome",
        "pid",
    }
)


class LogOutcome(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"
    RETRY = "retry"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"


_OUTCOMES = frozenset(outcome.value for outcome in LogOutcome)


class LogEvent(StrEnum):
    SYSTEM_SERVICE_STARTED = "system.service.started"
    SYSTEM_SERVICE_READY = "system.service.ready"
    SYSTEM_SERVICE_STOPPING = "system.service.stopping"
    SYSTEM_SERVICE_STOPPED = "system.service.stopped"
    SYSTEM_SERVICE_FAILED = "system.service.failed"
    HTTP_REQUEST_COMPLETED = "http.request.completed"
    HTTP_REQUEST_FAILED = "http.request.failed"
    HTTP_REQUEST_VALIDATION_REJECTED = "http.request.validation_rejected"
    ITEM_CREATE_COMPLETED = "item.create.completed"
    AUTH_SIGNUP_COMPLETED = "auth.signup.completed"
    AUTH_LOGIN_COMPLETED = "auth.login.completed"
    AUTH_LOGIN_REJECTED = "auth.login.rejected"
    STREAM_OUTBOX_PUBLISHED = "stream.outbox.published"
    STREAM_OUTBOX_RETRY_SCHEDULED = "stream.outbox.retry_scheduled"
    STREAM_OUTBOX_PARKED = "stream.outbox.parked"
    STREAM_MESSAGE_PROCESSED = "stream.message.processed"
    STREAM_MESSAGE_DEDUPLICATED = "stream.message.deduplicated"
    STREAM_MESSAGE_RETRY_PENDING = "stream.message.retry_pending"
    STREAM_MESSAGE_DLQ = "stream.message.dlq"
    REPOSITORY_QUERY_EXECUTED = "repository.query.executed"
    REPOSITORY_QUERY_SLOW = "repository.query.slow"
    REPOSITORY_QUERY_FAILED = "repository.query.failed"


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    event: str | LogEvent,
    outcome: str | LogOutcome,
    **fields: object,
) -> None:
    event_value = str(event)
    outcome_value = str(outcome)
    if _EVENT_PATTERN.fullmatch(event_value) is None:
        raise ValueError("log event must be a stable lowercase dotted name")
    if outcome_value not in _OUTCOMES:
        raise ValueError("log outcome must use a supported stable value")
    extra: dict[str, Any] = {
        "event": event_value,
        "event_domain": event_value.split(".", maxsplit=1)[0],
        "outcome": outcome_value,
    }
    for name, value in fields.items():
        if _FIELD_PATTERN.fullmatch(name) is None:
            raise ValueError(f"invalid structured log field: {name}")
        if name in _RESERVED_FIELDS:
            raise ValueError(f"structured log field is runtime-owned: {name}")
        if value is not None:
            extra[name] = value
    logger.log(level, message, extra=extra)


def log_exception(
    logger: logging.Logger,
    message: str,
    *,
    event: str | LogEvent,
    error: BaseException,
    outcome: str | LogOutcome = LogOutcome.FAILED,
    **fields: object,
) -> None:
    event_value = str(event)
    outcome_value = str(outcome)
    if _EVENT_PATTERN.fullmatch(event_value) is None:
        raise ValueError("log event must be a stable lowercase dotted name")
    if outcome_value not in _OUTCOMES:
        raise ValueError("log outcome must use a supported stable value")
    extra: dict[str, object] = {
        "event": event_value,
        "event_domain": event_value.split(".", maxsplit=1)[0],
        "outcome": outcome_value,
        "error_type": type(error).__name__,
        "exception": safe_exception(error),
    }
    for name, value in fields.items():
        if _FIELD_PATTERN.fullmatch(name) is None or name in _RESERVED_FIELDS:
            raise ValueError(f"invalid structured log field: {name}")
        if value is not None:
            extra[name] = value
    logger.error(message, extra=extra)
