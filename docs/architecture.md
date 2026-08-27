# Architecture

Project Forge has three layers:

1. `ProjectState` validates profile and monotonic capability constraints.
2. Copier renders an isolated desired project from the packaged template.
3. The update engine compares the previous template baseline, the current project, and the new
   desired render. One-sided changes apply automatically; double-sided changes become `.rej`.

State schema 2 also records a deterministic SHA-256 digest of the packaged rendering source. A
read-only `update --check` always performs the isolated render and three-way comparison, so it can
detect same-version template refreshes without touching managed files, state, baseline, or conflict
artifacts. Apply and preview share one update planner to prevent their semantics from drifting.

The generated backend follows the enforced dependency direction
`API → Service → Unit of Work → Repository → PostgreSQL`. API DTOs, domain models, credential
records, and database row mapping remain separate. A Service opens the transaction, a single-use
task-bound Unit of Work owns one Psycopg connection and repository lifecycle, and repositories
contain all persistence SQL and row mapping. The generated AST harness rejects framework imports in
the domain, HTTP imports in Services, API-to-repository shortcuts, and SQL outside persistence
adapters.

Conditional SQL deliberately uses two modes. Stable hot paths keep fixed statements for predictable
query plans. Complex searches accept a typed filter object, distinguish `UNSET` from SQL `NULL`,
append predicates in canonical order, bind named values, and whitelist every identifier and sort
direction through `psycopg.sql`. Array filters use one `ANY()` parameter, empty arrays mean no rows,
and `ILIKE` values escape wildcard metacharacters. Open-ended shapes use `prepare=False`; fixed
queries use `prepare=True`.

Optional authentication uses Argon2id passwords and opaque PostgreSQL sessions, never JWT or Redis.
The session cookie is HttpOnly; a readable, session-bound CSRF token and exact allowed-origin check
protect every authenticated unsafe method. PostgreSQL also owns HMAC-pseudonymized fixed-window
login and signup limits. Production fails closed unless cookies are Secure, origins are HTTPS, and a
dedicated rate-limit secret is configured.

Generated HTTP adapters attach or safely propagate `X-Request-ID` and emit structured access and
validation logs without bodies, credentials, cookies, or secrets. `app config check --json` exposes
only a redacted effective-settings summary. Event relays reclaim stale pending deliveries, bound
attempts, park failed outbox rows, and require explicit operator replay after remediation.

The generated frontend keeps server state in Vue Query, client-owned locale and per-user workspace
selection in Pinia, DTO types in one of four real FastAPI OpenAPI contracts, and locale state in one
i18n module that also updates PrimeVue's locale object. Its application shell has explicit loading,
guest, and authenticated states; protected queries do not mount for guests.

CI treats every valid render as a product: Python grammar and generator tests run across supported
Python releases, representative CLI flows smoke-test macOS and Windows, frontend checks use only
supported Node LTS lines, and dependency audits, coverage gates, Compose readiness, wheel isolation,
checksums, SBOM, and provenance protect the delivery path.
