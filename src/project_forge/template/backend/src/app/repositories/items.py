from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from psycopg import sql

from app.db.query import SqlPredicateBuilder
from app.db.types import DbConnection
from app.domain.items import UNSET, Item, ItemFilter, ItemSort, ItemStatus

GET_BY_ID = sql.SQL(
    """
    SELECT item_id, workspace_id, name, description, status, version, created_at, updated_at
    FROM items
    WHERE item_id = %(item_id)s
      AND workspace_id IS NOT DISTINCT FROM %(workspace_id)s
    """
)

INSERT_ITEM = sql.SQL(
    """
    INSERT INTO items (
        item_id, workspace_id, name, description, status, version, created_at, updated_at
    ) VALUES (
        %(item_id)s, %(workspace_id)s, %(name)s, %(description)s,
        %(status)s, %(version)s, %(created_at)s, %(updated_at)s
    )
    RETURNING item_id, workspace_id, name, description, status, version, created_at, updated_at
    """
)

SORT_EXPRESSIONS: Mapping[ItemSort, sql.Composed] = {
    ItemSort.CREATED_DESC: sql.Identifier("created_at") + sql.SQL(" DESC"),
    ItemSort.CREATED_ASC: sql.Identifier("created_at") + sql.SQL(" ASC"),
    ItemSort.NAME_ASC: sql.Identifier("name") + sql.SQL(" ASC"),
    ItemSort.NAME_DESC: sql.Identifier("name") + sql.SQL(" DESC"),
}


def build_item_list_query(
    workspace_id: UUID | None, filters: ItemFilter
) -> tuple[sql.Composed, dict[str, object], bool]:
    """Build one safe ad-hoc search shape in canonical predicate order."""
    predicates = SqlPredicateBuilder()
    if workspace_id is None:
        predicates.add_is_null(sql.Identifier("workspace_id"))
    else:
        predicates.add_equals(sql.Identifier("workspace_id"), "workspace_id", workspace_id)

    if filters.name is not UNSET:
        if filters.name is None:
            predicates.add_is_null(sql.Identifier("name"))
        elif isinstance(filters.name, str):
            predicates.add_ilike_contains(sql.Identifier("name"), "name_pattern", filters.name)
    if filters.description is not UNSET:
        if filters.description is None:
            predicates.add_is_null(sql.Identifier("description"))
        elif isinstance(filters.description, str):
            predicates.add_ilike_contains(
                sql.Identifier("description"), "description_pattern", filters.description
            )
    if isinstance(filters.status, ItemStatus):
        predicates.add_equals(sql.Identifier("status"), "status", filters.status.value)
    if filters.created_after is not UNSET:
        predicates.add_greater_than_or_equal(
            sql.Identifier("created_at"), "created_after", filters.created_after
        )

    where_clause, parameters = predicates.build()
    parameters.update({"limit": filters.limit, "offset": filters.offset})
    ordering = SORT_EXPRESSIONS[filters.sort]
    query = (
        sql.SQL(
            "SELECT item_id, workspace_id, name, description, status, version, "
            "created_at, updated_at FROM items WHERE "
        )
        + where_clause
        + sql.SQL(" ORDER BY ")
        + ordering
        + sql.SQL(", item_id ASC LIMIT %(limit)s OFFSET %(offset)s")
    )
    # This search has an open-ended number of shapes. Avoid filling the driver's
    # prepared statement cache; fixed hot-path statements above are prepared.
    return query, parameters, False


class ItemRepository:
    def __init__(self, connection: DbConnection) -> None:
        self._connection = connection

    async def get(self, item_id: UUID, workspace_id: UUID | None) -> Item | None:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                GET_BY_ID, {"item_id": item_id, "workspace_id": workspace_id}, prepare=True
            )
            row = await cursor.fetchone()
        return Item.model_validate(row) if row else None

    async def add(self, item: Item) -> Item:
        values = item.model_dump(mode="python")
        values["status"] = item.status.value
        async with self._connection.cursor() as cursor:
            await cursor.execute(INSERT_ITEM, values, prepare=True)
            row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("INSERT did not return an item")
        return Item.model_validate(row)

    async def list(self, workspace_id: UUID | None, filters: ItemFilter) -> tuple[Item, ...]:
        query, parameters, prepare = build_item_list_query(workspace_id, filters)
        async with self._connection.cursor() as cursor:
            await cursor.execute(query, parameters, prepare=prepare)
            rows = await cursor.fetchall()
        return tuple(Item.model_validate(row) for row in rows)
