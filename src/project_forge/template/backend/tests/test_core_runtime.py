from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from types import TracebackType
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import BaseModel
from typer.testing import CliRunner

from app.api.errors import install_error_handlers
from app.api.observability import JsonLogFormatter, current_request_id
from app.cli import app as cli_app
from app.db.query import SqlPredicateBuilder, escape_like
from app.db.repository_connection import PsycopgRepositoryConnection
from app.db.types import DbConnection, DbPool
from app.domain.base import StrictDomainModel, to_camel
from app.main import app
from app.services.health import HealthService
from app.uow.factory import UnitOfWorkFactory
from app.uow.unit import UnitOfWork


def test_sql_predicate_builder_covers_safe_composition_and_validation() -> None:
    empty_predicate, empty_parameters = SqlPredicateBuilder().build()
    assert empty_predicate.as_string() == "TRUE"
    assert empty_parameters == {}

    builder = SqlPredicateBuilder()
    builder.add(sql.SQL("enabled = %(enabled)s"), {"enabled": True})
    builder.add_equals(sql.Identifier("status"), "status", "ACTIVE")
    builder.add_greater_than_or_equal(sql.Identifier("created_at"), "created_after", 10)
    builder.add_is_null(sql.Identifier("deleted_at"))
    builder.add_ilike_contains(sql.Identifier("name"), "name_pattern", r"50%_off\today")
    builder.add_any(sql.Identifier("kind"), "kinds", ["A", "B"])

    predicate, parameters = builder.build()
    rendered = predicate.as_string()
    assert rendered.startswith("enabled = %(enabled)s AND")
    assert '"status" = %(status)s' in rendered
    assert '"created_at" >= %(created_after)s' in rendered
    assert '"deleted_at" IS NULL' in rendered
    assert '"name" ILIKE %(name_pattern)s' in rendered
    assert '"kind" = ANY(%(kinds)s)' in rendered
    assert parameters == {
        "enabled": True,
        "status": "ACTIVE",
        "created_after": 10,
        "name_pattern": r"%50\%\_off\\today%",
        "kinds": ["A", "B"],
    }

    with pytest.raises(ValueError, match="one character"):
        escape_like("value", "!!")
    with pytest.raises(TypeError, match="Composable"):
        SqlPredicateBuilder().add("unsafe")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid parameter name"):
        SqlPredicateBuilder().add(sql.SQL("TRUE"), {"not-safe": True})
    with pytest.raises(ValueError, match="must be descriptive"):
        SqlPredicateBuilder().add_equals(sql.Identifier("status"), "p1", "ACTIVE")
    with pytest.raises(ValueError, match="conflicting SQL parameter"):
        builder.add(sql.SQL("TRUE"), {"status": "ARCHIVED"})

    reused = SqlPredicateBuilder()
    reused.add_equals(sql.Identifier("created_at"), "cutoff", 10)
    reused.add_greater_than_or_equal(sql.Identifier("updated_at"), "cutoff", 10)
    reused_predicate, reused_parameters = reused.build()
    assert reused_predicate.as_string().count("%(cutoff)s") == 2
    assert reused_parameters == {"cutoff": 10}


class ExampleDomainModel(StrictDomainModel):
    display_name: str


class CredentialsPayload(BaseModel):
    password: int


def test_domain_base_enforces_aliases_and_normalization() -> None:
    assert to_camel("created_at") == "createdAt"
    model = ExampleDomainModel.model_validate({"displayName": "  Example  "})
    assert model.display_name == "Example"
    assert model.model_dump(by_alias=True) == {"displayName": "Example"}
    with pytest.raises(ValueError, match="Extra inputs"):
        ExampleDomainModel.model_validate({"displayName": "Example", "unknown": True})


class FakeTransaction:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False
        self.exit_error: type[BaseException] | None = None

    async def __aenter__(self) -> FakeTransaction:
        self.entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        self.exited = True
        self.exit_error = exc_type


class FakeConnection:
    def __init__(self) -> None:
        self.transaction_context = FakeTransaction()

    def transaction(self) -> FakeTransaction:
        return self.transaction_context


class FakeConnectionContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> DbConnection:
        self.entered = True
        return cast(DbConnection, self.connection)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.exited = True


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection_context = FakeConnectionContext(connection)

    def connection(self) -> FakeConnectionContext:
        return self.connection_context


class FakeCopy:
    def __init__(self) -> None:
        self.rows: list[tuple[object, ...]] = []

    async def __aenter__(self) -> FakeCopy:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def write_row(self, row: Sequence[object]) -> None:
        self.rows.append(tuple(row))


