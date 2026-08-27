from __future__ import annotations

import json
import logging
import re
import time
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_REQUEST_ID = ContextVar[str | None]("request_id", default=None)
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LOG_FIELDS = (
    "event",
    "request_id",
    "method",
    "path",
    "status",
    "duration_ms",
    "validation_errors",
)


def current_request_id() -> str | None:
    return _REQUEST_ID.get()


def _request_id(headers: list[tuple[bytes, bytes]]) -> str:
    values = [value for name, value in headers if name.lower() == b"x-request-id"]
    if len(values) != 1:
        return uuid4().hex
    try:
        candidate = values[0].decode("ascii")
    except UnicodeDecodeError:
        return uuid4().hex
    if _SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return uuid4().hex


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _LOG_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def configure_logging() -> None:
    """Install one JSON handler for application-owned loggers."""

    logger = logging.getLogger("app")
    if any(getattr(handler, "_project_forge_json", False) for handler in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    handler._project_forge_json = True  # type: ignore[attr-defined]
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class RequestContextMiddleware:
    """Attach a safe request ID and emit body-free structured access logs."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._logger = logging.getLogger("app.access")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = _request_id(scope.get("headers", []))
        token: Token[str | None] = _REQUEST_ID.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers = [item for item in headers if item[0].lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self._app(scope, receive, send_with_request_id)
        except BaseException:
            self._logger.exception(
                "request failed",
                extra={
                    "event": "request_failed",
                    "request_id": request_id,
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                },
            )
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            self._logger.info(
                "request completed",
                extra={
                    "event": "request_completed",
                    "request_id": request_id,
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status_code,
                    "duration_ms": duration_ms,
                },
            )
            _REQUEST_ID.reset(token)
