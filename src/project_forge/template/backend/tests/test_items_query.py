from datetime import UTC, datetime

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
    assert rendered.index("name ILIKE") < rendered.index("description IS NULL")
    assert rendered.index("description IS NULL") < rendered.index("status =")
    assert rendered.index("status =") < rendered.index("created_at >=")
    assert 'ORDER BY "name" ASC' in rendered
    assert parameters["name_pattern"] == "%alpha%"
    assert prepare is False


def test_unset_is_different_from_sql_null() -> None:
    unset_query, _, _ = build_item_list_query(None, ItemFilter(description=UNSET))
    null_query, _, _ = build_item_list_query(None, ItemFilter(description=None))
    assert "description IS NULL" not in unset_query.as_string()
    assert "description IS NULL" in null_query.as_string()
