# Conditional SQL

Every runtime value uses a descriptive Psycopg named placeholder such as `%(workspace_id)s`, and
every execution passes a mapping. Positional `%s`/`%b`/`%t`, `$1`, tuple parameters, quoted
placeholders, `sql.Literal`, and Python string interpolation are outside the project contract.
`sql.SQL` contains only static grammar. Dynamic identifiers and ordering are selected from
repository-owned allowlists and composed with `sql.Identifier` and other trusted
`psycopg.sql.Composable` objects. `SQL.format()` and `SQL.join()` are for structure, never values.

Use fixed query variants for latency-sensitive, frequently executed paths. Stable shapes give
PostgreSQL predictable plans and make index review straightforward.

For complex filters, define a typed filter next to its repository. Use a dedicated `UNSET` sentinel
so omitted and explicit `NULL` have different meanings. `SqlPredicateBuilder` supplies safe equality,
range, escaped `ILIKE`, and `ANY(array)` mechanics, but the repository still owns every column, join,
and sort allowlist. Append predicates in a canonical order and bind values by name. Empty list filters
stay bound as empty arrays in the same `= ANY(parameter)` shape, which evaluates to no rows without
disappearing silently or producing `IN ()`.

Fixed hot-path statements use `prepare=True`. Open-ended conditional searches use `prepare=False`
to avoid filling the driver/server prepared-statement cache with many shapes. Keep a deterministic
tie-breaker in every pageable ordering, cap page sizes, and verify representative shapes against a
real PostgreSQL database with `EXPLAIN` when adding indexes.

Do not build a global query language. If a search becomes important enough to tune independently,
promote its common shapes into explicit fixed statements.

For writes over multiple rows, choose the strategy explicitly:

1. Prefer one set-based statement using `ANY`, `UNNEST`, `INSERT ... SELECT`, or a CTE when the
   operation needs one result or `RETURNING`.
2. Use `RepositoryConnection.execute_many()` for bounded independent rows. The query still uses
   descriptive named placeholders and every row is a mapping. Empty input performs no SQL and
   returns zero. Psycopg already pipelines `executemany`; do not add a manual pipeline.
3. Use a fixed `COPY ... FROM STDIN` statement through `copy_rows()` for large import-oriented
   inserts without per-row results or conflict handling. COPY row order must exactly match the
   explicit column list and the whole copy remains inside the UoW transaction.

Calling `execute`, `fetch_one`, or `fetch_all` inside a loop is forbidden because it turns a batch
into N database round trips. Loops may submit explicit bounded chunks through `execute_many` or
`copy_rows` only when the use case permits the chosen transaction boundary.

See `.agents/rules/30-sql.md` for the complete contract and examples. The upstream behavior is
documented in the [Psycopg SQL composition API](https://www.psycopg.org/psycopg3/docs/api/sql.html)
and [query parameter guide](https://www.psycopg.org/psycopg3/docs/basic/params.html).
Batch behavior is defined by the [cursor API](https://www.psycopg.org/psycopg3/docs/api/cursors.html),
[pipeline mode](https://www.psycopg.org/psycopg3/docs/advanced/pipeline.html), and
[COPY guide](https://www.psycopg.org/psycopg3/docs/basic/copy.html).
