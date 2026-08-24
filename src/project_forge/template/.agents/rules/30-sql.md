# SQL rules

- Bind every value with Psycopg named parameters. Never interpolate values.
- Whitelist identifiers and sort directions, then compose them with `psycopg.sql`.
- Use fixed statements for hot paths and typed repository-local filters for complex searches.
- Preserve canonical predicate ordering and explicit omitted-versus-NULL semantics.
- Use `SqlPredicateBuilder` only for safe predicate composition; business columns, joins, and
  sorting remain repository-local allowlists.
- Escape LIKE metacharacters and use one `= ANY(array_parameter)` shape for variable lists; bind an
  empty array to the same shape so it evaluates to no rows.
- Use `prepare=True` for fixed hot paths and `prepare=False` for open-ended conditional shapes.
- Persistence execution belongs only in repositories and migration infrastructure.
