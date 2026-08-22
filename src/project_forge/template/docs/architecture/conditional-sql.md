# Conditional SQL

Use fixed query variants for latency-sensitive, frequently executed paths. Stable shapes give
PostgreSQL predictable plans and make index review straightforward.

For complex filters, define a typed filter next to its repository. Use a dedicated `UNSET` sentinel
so omitted and explicit `NULL` have different meanings. Append predicates in a canonical order,
bind values by name, and compose columns only from an allowlist of `psycopg.sql.Identifier` values.
Stable shapes may use driver-managed preparation; highly ad-hoc shapes pass `prepare=False`.

Do not build a global query language. If a search becomes important enough to tune independently,
promote its common shapes into explicit fixed statements.
