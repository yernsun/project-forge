from __future__ import annotations

import json
import logging
import traceback
from collections.abc import Mapping
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any
from uuid import UUID

MAX_LOG_LINE_BYTES = 65_536
MAX_STRING_LENGTH = 2_048
MAX_COLLECTION_ITEMS = 50
MAX_NESTING_DEPTH = 4
REDACTED = "[REDACTED]"
_SENSITIVE_PARTS = (
    "authorization",
    "body",
    "cookie",
    "credential",
    "database_url",
    "header",
    "parameters",
    "password",
    "payload",
    "private_key",
    "secret",
    "session",
    "token",
)
_STANDARD_FIELDS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonLineFormatter(logging.Formatter):
    """Serialize one bounded, deterministic JSON object per record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _bounded_string(record.getMessage()),
        }
        truncated = False
        for name in sorted(record.__dict__):
            if name in _STANDARD_FIELDS or name.startswith("_") or name in payload:
                continue
            candidate = REDACTED if _sensitive_name(name) else _json_safe(
                record.__dict__[name], depth=0
            )
            payload[name] = candidate
            if len(_encode({**payload, "fields_truncated": True})) > MAX_LOG_LINE_BYTES:
                del payload[name]
                truncated = True
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = _safe_exception(record.exc_info)
        if truncated or len(_encode(payload)) > MAX_LOG_LINE_BYTES:
            payload.pop("exception", None)
            payload["fields_truncated"] = True
        return _encode(payload).decode("utf-8")


class ConsoleFormatter(logging.Formatter):
    """Keep console output readable without rendering exception values."""

    def format(self, record: logging.LogRecord) -> str:
        domain = getattr(record, "domain", "unknown")
        instance = getattr(record, "instance", "unknown")
        rendered = (
            f"{self.formatTime(record, self.datefmt)} {record.levelname} "
            f"[{domain}/{instance}] {record.name} {_bounded_string(record.getMessage())}"
        )
        error_type = getattr(record, "error_type", None)
        if isinstance(error_type, str):
            rendered += f" exception={error_type}"
        elif record.exc_info and record.exc_info[0] is not None:
            rendered += f" exception={record.exc_info[0].__name__}"
        return rendered


def _encode(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _bounded_string(value: object) -> str:
    text = str(value)
    if len(text) <= MAX_STRING_LENGTH:
        return text
    return text[:MAX_STRING_LENGTH] + "…"


def _sensitive_name(name: str) -> bool:
    normalized = name.lower()
    return any(part in normalized for part in _SENSITIVE_PARTS)


def _json_safe(value: object, *, depth: int) -> Any:
    if depth >= MAX_NESTING_DEPTH:
        return "[DEPTH_LIMIT]"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _bounded_string(value)
    if isinstance(value, Enum):
        return _json_safe(value.value, depth=depth + 1)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Path | UUID):
        return str(value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_COLLECTION_ITEMS:
                result["items_truncated"] = True
                break
            name = _bounded_string(key)
            result[name] = (
                REDACTED
                if _sensitive_name(name)
                else _json_safe(item, depth=depth + 1)
            )
        return result
    if isinstance(value, tuple | list | set | frozenset):
        items = list(value)
        rendered = [
            _json_safe(item, depth=depth + 1)
            for item in items[:MAX_COLLECTION_ITEMS]
        ]
        if len(items) > MAX_COLLECTION_ITEMS:
            rendered.append("[ITEM_LIMIT]")
        return rendered
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump(mode="json"), depth=depth + 1)
    return f"<{type(value).__name__}>"


def _safe_exception(
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None],
) -> dict[str, object]:
    exception_type, _error, raw_traceback = exc_info
    frames: list[dict[str, object]] = []
    if raw_traceback is not None:
        for frame in traceback.extract_tb(raw_traceback)[-20:]:
            frames.append(
                {
                    "file": Path(frame.filename).name,
                    "line": frame.lineno,
                    "function": frame.name,
                }
            )
    return {"type": exception_type.__name__, "frames": frames}


def safe_exception(error: BaseException) -> dict[str, object]:
    """Return stack locations and type without retaining or formatting the exception value."""

    return _safe_exception((type(error), error, error.__traceback__))
