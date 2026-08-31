# Service, Repository, and Unit of Work

The API creates Services, not repositories. A Service opens one Unit of Work for a use case. The
Unit of Work owns the pool acquisition, opens one transaction, and then commits or rolls back as its
context exits. It cannot be reused or crossed into another async task.

Every public repository contract inherits `BaseRepository, Protocol`; every concrete PostgreSQL
implementation inherits `BaseRepository` and is named `Postgres*Repository`. UnitOfWork creates each
implementation lazily with a cached property:

```python
@cached_property
def items(self) -> PostgresItemRepository:
    return PostgresItemRepository(self._require_connection())
```

`_require_connection()` returns a guarded `RepositoryConnection`, not a pool or raw Psycopg
connection. It exposes only `execute`, `fetch_one`, `fetch_all`, `execute_many`, and `copy_rows`,
checks the owning asyncio task before every call, and detaches the raw connection before the UoW
returns it to the pool. An escaped repository therefore cannot execute after transaction exit.

Repositories never acquire a connection, create a cursor, commit, roll back, or start transactions.
They execute SQL through the injected guard, map rows, and return domain values. Cross-repository
orchestration stays in the Service. Tests may construct a concrete repository with a fake
`RepositoryConnection`; production code may instantiate one only inside UnitOfWork.

The dependency direction is enforced rather than conventional: domain modules import no framework
or infrastructure package; API modules import Services rather than repositories or database types;
Services import Unit of Work and domain types but no FastAPI or Psycopg symbols. Repository modules
own SQL, while the guarded database adapter alone owns Psycopg cursor mechanics. Run
`python harness/check.py` after moving code between layers so `check_architecture.py` can catch
inheritance, instantiation, raw-connection, and dependency regressions immediately.
