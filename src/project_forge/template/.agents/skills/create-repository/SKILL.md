---
name: create-repository
description: Add or modify Psycopg repositories, persistence mappings, and safe fixed or conditional SQL in this generated project.
---

Read `.agents/rules/30-sql.md` before editing. Keep SQL and row mapping in the repository. Bind every
runtime value through a descriptive `%(lower_snake_case)s` placeholder and pass a mapping to
`execute()`/`fetch_one()`/`fetch_all()`; never use positional parameters or `sql.Literal`. Compose structure only from static
`sql.SQL` and repository-local allowlists of trusted `Composable` objects. Use a typed filter with
canonical predicate ordering for conditional searches and `app.db.query.SqlPredicateBuilder` for
reusable safe predicate mechanics while keeping business columns, joins, and ordering in this
repository. Escape LIKE patterns, use one named array parameter for variable lists, and choose
preparation policy deliberately.

Define the public contract as `ExampleRepository(BaseRepository, Protocol)` and the implementation
as `PostgresExampleRepository(BaseRepository)`. Add exactly one `@cached_property` to UnitOfWork
that returns `PostgresExampleRepository(self._require_connection())`; never instantiate the
implementation elsewhere. Do not import a pool/raw connection or open a cursor in a repository.

For batches, prefer set-based SQL, then `execute_many()` with an iterable of named mappings, and use
fixed `copy_rows()` only for large import-style writes. Never issue one-row SQL in a loop or add a
manual pipeline around `execute_many()`. Add query-shape and batch tests, then run
`python harness/check.py`.