class FakeRepositoryCursor:
    def __init__(self) -> None:
        self.rowcount = 0
        self.executemany_calls = 0
        self.parameter_sets: list[dict[str, object]] = []
        self.copy_context = FakeCopy()
        self.fetchone_result: Mapping[str, object] | None = {"value": 1}
        self.fetchall_result: list[Mapping[str, object]] = [{"value": 1}, {"value": 2}]
        self.execute_calls: list[tuple[object, object | None, bool | None]] = []

    async def __aenter__(self) -> FakeRepositoryCursor:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def executemany(
        self, query: object, parameter_sets: Iterable[Mapping[str, object]]
    ) -> None:
        del query
        self.executemany_calls += 1
        self.parameter_sets = [dict(parameters) for parameters in parameter_sets]
        self.rowcount = len(self.parameter_sets)

    async def execute(
        self,
        query: object,
        parameters: object | None = None,
        *,
        prepare: bool | None = None,
    ) -> None:
        self.execute_calls.append((query, parameters, prepare))
        self.rowcount = 1

    async def fetchone(self) -> Mapping[str, object] | None:
        return self.fetchone_result

    async def fetchall(self) -> list[Mapping[str, object]]:
        return self.fetchall_result

    def copy(self, query: object) -> FakeCopy:
        del query
        return self.copy_context


class FakeRepositoryConnection:
    def __init__(self) -> None:
        self.cursor_context = FakeRepositoryCursor()

    def cursor(self) -> FakeRepositoryCursor:
        return self.cursor_context


@pytest.mark.asyncio
async def test_repository_connection_batches_named_mappings_and_copy_rows() -> None:
    raw_connection = FakeRepositoryConnection()
    owner = asyncio.current_task()
    if owner is None:
        raise RuntimeError("test requires an asyncio task")
    connection = PsycopgRepositoryConnection(
        cast(DbConnection, raw_connection), owner
    )
    query = sql.SQL(
        "INSERT INTO examples (example_id) VALUES (%(example_id)s)"
    )

    assert await connection.execute(query, {"example_id": 1}, prepare=True) == 1
    assert await connection.fetch_one(query, {"example_id": 1}, prepare=False) == {
        "value": 1
    }
    assert await connection.fetch_all(query, prepare=True) == (
        {"value": 1},
        {"value": 2},
    )

    assert await connection.execute_many(query, []) == 0
    assert raw_connection.cursor_context.executemany_calls == 0
    assert await connection.execute_many(
        query,
        ({"example_id": example_id} for example_id in (1, 2)),
    ) == 2
    assert raw_connection.cursor_context.parameter_sets == [
        {"example_id": 1},
        {"example_id": 2},
    ]

    with pytest.raises(TypeError, match="must be mappings"):
        await connection.execute_many(query, [(3,)])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="must be mappings"):
        await connection.execute_many(
            query,
            [{"example_id": 3}, (4,)],  # type: ignore[list-item]
        )

    copy_query = sql.SQL("COPY examples (example_id) FROM STDIN")
    assert await connection.copy_rows(copy_query, []) == 0
    assert await connection.copy_rows(copy_query, [(4,), (5,)]) == 2
    assert raw_connection.cursor_context.copy_context.rows == [(4,), (5,)]

    async def async_rows() -> AsyncIterator[tuple[object, ...]]:
        yield (6,)

    assert await connection.copy_rows(copy_query, async_rows()) == 1
    assert raw_connection.cursor_context.copy_context.rows == [(4,), (5,), (6,)]

    async def empty_async_rows() -> AsyncIterator[tuple[object, ...]]:
        if False:
            yield ()

    assert await connection.copy_rows(copy_query, empty_async_rows()) == 0

    connection.finish()
    with pytest.raises(RuntimeError, match="no longer active"):
        await connection.execute_many(query, [{"example_id": 7}])


@pytest.mark.asyncio
async def test_unit_of_work_is_single_use_and_task_owned() -> None:
    connection = FakeConnection()
    pool = FakePool(connection)
    unit_of_work = UnitOfWork(cast(DbPool, pool))

    with pytest.raises(RuntimeError, match="not active"):
        unit_of_work.assert_owner()

    async with unit_of_work as active:
        assert active is unit_of_work
        assert pool.connection_context.entered is True
        assert connection.transaction_context.entered is True
        active.assert_owner()
        health = active.health
        assert active.health is health

        async def assert_from_another_task() -> None:
            with pytest.raises(RuntimeError, match="task boundaries"):
                active.assert_owner()
            with pytest.raises(RuntimeError, match="task boundaries"):
                await health.connection.execute(sql.SQL("SELECT 1"), prepare=True)

        await asyncio.create_task(assert_from_another_task())

    assert connection.transaction_context.exited is True
    assert pool.connection_context.exited is True
    with pytest.raises(RuntimeError, match="no longer active"):
        await health.connection.execute(sql.SQL("SELECT 1"), prepare=True)
    with pytest.raises(RuntimeError, match="single-use"):
        await unit_of_work.__aenter__()


