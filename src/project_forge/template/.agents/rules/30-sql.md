# SQL rules

These rules apply to every Psycopg query, including repositories, database adapters, migrations,
tests, maintenance commands, and one-off data fixes. Treat query data and query structure as two
different channels. Data is bound by Psycopg; structure is assembled only from trusted
`psycopg.sql.Composable` objects.

## Ownership and transaction boundary

- Application SQL is executed only by repositories. Database bootstrap and immutable forward
  migrations are the only infrastructure exceptions.
- Services own transaction boundaries through the Unit of Work. Repositories execute SQL and map
  rows; they never commit, roll back, or open an independent business transaction.
- The Unit of Work owns pool acquisition and creates every concrete `Postgres*Repository` lazily
  through `@cached_property`. Application modules never instantiate concrete repositories.
- Every repository contract inherits `BaseRepository, Protocol`; every PostgreSQL implementation
  inherits `BaseRepository`. A repository receives only the task-bound `RepositoryConnection`
  injected by `UnitOfWork._require_connection()`.
- Repositories never import connection/pool types or call `connect`, `connection`, `cursor`,
  `transaction`, `commit`, or `rollback`. The guarded adapter is the only application component
  that opens Psycopg cursors, and it becomes unusable when the UoW exits or crosses tasks.
- API handlers, domain modules, and services must not import Psycopg, accept SQL fragments, or
  access a connection/cursor directly.
- Forward migration `up_sql` is one immutable static string literal. It has no runtime inputs or
  placeholders; the migration engine is the sole reviewed boundary that wraps the checksummed DDL
  in `sql.SQL`. Never interpolate migration SQL or rewrite an applied migration.

## Runtime values: named parameters only

- Bind every runtime value with a named placeholder: `%(workspace_id)s`. Pass the values separately
  as a mapping: `{"workspace_id": workspace_id}`.
- Parameter names are descriptive `lower_snake_case` identifiers. Do not use `p1`, `arg2`,
  `param3`, `value4`, or names containing punctuation.
- Reuse the same name when the same semantic runtime value appears more than once. Use different
  names for values with different meanings, even if they happen to be equal.
- The normal placeholder is `%(name)s`. If binary or text format is deliberately required, it must
  still be named (`%(payload)b` or `%(payload)t`) and documented at the call site.
- Never use positional `%s`, `%b`, or `%t`, PostgreSQL/async-driver `$1` placeholders, or a sequence
  of parameters. Never call `sql.Placeholder()` without a non-empty name.
- Do not quote placeholders. Write `WHERE email = %(email)s`, not
  `WHERE email = '%(email)s'`. Psycopg adapts and quotes values according to their types.
- A literal percent sign in a parameterized query is written as `%%` where Psycopg requires it.
- `execute()`, `fetch_one()`, and `fetch_all()` receive a mapping whenever parameters are present.
  `execute_many()` receives an iterable of mappings using the same named query contract.
- Runtime values must never enter SQL through f-strings, Python `%`, `str.format()`, concatenation,
  `sql.SQL()`, `sql.Literal()`, `Composable.as_string()`, or manual quoting/escaping.

## Query structure: `psycopg.sql` only

Use each Psycopg composition object for its intended role:

| API | Allowed use | Project rule |
| --- | --- | --- |
| `sql.SQL` | SQL grammar and fixed templates | Its argument is a static trusted string. It does not escape input. |
| `sql.Identifier` | Table, schema, column, alias names | Construct only from repository-owned constants/allowlists, never directly from request text. |
| `sql.Placeholder` | A value supplied later to `execute()` | Always give it a validated descriptive name. Anonymous placeholders are forbidden. |
| `sql.Literal` | A value embedded into query text | Do not use it in application SQL; bind the value by name instead. |
| `sql.Composed` | Result of combining composables | Do not instantiate it directly. Produce it with `SQL.format()`, `SQL.join()`, or `+`. |

- `{}` placeholders used by `sql.SQL(...).format(...)` are only for SQL structure. Every replacement
  must already be a trusted `Composable`; passing a Python value is forbidden because Psycopg will
  convert non-composables into embedded literals.
- Every item passed to `sql.SQL(...).join(...)` must be a trusted `Composable`. Do not join raw
  strings, request fields, or values.
- Select dynamic identifiers and sort expressions through a closed mapping from a typed enum to
  prebuilt `Identifier`/`SQL` objects. Validation followed by `sql.Identifier(user_text)` is not an
  acceptable substitute for a local allowlist.
- Sort direction, operators, functions, joins, casts, clauses, and fragments are SQL structure.
  Represent their finite choices as static composables; they are not bind parameters and must never
  come from raw input.
- Do not create a general query language or accept caller-provided predicates. Each repository owns
  its tables, joins, filters, projections, and ordering contract.

## Conditional query rules

- Prefer fixed statements for latency-sensitive hot paths. Use typed repository-local filter models
  only when the number of useful combinations makes fixed variants impractical.
- Distinguish all three states explicitly: omitted (`UNSET`), SQL `NULL` (`IS NULL` / `IS NOT NULL`),
  and a concrete bound value. Do not overload Python `None` to mean both omitted and SQL `NULL`.
- Append optional predicates in one canonical order so the same filter set produces the same query
  shape regardless of caller input order.
- Use `SqlPredicateBuilder` only for the safe mechanics of predicates and named bindings. Business
  columns, joins, predicates, and ordering remain in the repository allowlist.
- Use `column = ANY(%(ids)s)` with one bound array for variable-length equality lists. An empty list
  stays bound to the same shape and means no rows; never emit `IN ()`, expand one placeholder per
  element, or silently drop the filter.
