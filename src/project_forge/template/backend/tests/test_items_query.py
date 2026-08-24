import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from app.db.migration_engine import MigrationRunner
from app.db.query import SqlPredicateBuilder, escape_like
from app.db.registry import MIGRATIONS
from app.domain.items import UNSET, ItemFilter, ItemSort, ItemStatus
from app.repositories.items import build_item_list_query


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


def test_builder_rejects_duplicate_or_invalid_parameter_names() -> None:
    builder = SqlPredicateBuilder()
    builder.add_equals(sql.Identifier("status"), "status", "ACTIVE")
    with pytest.raises(ValueError, match="duplicate SQL parameter"):
        builder.add_equals(sql.Identifier("other_status"), "status", "ARCHIVED")
    with pytest.raises(ValueError, match="invalid parameter name"):
        SqlPredicateBuilder().add_equals(sql.Identifier("status"), "not-safe", "ACTIVE")
    with pytest.raises(TypeError, match=r"psycopg\.sql\.Composable"):
        SqlPredicateBuilder().add("status = 'ACTIVE'")  # type: ignore[arg-type]


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
