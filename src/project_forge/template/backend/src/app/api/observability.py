from __future__ import annotations

import logging
import re
import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability import (
    LogEvent,
    LogOutcome,
    configure_logging,
    current_request_id,
    log_event,
    log_exception,
    operation_context,
)
from app.observability.formatters import JsonLineFormatter as JsonLogFormatter

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


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


class RequestContextMiddleware:
    """Attach a safe request ID and emit body-free structured access logs."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._logger = logging.getLogger(__name__)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = _request_id(scope.get("headers", []))
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

        with operation_context(request_id=request_id, operation_id=request_id):
            try:
                await self._app(scope, receive, send_with_request_id)
            except BaseException as error:
                log_exception(
                    self._logger,
                    "request failed",
                    event=LogEvent.HTTP_REQUEST_FAILED,
                    outcome=LogOutcome.FAILED,
                    error=error,
                    method=scope.get("method"),
                    path=scope.get("path"),
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                )
                raise
            else:
                level = logging.ERROR if status_code >= 500 else logging.INFO
                log_event(
                    self._logger,
                    level,
                    "request completed",
                    event=LogEvent.HTTP_REQUEST_COMPLETED,
                    outcome=(
                        LogOutcome.FAILED
                        if status_code >= 500
                        else (
                            LogOutcome.REJECTED
                            if status_code >= 400
                            else LogOutcome.SUCCESS
                        )
                    ),
                    method=scope.get("method"),
                    path=scope.get("path"),
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                )


__all__ = [
    "JsonLogFormatter",
    "RequestContextMiddleware",
    "configure_logging",
    "current_request_id",
]
