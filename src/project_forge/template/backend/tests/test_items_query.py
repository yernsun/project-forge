import asyncio
import json
import os
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from psycopg import AsyncConnection, sql
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

from app.db.migration_engine import MigrationRunner
from app.db.query import SqlPredicateBuilder, escape_like
from app.db.registry import MIGRATIONS
from app.db.repository_connection import PsycopgRepositoryConnection
from app.domain.items import UNSET, Item, ItemFilter, ItemSort, ItemStatus
from app.repositories.base import RepositoryConnection
from app.repositories.items import (
    INSERT_ITEMS,
    PostgresItemRepository,
    build_item_list_query,
)


def test_conditional_query_has_canonical_predicate_order() -> None:
    query, parameters, prepare = build_item_list_query(
        None,
        ItemFilter(
            name="alpha",
            description=None,
            status=ItemStatus.ACTIVE,
            created_after=datetime(2026, 1, 1, tzinfo=UTC),
            sort=ItemSort.NAME_ASC,
        ),
    )
    rendered = query.as_string()
    assert rendered.index('"name" ILIKE') < rendered.index('"description" IS NULL')
    assert rendered.index('"description" IS NULL') < rendered.index('"status" =')
    assert rendered.index('"status" =') < rendered.index('"created_at" >=')
    assert 'ORDER BY "name" ASC' in rendered
    assert parameters["name_pattern"] == "%alpha%"
    assert prepare is False


def test_unset_is_different_from_sql_null() -> None:
    unset_query, _, _ = build_item_list_query(None, ItemFilter(description=UNSET))
    null_query, _, _ = build_item_list_query(None, ItemFilter(description=None))
    assert '"description" IS NULL' not in unset_query.as_string()
    assert '"description" IS NULL' in null_query.as_string()

    null_name_query, _, _ = build_item_list_query(None, ItemFilter(name=None))
    assert '"name" IS NULL' in null_name_query.as_string()
    description_query, parameters, _ = build_item_list_query(
        None, ItemFilter(description="details")
    )
    assert '"description" ILIKE %(description_pattern)s' in description_query.as_string()
    assert parameters["description_pattern"] == "%details%"


def test_like_metacharacters_are_escaped() -> None:
    query, parameters, _ = build_item_list_query(None, ItemFilter(name=r"50%_off\today"))
    assert "ESCAPE '\\'" in query.as_string()
    assert parameters["name_pattern"] == r"%50\%\_off\\today%"
    assert escape_like("plain") == "plain"


def test_any_uses_one_array_parameter_and_empty_means_no_rows() -> None:
    populated = SqlPredicateBuilder()
    populated.add_any(sql.Identifier("status"), "statuses", ["ACTIVE", "ARCHIVED"])
    predicate, parameters = populated.build()
    assert predicate.as_string() == '"status" = ANY(%(statuses)s)'
    assert parameters == {"statuses": ["ACTIVE", "ARCHIVED"]}

    empty = SqlPredicateBuilder()
    empty.add_any(sql.Identifier("status"), "statuses", [])
    empty_predicate, empty_parameters = empty.build()
    assert empty_predicate.as_string() == predicate.as_string()
    assert empty_parameters == {"statuses": []}


def test_builder_reuses_equal_parameters_and_rejects_conflicts_or_invalid_names() -> None:
    builder = SqlPredicateBuilder()
    builder.add_equals(sql.Identifier("status"), "status", "ACTIVE")
    builder.add_equals(sql.Identifier("other_status"), "status", "ACTIVE")
    predicate, parameters = builder.build()
    assert predicate.as_string().count("%(status)s") == 2
    assert parameters == {"status": "ACTIVE"}
    with pytest.raises(ValueError, match="conflicting SQL parameter"):
        builder.add_equals(sql.Identifier("other_status"), "status", "ARCHIVED")
    with pytest.raises(ValueError, match="invalid parameter name"):
        SqlPredicateBuilder().add_equals(sql.Identifier("status"), "not-safe", "ACTIVE")
    with pytest.raises(TypeError, match=r"psycopg\.sql\.Composable"):
        SqlPredicateBuilder().add("status = 'ACTIVE'")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_item_repository_batches_named_parameter_mappings() -> None:
    connection = AsyncMock()
    connection.execute_many.return_value = 2
    repository = PostgresItemRepository(cast(RepositoryConnection, connection))
    now = datetime.now(UTC)
    items = (
        Item(
            item_id=uuid4(),
            name="first",
            status=ItemStatus.ACTIVE,
            version=1,
            created_at=now,
            updated_at=now,
        ),
        Item(
            item_id=uuid4(),
            name="second",
            status=ItemStatus.ARCHIVED,
            version=1,
            created_at=now,
            updated_at=now,
        ),
    )

    assert await repository.add_many(items) == 2
    query, parameter_sets = connection.execute_many.await_args.args
    assert query is INSERT_ITEMS
    assert [parameters["status"] for parameters in parameter_sets] == [
        "ACTIVE",
        "ARCHIVED",
    ]

    row = items[0].model_dump(mode="python")
    connection.fetch_one.side_effect = [row, None, row, None]
    assert await repository.get(items[0].item_id, None) == items[0]
    assert await repository.get(uuid4(), None) is None
    assert await repository.add(items[0]) == items[0]
    with pytest.raises(RuntimeError, match="did not return an item"):
        await repository.add(items[1])
    connection.fetch_all.return_value = [row]
    assert await repository.list(None, ItemFilter()) == (items[0],)


