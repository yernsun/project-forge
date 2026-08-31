from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol
from uuid import UUID

from psycopg import sql

from app.db.query import SqlPredicateBuilder
from app.domain.items import UNSET, Item, ItemFilter, ItemSort, ItemStatus
from app.repositories.base import BaseRepository

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

INSERT_ITEMS = sql.SQL(
    """
    INSERT INTO items (
        item_id, workspace_id, name, description, status, version, created_at, updated_at
    ) VALUES (
        %(item_id)s, %(workspace_id)s, %(name)s, %(description)s,
        %(status)s, %(version)s, %(created_at)s, %(updated_at)s
    )
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


def _item_values(item: Item) -> dict[str, object]:
    return {
        "item_id": item.item_id,
        "workspace_id": item.workspace_id,
        "name": item.name,
        "description": item.description,
        "status": item.status.value,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


class ItemRepository(BaseRepository, Protocol):
    """Persistence contract for the optional sample Item capability."""

    async def get(self, item_id: UUID, workspace_id: UUID | None) -> Item | None: ...

    async def add(self, item: Item) -> Item: ...

    async def add_many(self, items: Iterable[Item]) -> int: ...

    async def list(
        self, workspace_id: UUID | None, filters: ItemFilter
    ) -> tuple[Item, ...]: ...


class PostgresItemRepository(BaseRepository):
    """Psycopg implementation created only by UnitOfWork."""

    async def get(self, item_id: UUID, workspace_id: UUID | None) -> Item | None:
        row = await self.connection.fetch_one(
            GET_BY_ID,
            {"item_id": item_id, "workspace_id": workspace_id},
            prepare=True,
        )
        return Item.model_validate(row) if row else None

    async def add(self, item: Item) -> Item:
        row = await self.connection.fetch_one(
            INSERT_ITEM, _item_values(item), prepare=True
        )
        if row is None:
            raise RuntimeError("INSERT did not return an item")
        return Item.model_validate(row)

    async def add_many(self, items: Iterable[Item]) -> int:
        """Insert a bounded batch with one driver-level executemany operation."""

        parameter_sets = (_item_values(item) for item in items)
        return await self.connection.execute_many(INSERT_ITEMS, parameter_sets)

    async def list(self, workspace_id: UUID | None, filters: ItemFilter) -> tuple[Item, ...]:
        query, parameters, prepare = build_item_list_query(workspace_id, filters)
        rows = await self.connection.fetch_all(query, parameters, prepare=prepare)
        return tuple(Item.model_validate(row) for row in rows)
