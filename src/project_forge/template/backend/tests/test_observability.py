from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

import app.api.observability as api_observability
from app.observability import (
    LogEvent,
    LogOutcome,
    build_logging_config,
    configure_logging,
    current_request_id,
    get_operation_context,
    log_event,
    log_exception,
    operation_context,
    shutdown_logging,
)
from app.observability.config import prepare_log_directory
from app.observability.formatters import (
    MAX_COLLECTION_ITEMS,
    MAX_LOG_LINE_BYTES,
    ConsoleFormatter,
    JsonLineFormatter,
)
from app.observability.sql import configure_sql_observability, record_sql_query


@pytest.fixture(autouse=True)
def reset_application_logging() -> None:
    shutdown_logging()
    yield
    shutdown_logging()


def _config(tmp_path: Path, **overrides: object) -> object:
    values: dict[str, object] = {
        "domain": "api",
        "instance": "instance-1",
        "root": tmp_path,
        "environment": "test",
        "level": "DEBUG",
        "max_bytes": 1_000_000,
        "backup_count": 2,
        "sql_enabled": True,
        "sql_slow_ms": 10.0,
    }
    values.update(overrides)
    return build_logging_config(**values)  # type: ignore[arg-type]


def _settings(tmp_path: Path, **overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "app_env": SimpleNamespace(value="test"),
        "log_root": tmp_path,
        "log_instance_id": "instance-1",
        "log_level": "DEBUG",
        "log_max_bytes": 1_000_000,
        "log_backup_count": 2,
        "log_sql_enabled": True,
        "log_sql_slow_ms": 10.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _read_json_lines(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_logging_configuration_normalizes_safe_values(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        domain=" Event-Relay ",
        instance="worker_1.local",
        environment=" ",
        level="info",
        root=str(tmp_path / "nested"),
        sql_slow_ms=12,
    )

    assert config.domain == "event-relay"
    assert config.instance == "worker_1.local"
    assert config.environment == "unknown"
    assert config.level == logging.INFO
    assert config.level_name == "INFO"
    assert config.sql_slow_ms == 12.0
    assert config.directory == tmp_path / "nested" / "event-relay" / "worker_1.local"
    assert prepare_log_directory(config) == config.directory.absolute()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"domain": "API worker"}, "domain"),
        ({"domain": "a" * 65}, "domain"),
        ({"instance": "worker/1"}, "instance"),
        ({"level": "TRACE"}, "log level"),
        ({"max_bytes": 0}, "max bytes"),
        ({"backup_count": 0}, "backup count"),
        ({"sql_slow_ms": -1}, "slow threshold"),
    ],
)
def test_logging_configuration_rejects_unsafe_values(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _config(tmp_path, **overrides)


def test_logging_paths_reject_links_and_non_files(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    linked_root = tmp_path / "linked"
    try:
        linked_root.symlink_to(real_root, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")

    with pytest.raises(ValueError, match="symlinks or junctions"):
        prepare_log_directory(_config(tmp_path, root=linked_root))

    config = _config(tmp_path, root=tmp_path / "regular")
    config.directory.mkdir(parents=True)
    (config.directory / "error.log").mkdir()
    with pytest.raises(ValueError, match="regular file"):
        prepare_log_directory(config)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_logging_paths_reject_windows_junctions(tmp_path: Path) -> None:
    target = tmp_path / "junction-target"
    target.mkdir()
    junction = tmp_path / "junction"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:
        pytest.skip("junction creation is unavailable")
    try:
        with pytest.raises(ValueError, match="symlinks or junctions"):
            prepare_log_directory(_config(tmp_path, root=junction))
    finally:
        os.rmdir(junction)


def test_context_is_nested_and_task_local() -> None:
    assert get_operation_context() == {}
    assert current_request_id() is None
    with operation_context(request_id="request-1", actor_id=uuid4()):
        actor_id = get_operation_context()["actor_id"]
        assert current_request_id() == "request-1"
        with operation_context(operation_id="operation-1", request_id=""):
            assert get_operation_context() == {
                "request_id": "request-1",
                "actor_id": actor_id,
                "operation_id": "operation-1",
            }
        assert "operation_id" not in get_operation_context()
    assert get_operation_context() == {}


def test_rotated_files_are_isolated_routed_and_redacted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    sentinel = logging.NullHandler()
    application_logger = logging.getLogger("app")
    application_logger.addHandler(sentinel)
    try:
        config = configure_logging(settings, domain="api")
        owned_count = len(application_logger.handlers)
        assert configure_logging(settings, domain="api") == config
        assert len(application_logger.handlers) == owned_count

        service_logger = logging.getLogger("app.services.example")
        with operation_context(
            request_id="request-1",
            operation_id="operation-1",
            correlation_id="correlation-1",
            causation_id="causation-1",
            actor_id="actor-1",
            workspace_id="workspace-1",
            event_id="event-1",
            message_id="message-1",
        ):
            log_event(
                service_logger,
                logging.DEBUG,
                "service diagnostic",
                event="service.example.inspected",
                outcome=LogOutcome.SUCCESS,
            )
            log_event(
                service_logger,
                logging.INFO,
                "service operation completed",
                event="service.example.completed",
                outcome=LogOutcome.SUCCESS,
                api_token="never-write-token",
                metadata={
                    "password": "never-write-password",
                    "requestHeaders": "never-write-header",
                    "safe": "value",
                },
            )
            service_logger.warning(
                "service capacity warning",
                extra={"event": "service.capacity.warning", "outcome": "unknown"},
            )
            try:
                raise RuntimeError("never-write-exception-value")
            except RuntimeError as error:
                log_exception(
                    service_logger,
                    "service operation failed",
                    event="service.example.failed",
                    error=error,
                )

        record_sql_query(
            query="SELECT item_id FROM items WHERE workspace_id = %(workspace_id)s",
            operation="select",
            duration_ms=1.0,
            rows=1,
            transaction_id="transaction-1",
            repository="items",
        )
        record_sql_query(
            query="UPDATE items SET status = %(status)s",
            operation="update",
            duration_ms=11.0,
            rows=2,
            transaction_id="transaction-1",
            repository="items",
        )
        sql_error = RuntimeError("never-write-database-value")
        record_sql_query(
            query="DELETE FROM items WHERE item_id = %(item_id)s",
            operation="delete",
            duration_ms=2.0,
            rows=None,
            transaction_id="transaction-1",
            repository="items",
            error=sql_error,
        )
        shutdown_logging()
    finally:
        application_logger.removeHandler(sentinel)

    directory = tmp_path / "api" / "instance-1"
    business = _read_json_lines(directory / "business.log")
    debug = _read_json_lines(directory / "debug.log")
    errors = _read_json_lines(directory / "error.log")
    queries = _read_json_lines(directory / "sql.log")

    assert {entry["event"] for entry in business} == {
        "service.example.completed",
        "service.capacity.warning",
        "service.example.failed",
    }
    assert [entry["event"] for entry in debug] == ["service.example.inspected"]
    assert {entry["event"] for entry in queries} == {
        LogEvent.REPOSITORY_QUERY_EXECUTED,
        LogEvent.REPOSITORY_QUERY_SLOW,
        LogEvent.REPOSITORY_QUERY_FAILED,
    }
    assert LogEvent.REPOSITORY_QUERY_SLOW in {entry["event"] for entry in errors}
    assert LogEvent.REPOSITORY_QUERY_FAILED in {entry["event"] for entry in errors}
    completed = next(
        entry for entry in business if entry["event"] == "service.example.completed"
    )
    assert completed["domain"] == "api"
    assert completed["instance"] == "instance-1"
    assert completed["environment"] == "test"
    assert completed["request_id"] == "request-1"
    assert completed["api_token"] == "[REDACTED]"
    assert completed["metadata"] == {
        "password": "[REDACTED]",
        "requestHeaders": "[REDACTED]",
        "safe": "value",
    }
    assert all("workspace-1" not in json.dumps(entry) for entry in queries)

    combined_files = "".join(
        path.read_text(encoding="utf-8") for path in directory.glob("*.log")
    )
    console = capsys.readouterr().err
    for secret in (
        "never-write-token",
        "never-write-password",
        "never-write-header",
        "never-write-exception-value",
        "never-write-database-value",
    ):
        assert secret not in combined_files
        assert secret not in console
    assert "SELECT item_id" not in console
    assert "service operation completed" in console


def test_rotation_and_instance_directories_do_not_cross_write(tmp_path: Path) -> None:
    first = _settings(
        tmp_path,
        log_instance_id="instance-a",
        log_max_bytes=300,
        log_sql_enabled=False,
    )
    configure_logging(first, domain="worker")
    logger = logging.getLogger("app.workers.example")
    for index in range(12):
        log_event(
            logger,
            logging.INFO,
            "rotating worker record",
            event="worker.example.completed",
            outcome=LogOutcome.SUCCESS,
            record_index=index,
        )
    first_directory = tmp_path / "worker" / "instance-a"
    assert (first_directory / "business.log.1").exists()
    assert not (first_directory / "sql.log").exists()

    second = _settings(tmp_path, log_instance_id="instance-b", log_sql_enabled=False)
    configure_logging(second, domain="worker")
    log_event(
        logger,
        logging.INFO,
        "second instance record",
        event="worker.example.completed",
        outcome=LogOutcome.SUCCESS,
    )
    record_sql_query(
        query="SELECT 1",
        operation="select",
        duration_ms=1,
        rows=1,
        transaction_id="transaction-2",
        repository="health",
    )
    shutdown_logging()

    assert "second instance record" not in (
        first_directory / "business.log"
    ).read_text(encoding="utf-8")
    second_directory = tmp_path / "worker" / "instance-b"
    assert "second instance record" in (
        second_directory / "business.log"
    ).read_text(encoding="utf-8")
    assert not (second_directory / "sql.log").exists()


class _ExampleEnum(StrEnum):
    VALUE = "value"


class _ExampleModel:
    def model_dump(self, *, mode: str) -> dict[str, str]:
        assert mode == "json"
        return {"accessToken": "secret", "safe": "model"}


def test_formatters_bound_values_collections_and_exceptions() -> None:
    record = logging.LogRecord(
        name="app.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="bounded record",
        args=(),
        exc_info=None,
    )
    record.domain = "api"
    record.instance = "instance-1"
    record.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    record.identifier = uuid4()
    record.path = Path("safe/path")
    record.enum_value = _ExampleEnum.VALUE
    record.model = _ExampleModel()
    record.unknown = object()
    record.long_value = "x" * 3_000
    record.items = list(range(MAX_COLLECTION_ITEMS + 1))
    record.deep = {"one": {"two": {"three": {"four": "limited"}}}}
    for index in range(40):
        setattr(record, f"zlarge_{index:02d}", "y" * 3_000)
    try:
        raise RuntimeError("never-format-this-value")
    except RuntimeError:
        record.exc_info = sys.exc_info()

    rendered = JsonLineFormatter().format(record)
    payload = json.loads(rendered)
    assert len(rendered.encode("utf-8")) <= MAX_LOG_LINE_BYTES
    assert payload["created_at"] == "2026-01-01T00:00:00+00:00"
    assert payload["enum_value"] == "value"
    assert payload["model"] == {"accessToken": "[REDACTED]", "safe": "model"}
    assert payload["unknown"] == "<object>"
    assert payload["long_value"].endswith("…")
    assert payload["items"][-1] == "[ITEM_LIMIT]"
    assert payload["deep"]["one"]["two"]["three"]["four"] == "[DEPTH_LIMIT]"
    assert payload["fields_truncated"] is True
    assert "never-format-this-value" not in rendered

    console = ConsoleFormatter().format(record)
    assert "[api/instance-1]" in console
    assert "exception=RuntimeError" in console
    assert "never-format-this-value" not in console


def test_event_helpers_reject_unstable_fields_and_preserve_safe_exception_type() -> None:
    logger = Mock(spec=logging.Logger)
    log_event(
        logger,
        logging.INFO,
        "operation completed",
        event="example.operation.completed",
        outcome=LogOutcome.SUCCESS,
        entity_id="entity-1",
        omitted=None,
    )
    extra = logger.log.call_args.kwargs["extra"]
    assert extra == {
        "event": "example.operation.completed",
        "event_domain": "example",
        "outcome": "success",
        "entity_id": "entity-1",
    }

    with pytest.raises(ValueError, match="stable lowercase"):
        log_event(logger, logging.INFO, "bad", event="bad", outcome="unknown")
    with pytest.raises(ValueError, match="supported stable value"):
        log_event(
            logger,
            logging.INFO,
            "bad",
            event="example.bad",
            outcome="sometimes",
        )
    with pytest.raises(ValueError, match="invalid structured log field"):
        log_event(
            logger,
            logging.INFO,
            "bad",
            event="example.bad",
            outcome="unknown",
            **{"Bad-Field": 1},
        )
    with pytest.raises(ValueError, match="runtime-owned"):
        log_event(
            logger,
            logging.INFO,
            "bad",
            event="example.bad",
            outcome="unknown",
            domain="caller-owned",
        )

    error = RuntimeError("private exception value")
    log_exception(
        logger,
        "operation failed",
        event="example.operation.failed",
        error=error,
    )
    exception_call = logger.error.call_args
    assert exception_call.kwargs["extra"]["error_type"] == "RuntimeError"
    assert exception_call.kwargs["extra"]["exception"]["type"] == "RuntimeError"
    assert "exc_info" not in exception_call.kwargs

    with pytest.raises(ValueError, match="stable lowercase"):
        log_exception(logger, "bad", event="bad", error=error)
    with pytest.raises(ValueError, match="supported stable value"):
        log_exception(
            logger,
            "bad",
            event="example.bad",
            outcome="sometimes",
            error=error,
        )
    with pytest.raises(ValueError, match="invalid structured log field"):
        log_exception(
            logger,
            "bad",
            event="example.bad",
            error=error,
            **{"Bad-Field": 1},
        )


def test_http_observability_classifies_rejections_and_server_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[int, object, dict[str, object]]] = []
    failures: list[dict[str, object]] = []

    def capture_event(
        _logger: logging.Logger,
        level: int,
        _message: str,
        *,
        event: object,
        outcome: object,
        **fields: object,
    ) -> None:
        events.append((level, outcome, {"event": event, **fields}))

    def capture_failure(*_: object, **fields: object) -> None:
        failures.append(fields)

    monkeypatch.setattr(api_observability, "log_event", capture_event)
    monkeypatch.setattr(api_observability, "log_exception", capture_failure)
    application = FastAPI()
    application.add_middleware(api_observability.RequestContextMiddleware)

    @application.get("/unavailable")
    async def unavailable() -> Response:
        return Response(status_code=503)

    @application.get("/boom")
    async def boom() -> None:
        raise RuntimeError("private failure")

    client = TestClient(application, raise_server_exceptions=False)
    missing = client.get("/missing")
    unavailable_response = client.get("/unavailable")
    failed = client.get("/boom")

    assert missing.status_code == 404
    assert unavailable_response.status_code == 503
    assert failed.status_code == 500
    assert events[0][0:2] == (logging.INFO, LogOutcome.REJECTED)
    assert events[1][0:2] == (logging.ERROR, LogOutcome.FAILED)
    assert events[0][2]["status"] == 404
    assert events[1][2]["status"] == 503
    assert failures[0]["event"] == LogEvent.HTTP_REQUEST_FAILED
    assert failures[0]["status"] == 500


def test_sql_observability_can_be_disabled() -> None:
    logger = logging.getLogger("app.sql")
    handler = Mock(spec=logging.Handler)
    logger.addHandler(handler)
    try:
        configure_sql_observability(enabled=False, slow_ms=1)
        record_sql_query(
            query="SELECT 1",
            operation="select",
            duration_ms=10,
            rows=1,
            transaction_id="transaction-3",
            repository="health",
        )
        assert not handler.handle.called
    finally:
        logger.removeHandler(handler)