@pytest.mark.asyncio
async def test_unit_of_work_factory_owns_connection_and_transaction() -> None:
    connection = FakeConnection()
    pool = FakePool(connection)
    factory = UnitOfWorkFactory(cast(DbPool, pool))

    async with factory() as unit_of_work:
        unit_of_work.assert_owner()
        assert connection.transaction_context.entered is True

    assert connection.transaction_context.exited is True
    assert pool.connection_context.exited is True


@pytest.mark.asyncio
async def test_unit_of_work_forwards_failures_to_transaction_rollback() -> None:
    connection = FakeConnection()
    factory = UnitOfWorkFactory(cast(DbPool, FakePool(connection)))

    with pytest.raises(ValueError, match="rollback"):
        async with factory():
            raise ValueError("rollback")

    assert connection.transaction_context.exit_error is ValueError


class FakeHealthRepository:
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    async def is_ready(self) -> bool:
        return self._ready


class FakeHealthContext:
    def __init__(self, ready: bool, *, fail: bool = False) -> None:
        self.health = FakeHealthRepository(ready)
        self._fail = fail

    async def __aenter__(self) -> FakeHealthContext:
        if self._fail:
            raise ConnectionError("database unavailable")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback


class FakeHealthFactory:
    def __init__(self, ready: bool, *, fail: bool = False) -> None:
        self._ready = ready
        self._fail = fail

    def __call__(self) -> FakeHealthContext:
        return FakeHealthContext(self._ready, fail=self._fail)


@pytest.mark.asyncio
async def test_health_service_preserves_the_infrastructure_failure_boundary() -> None:
    ready_service = HealthService(cast(UnitOfWorkFactory, FakeHealthFactory(True)))
    failed_service = HealthService(cast(UnitOfWorkFactory, FakeHealthFactory(False, fail=True)))

    assert await ready_service.is_ready() is True
    assert await failed_service.is_ready() is False


def test_http_boundary_adds_request_ids_and_safe_errors() -> None:
    live = TestClient(app).get("/health/live", headers={"X-Request-ID": "request-123"})
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert live.headers["X-Request-ID"] == "request-123"
    assert current_request_id() is None

    boundary = FastAPI()
    install_error_handlers(boundary)

    @boundary.post("/plain")
    async def plain(_: CredentialsPayload) -> dict[str, bool]:
        return {"ok": True}

    @boundary.post("/api/v1/workspaces")
    async def auth_related(_: CredentialsPayload) -> dict[str, bool]:
        return {"ok": True}

    @boundary.get("/forbidden")
    async def forbidden() -> None:
        raise PermissionError("access denied")

    client = TestClient(boundary)
    plain_response = client.post("/plain", json={"password": "do-not-log"})
    assert plain_response.status_code == 422
    assert "do-not-log" not in plain_response.text
    assert "[redacted]" in plain_response.text

    auth_response = client.post(
        "/api/v1/workspaces", json={"password": "do-not-log"}
    )
    assert auth_response.status_code == 422
    assert auth_response.json() == {
        "code": "request_validation_failed",
        "message": "request validation failed",
    }
    assert auth_response.headers["Cache-Control"] == "no-store"

    forbidden_response = client.get("/forbidden")
    assert forbidden_response.status_code == 403
    assert forbidden_response.json() == {"code": "forbidden", "message": "access denied"}


def test_json_log_formatter_emits_structured_safe_fields() -> None:
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="completed",
        args=(),
        exc_info=None,
    )
    record.event = "test_completed"
    record.request_id = "request-123"

    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["message"] == "completed"
    assert payload["event"] == "test_completed"
    assert payload["request_id"] == "request-123"


def test_config_cli_reports_valid_and_redacted_invalid_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = CliRunner().invoke(cli_app, ["config", "check", "--json"])
    assert valid.exit_code == 0
    assert json.loads(valid.stdout)["database_configured"] is True

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    invalid = CliRunner().invoke(cli_app, ["config", "check", "--json"])
    assert invalid.exit_code == 2
    payload = json.loads(invalid.stdout)
    assert payload["ok"] is False
    assert payload["errors"]
    assert "postgresql://" not in invalid.stdout
