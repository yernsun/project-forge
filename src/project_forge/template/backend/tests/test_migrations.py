import pytest

from app.db.migration_engine import Migration, MigrationError, ordered_migrations


def migration(migration_id: str, dependencies: tuple[str, ...] = ()) -> Migration:
    return Migration(migration_id=migration_id, dependencies=dependencies, up_sql="SELECT 1;")


def test_migration_dag_is_topologically_sorted() -> None:
    result = ordered_migrations((migration("b", ("a",)), migration("a")))
    assert [entry.migration_id for entry in result] == ["a", "b"]


def test_migration_dag_rejects_cycles() -> None:
    with pytest.raises(MigrationError, match="cycle"):
        ordered_migrations((migration("a", ("b",)), migration("b", ("a",))))


def test_checksum_covers_dependencies_and_sql() -> None:
    assert migration("a").checksum != migration("b").checksum
    assert migration("a").checksum != Migration("a", (), "SELECT 2;").checksum