- Escape `\\`, `%`, and `_` before adding wildcards to a `LIKE`/`ILIKE` value, and declare the escape
  character in SQL. Do not let caller wildcards change the search contract accidentally.
- Pageable ordering always includes a stable unique tie-breaker. Cap limits/offsets and select the
  primary sort expression from an allowlist.

## Batch write rules

Choose the narrowest efficient shape explicitly; never hide an automatic threshold in a generic
repository helper.

1. Prefer one set-based statement (`ANY`, `UNNEST`, `INSERT ... SELECT`, or a bounded CTE) when the
   operation has one semantic result or needs `RETURNING`.
2. Use `RepositoryConnection.execute_many()` for a bounded collection of independent executions of
   the same statement. Every row is a mapping keyed by the query's named placeholders. Empty input
   is a no-op returning zero. Psycopg pipelines `executemany()` internally, so do not open a manual
   pipeline around it.
3. Use `RepositoryConnection.copy_rows()` with a fixed `COPY ... FROM STDIN` composable for large,
   insert-oriented imports that do not require per-row `RETURNING` or `ON CONFLICT`. COPY row values
   are ordered protocol data, not SQL parameters; the fixed COPY column list defines their meaning.

- Do not call `execute()`, `fetch_one()`, or `fetch_all()` inside `for`/`async for`. Replace the N
  round trips with set-based SQL, `execute_many()`, or `copy_rows()`.
- `execute_many()` deliberately does not expose result sets. Use one set-based statement with
  `RETURNING` when results are required.
- COPY participates in the current UoW transaction. Any adaptation, constraint, or stream failure
  rolls back the transaction; do not commit partial chunks from a repository.
- Chunking belongs at an explicit use-case boundary only when separate commits are valid. Looping
  over bounded chunks may call `execute_many()`/`copy_rows()`, never one-row execution.

## Preparation and review

- Fixed hot-path statements explicitly use `prepare=True`.
- Open-ended conditional shapes explicitly use `prepare=False` to avoid unbounded prepared statement
  shapes. The repository chooses this policy at every single-statement connection call.
- Add query-shape tests for named binding, allowlisted ordering, canonical predicate order,
  omitted/`NULL`/value semantics, empty arrays, escaped `ILIKE`, and preparation policy.
- Exercise representative PostgreSQL shapes with `EXPLAIN` when adding or relying on an index.
- Run `python harness/check_sql.py`; do not suppress or work around a finding.

## Examples

Fixed query with one mapping entry reused for the same semantic value:

```python
UPDATE_PASSWORD = sql.SQL(
    "UPDATE users SET password_hash = %(password_hash)s, "
    "password_updated_at = %(updated_at)s, updated_at = %(updated_at)s "
    "WHERE user_id = %(user_id)s"
)

await self.connection.execute(
    UPDATE_PASSWORD,
    {
        "user_id": user_id,
        "password_hash": password_hash,
        "updated_at": updated_at,
    },
    prepare=True,
)
```

Allowlisted structure plus named values:

```python
SORTS = {
    ItemSort.CREATED_DESC: sql.Identifier("created_at") + sql.SQL(" DESC"),
    ItemSort.NAME_ASC: sql.Identifier("name") + sql.SQL(" ASC"),
}

query = sql.SQL(
    "SELECT item_id, name FROM items "
    "WHERE workspace_id = %(workspace_id)s ORDER BY {ordering}, item_id ASC"
).format(ordering=SORTS[filters.sort])

rows = await self.connection.fetch_all(
    query,
    {"workspace_id": workspace_id},
    prepare=False,
)
```

Bounded batch with the same readable named contract:

```python
INSERT_ITEMS = sql.SQL(
    "INSERT INTO items (item_id, name) VALUES (%(item_id)s, %(name)s)"
)

parameter_sets = (
    {"item_id": item.item_id, "name": item.name}
    for item in items
)
inserted = await self.connection.execute_many(INSERT_ITEMS, parameter_sets)
```

Large import with an explicit ordered COPY contract:

```python
COPY_ITEMS = sql.SQL(
    "COPY items (item_id, name, created_at) FROM STDIN"
)
copied = await self.connection.copy_rows(
    COPY_ITEMS,
    ((item.item_id, item.name, item.created_at) for item in items),
)
```

Forbidden forms:

```python
sql.SQL(f"SELECT * FROM {table_name}")
sql.SQL("SELECT * FROM {} WHERE id = {}").format(table_name, item_id)
sql.SQL("SELECT * FROM items WHERE item_id = %s")
sql.Placeholder()
sql.Literal(item_id)
await cursor.execute(query, (item_id,))
PostgresItemRepository(connection)  # concrete repositories are UoW-owned
for item in items:
    await self.connection.execute(INSERT_ITEM, {"item_id": item.item_id}, prepare=True)
```

References:

- [Psycopg 3 SQL string composition](https://www.psycopg.org/psycopg3/docs/api/sql.html)
- [Psycopg 3 query parameters](https://www.psycopg.org/psycopg3/docs/basic/params.html)
- [Psycopg cursor and executemany](https://www.psycopg.org/psycopg3/docs/api/cursors.html)
- [Psycopg pipeline mode](https://www.psycopg.org/psycopg3/docs/advanced/pipeline.html)
- [Psycopg COPY](https://www.psycopg.org/psycopg3/docs/basic/copy.html)
- [Teclado SQL string composition lesson](https://pysql.tecladocode.com/section08/lectures/08_sql_string_composition/)

The Teclado lesson is useful for understanding the separation between values and identifiers, but
its examples use Psycopg 2, positional parameters, and identifiers derived directly from input.
Project Forge's Psycopg 3, named-mapping, and repository-allowlist rules above take precedence.
