from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

OPERATION_FIELDS = (
    "request_id",
    "operation_id",
    "correlation_id",
    "causation_id",
    "actor_id",
    "workspace_id",
    "event_id",
    "message_id",
)

_OPERATION_CONTEXT: ContextVar[dict[str, object] | None] = ContextVar(
    "application_operation_context", default=None
)


def get_operation_context() -> dict[str, object]:
    """Return a copy of context local to the current async task."""

    return dict(_OPERATION_CONTEXT.get() or {})


def current_request_id() -> str | None:
    value = get_operation_context().get("request_id")
    return str(value) if value is not None else None


@contextmanager
def operation_context(
    *,
    request_id: object | None = None,
    operation_id: object | None = None,
    correlation_id: object | None = None,
    causation_id: object | None = None,
    actor_id: object | None = None,
    workspace_id: object | None = None,
    event_id: object | None = None,
    message_id: object | None = None,
) -> Iterator[None]:
    """Merge bounded correlation identifiers and restore the parent reliably."""

    values = {
        name: value
        for name, value in {
            "request_id": request_id,
            "operation_id": operation_id,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "actor_id": actor_id,
            "workspace_id": workspace_id,
            "event_id": event_id,
            "message_id": message_id,
        }.items()
        if value is not None and str(value) != ""
    }
    merged = get_operation_context()
    merged.update(values)
    token = _OPERATION_CONTEXT.set(merged)
    try:
        yield
    finally:
        _OPERATION_CONTEXT.reset(token)
