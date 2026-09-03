from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Protocol

from app.observability.config import LoggingConfig, build_logging_config, prepare_log_directory
from app.observability.context import OPERATION_FIELDS, get_operation_context
from app.observability.formatters import ConsoleFormatter, JsonLineFormatter
from app.observability.sql import configure_sql_observability

_HANDLER_MARKER = "_project_forge_observability_handler"
_SQL_LOGGER_NAME = "app.sql"


class LoggingSettings(Protocol):
    app_env: Any
    log_root: Path
    log_instance_id: str
    log_level: str
    log_max_bytes: int
    log_backup_count: int
    log_sql_enabled: bool
    log_sql_slow_ms: float


def configure_logging(settings: LoggingSettings, *, domain: str) -> LoggingConfig:
    environment = getattr(settings.app_env, "value", settings.app_env)
    config = build_logging_config(
        domain=domain,
        instance=settings.log_instance_id,
        root=settings.log_root,
        environment=str(environment),
        level=settings.log_level,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
        sql_enabled=settings.log_sql_enabled,
        sql_slow_ms=settings.log_sql_slow_ms,
    )
    directory = prepare_log_directory(config)
    application_logger = logging.getLogger("app")
    identity = (
        config.domain,
        config.instance,
        str(directory),
        config.level,
        config.max_bytes,
        config.backup_count,
        config.sql_enabled,
        config.sql_slow_ms,
    )
    if (
        getattr(application_logger, "_project_forge_observability_identity", None)
        == identity
        and any(_is_owned(handler) for handler in application_logger.handlers)
    ):
        return config
    _remove_owned_handlers(application_logger)
    handlers: list[logging.Handler] = []
    console = logging.StreamHandler()
    console.setFormatter(ConsoleFormatter())
    console.addFilter(_StructuredContextFilter(config))
    console.addFilter(_ConsoleFilter(config.level))
    handlers.append(console)
    handlers.append(
        _file_handler(
            directory / "business.log",
            config,
            _BusinessFilter(config.level),
        )
    )
    handlers.append(
        _file_handler(directory / "debug.log", config, _DebugFilter(config.level))
    )
    handlers.append(_file_handler(directory / "error.log", config, _ErrorFilter()))
    if config.sql_enabled:
        handlers.append(_file_handler(directory / "sql.log", config, _SqlFilter()))
    for handler in handlers:
        setattr(handler, _HANDLER_MARKER, True)
        application_logger.addHandler(handler)
    application_logger.setLevel(logging.DEBUG)
    application_logger.propagate = False
    application_logger.__dict__["_project_forge_observability_identity"] = identity
    configure_sql_observability(enabled=config.sql_enabled, slow_ms=config.sql_slow_ms)
    return config


def shutdown_logging() -> None:
    logger = logging.getLogger("app")
    _remove_owned_handlers(logger)
    logger.__dict__["_project_forge_observability_identity"] = None
    configure_sql_observability(enabled=False, slow_ms=200.0)


def _file_handler(
    path: Path, config: LoggingConfig, route_filter: logging.Filter
) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(JsonLineFormatter())
    handler.addFilter(_StructuredContextFilter(config))
    handler.addFilter(route_filter)
    return handler


def _is_sql(record: logging.LogRecord) -> bool:
    return record.name == _SQL_LOGGER_NAME or record.name.startswith(f"{_SQL_LOGGER_NAME}.")


def _is_owned(handler: logging.Handler) -> bool:
    return bool(getattr(handler, _HANDLER_MARKER, False))


def _remove_owned_handlers(logger: logging.Logger) -> None:
    for handler in tuple(logger.handlers):
        if _is_owned(handler):
            logger.removeHandler(handler)
            handler.close()


class _StructuredContextFilter(logging.Filter):
    def __init__(self, config: LoggingConfig) -> None:
        super().__init__()
        self._config = config

    def filter(self, record: logging.LogRecord) -> bool:
        record.domain = self._config.domain
        record.instance = self._config.instance
        record.environment = self._config.environment
        record.pid = os.getpid()
        for field in OPERATION_FIELDS:
            value = get_operation_context().get(field)
            if value is not None and (
                not hasattr(record, field) or getattr(record, field) is None
            ):
                setattr(record, field, value)
        return True


class _ConsoleFilter(logging.Filter):
    def __init__(self, configured_level: int) -> None:
        super().__init__()
        self._minimum = min(configured_level, logging.WARNING)

    def filter(self, record: logging.LogRecord) -> bool:
        return not _is_sql(record) and record.levelno >= self._minimum


class _BusinessFilter(logging.Filter):
    def __init__(self, configured_level: int) -> None:
        super().__init__()
        self._minimum = max(logging.INFO, min(configured_level, logging.WARNING))

    def filter(self, record: logging.LogRecord) -> bool:
        return not _is_sql(record) and record.levelno >= self._minimum


class _DebugFilter(logging.Filter):
    def __init__(self, configured_level: int) -> None:
        super().__init__()
        self._enabled = configured_level <= logging.DEBUG

    def filter(self, record: logging.LogRecord) -> bool:
        return self._enabled and not _is_sql(record) and record.levelno == logging.DEBUG


class _ErrorFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING


class _SqlFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return _is_sql(record)
