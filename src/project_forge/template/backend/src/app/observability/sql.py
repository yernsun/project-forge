from __future__ import annotations

import logging
from dataclasses import dataclass

from app.observability.events import LogEvent, LogOutcome, log_event, log_exception

logger = logging.getLogger("app.sql")


@dataclass(frozen=True, slots=True)
class SqlObservabilityConfig:
    enabled: bool = True
    slow_ms: float = 200.0


_config = SqlObservabilityConfig(enabled=False)


def configure_sql_observability(*, enabled: bool, slow_ms: float) -> None:
    global _config
    _config = SqlObservabilityConfig(enabled=enabled, slow_ms=slow_ms)


def record_sql_query(
    *,
    query: str,
    operation: str,
    duration_ms: float,
    rows: int | None,
    transaction_id: str,
    repository: str,
    error: BaseException | None = None,
) -> None:
    """Record a parameter-free SQL observation without changing execution semantics."""

    if not _config.enabled:
        return
    fields: dict[str, object] = {
        "sql": query,
        "operation": operation,
        "duration_ms": round(duration_ms, 3),
        "transaction_id": transaction_id,
        "repository": repository,
    }
    if rows is not None:
        fields["rows"] = rows
    if error is not None:
        log_exception(
            logger,
            "repository query failed",
            event=LogEvent.REPOSITORY_QUERY_FAILED,
            outcome=LogOutcome.FAILED,
            error=error,
            **fields,
        )
        return
    if duration_ms >= _config.slow_ms:
        log_event(
            logger,
            logging.WARNING,
            "repository query was slow",
            event=LogEvent.REPOSITORY_QUERY_SLOW,
            outcome=LogOutcome.SUCCESS,
            **fields,
        )
        return
    log_event(
        logger,
        logging.DEBUG,
        "repository query completed",
        event=LogEvent.REPOSITORY_QUERY_EXECUTED,
        outcome=LogOutcome.SUCCESS,
        **fields,
    )
