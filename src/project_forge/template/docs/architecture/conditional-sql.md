# Conditional SQL

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
