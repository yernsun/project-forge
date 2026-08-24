from __future__ import annotations

from collections.abc import Mapping, Sequence

from psycopg import sql


def escape_like(value: str, escape: str = "\\") -> str:
    """Escape a value used inside a LIKE/ILIKE pattern."""
    if len(escape) != 1:
        raise ValueError("LIKE escape must be one character")
    return (
        value.replace(escape, escape + escape)
        .replace("%", escape + "%")
        .replace("_", escape + "_")
    )


class SqlPredicateBuilder:
    """Compose a WHERE clause from safe Psycopg fragments and bound values.

    The builder intentionally knows nothing about business fields, joins, or sorting.
    Repositories retain those allowlists and append predicates in canonical order.
    """

    def __init__(self) -> None:
        self._predicates: list[sql.Composable] = []
        self._parameters: dict[str, object] = {}

    def _bind(self, name: str, value: object) -> sql.Placeholder:
        if not name.isidentifier():
            raise ValueError(f"invalid parameter name: {name!r}")
        if name in self._parameters:
            raise ValueError(f"duplicate SQL parameter: {name}")
        self._parameters[name] = value
        return sql.Placeholder(name)

    def add(
        self,
        predicate: sql.Composable,
        parameters: Mapping[str, object] | None = None,
    ) -> None:
        if not isinstance(predicate, sql.Composable):
            raise TypeError("predicate must be a psycopg.sql.Composable")
        if parameters:
            invalid = sorted(name for name in parameters if not name.isidentifier())
            if invalid:
                raise ValueError(f"invalid parameter name: {invalid[0]!r}")
            duplicates = self._parameters.keys() & parameters.keys()
            if duplicates:
                duplicate = sorted(duplicates)[0]
                raise ValueError(f"duplicate SQL parameter: {duplicate}")
            self._parameters.update(parameters)
        self._predicates.append(predicate)

    def add_equals(self, column: sql.Identifier, name: str, value: object) -> None:
        self._predicates.append(column + sql.SQL(" = ") + self._bind(name, value))

    def add_greater_than_or_equal(
        self, column: sql.Identifier, name: str, value: object
    ) -> None:
        self._predicates.append(column + sql.SQL(" >= ") + self._bind(name, value))

    def add_is_null(self, column: sql.Identifier) -> None:
        self._predicates.append(column + sql.SQL(" IS NULL"))

    def add_ilike_contains(self, column: sql.Identifier, name: str, value: str) -> None:
        pattern = f"%{escape_like(value)}%"
        self._predicates.append(
            column
            + sql.SQL(" ILIKE ")
            + self._bind(name, pattern)
            + sql.SQL(" ESCAPE '\\'")
        )

    def add_any(self, column: sql.Identifier, name: str, values: Sequence[object]) -> None:
        self._predicates.append(
            column + sql.SQL(" = ANY(") + self._bind(name, list(values)) + sql.SQL(")")
        )

    def build(self) -> tuple[sql.Composable, dict[str, object]]:
        predicate = (
            sql.SQL(" AND ").join(self._predicates)
            if self._predicates
            else sql.SQL("TRUE")
        )
        return predicate, dict(self._parameters)
