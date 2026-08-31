from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from psycopg import sql

_SQL_PARAMETER_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_MEANINGLESS_PARAMETER_NAME = re.compile(r"^(?:arg|p|param|value)\d+$")


def _validate_parameter_name(name: str) -> None:
    if not _SQL_PARAMETER_NAME.fullmatch(name):
        raise ValueError(f"invalid parameter name: {name!r}")
    if _MEANINGLESS_PARAMETER_NAME.fullmatch(name):
        raise ValueError(f"SQL parameter name must be descriptive: {name!r}")


def _same_parameter_value(left: object, right: object) -> bool:
    if left is right:
        return True
    try:
        equal = left == right
    except (TypeError, ValueError):
        return False
    return equal if isinstance(equal, bool) else False


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
        # Keep the local guard explicit so the static SQL harness can prove that
        # this dynamic Placeholder name cannot alter placeholder syntax.
        if not name.isidentifier():
            raise ValueError(f"invalid parameter name: {name!r}")
        _validate_parameter_name(name)
        if name in self._parameters:
            if not _same_parameter_value(self._parameters[name], value):
                raise ValueError(f"conflicting SQL parameter: {name}")
        else:
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
            for name in parameters:
                _validate_parameter_name(name)
            duplicates = self._parameters.keys() & parameters.keys()
            conflicts = sorted(
                name
                for name in duplicates
                if not _same_parameter_value(self._parameters[name], parameters[name])
            )
            if conflicts:
                raise ValueError(f"conflicting SQL parameter: {conflicts[0]}")
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
