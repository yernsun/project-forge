# SQL rules

- Bind every value with Psycopg named parameters. Never interpolate values.
- Whitelist identifiers and sort directions, then compose them with `psycopg.sql`.
- Use fixed statements for hot paths and typed repository-local filters for complex searches.
- Preserve canonical predicate ordering and explicit omitted-versus-NULL semantics.
- Persistence execution belongs only in repositories and migration infrastructure.