@pytest.mark.asyncio
async def test_representative_postgres_shape_uses_workspace_status_index() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    connection = await AsyncConnection.connect(database_url, row_factory=dict_row)
    try:
        await MigrationRunner(connection, MIGRATIONS).up()
        await connection.execute(sql.SQL("SET enable_seqscan = off"))
        query, parameters, _ = build_item_list_query(
            uuid4(), ItemFilter(status=ItemStatus.ACTIVE, sort=ItemSort.CREATED_DESC)
        )
        async with connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("EXPLAIN (FORMAT JSON) ") + query,
                parameters,
                prepare=False,
            )
            row = await cursor.fetchone()
        assert row is not None
        assert "idx_items_workspace_status" in json.dumps(row["QUERY PLAN"])
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_postgres_execute_many_and_copy_are_atomic() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    connection = await AsyncConnection.connect(database_url, row_factory=dict_row)
    owner = asyncio.current_task()
    if owner is None:
        raise RuntimeError("integration test requires an asyncio task")
    guarded = PsycopgRepositoryConnection(connection, owner)
    repository = PostgresItemRepository(guarded)
    now = datetime.now(UTC)

    def item(name: str) -> Item:
        return Item(
            item_id=uuid4(),
            name=name,
            status=ItemStatus.ACTIVE,
            version=1,
            created_at=now,
            updated_at=now,
        )

    async def count_rows(item_ids: list[object]) -> int:
        cursor = await connection.execute(
            sql.SQL(
                "SELECT count(*) AS count FROM items "
                "WHERE item_id = ANY(%(item_ids)s)"
            ),
            {"item_ids": item_ids},
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("item count query returned no row")
        return int(row["count"])

    inserted = (item("batch-one"), item("batch-two"))
    copied = (item("copy-one"), item("copy-two"))
    rollback_items = (item("rollback-one"), item("rollback-two"))
    duplicate_id = uuid4()
    cleanup_ids = [
        *(entry.item_id for entry in (*inserted, *copied, *rollback_items)),
        duplicate_id,
    ]
    try:
        await MigrationRunner(connection, MIGRATIONS).up()

        async with connection.transaction():
            assert await repository.add_many(inserted) == 2
        assert await count_rows([entry.item_id for entry in inserted]) == 2

        with pytest.raises(RuntimeError, match="force rollback"):
            async with connection.transaction():
                assert await repository.add_many(rollback_items) == 2
                raise RuntimeError("force rollback")
        assert await count_rows([entry.item_id for entry in rollback_items]) == 0

        copy_query = sql.SQL(
            "COPY items (item_id, workspace_id, name, description, status, version, "
            "created_at, updated_at) FROM STDIN"
        )
        copy_rows = [
            (
                entry.item_id,
                entry.workspace_id,
                entry.name,
                entry.description,
                entry.status.value,
                entry.version,
                entry.created_at,
                entry.updated_at,
            )
            for entry in copied
        ]
        async with connection.transaction():
            assert await guarded.copy_rows(copy_query, copy_rows) == 2
        assert await count_rows([entry.item_id for entry in copied]) == 2

        duplicate_rows = [
            (duplicate_id, None, "duplicate", None, "ACTIVE", 1, now, now),
            (duplicate_id, None, "duplicate", None, "ACTIVE", 1, now, now),
        ]
        with pytest.raises(UniqueViolation):
            async with connection.transaction():
                await guarded.copy_rows(copy_query, duplicate_rows)
        assert await count_rows([duplicate_id]) == 0
    finally:
        await connection.execute(
            sql.SQL("DELETE FROM items WHERE item_id = ANY(%(item_ids)s)"),
            {"item_ids": cleanup_ids},
        )
        await connection.commit()
        guarded.finish()
        await connection.close()
