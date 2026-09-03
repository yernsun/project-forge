# Architecture

Project Forge has three layers:

1. `ProjectState` validates profile and monotonic capability constraints.
2. Copier renders an isolated desired project from the packaged template.
3. The update engine compares the previous template baseline, the current project, and the new
   desired render. One-sided changes apply automatically; double-sided changes become `.rej`.

State schema 3 records both the generated console command and a deterministic SHA-256 digest of the
packaged rendering source. Schema v1/v2 loads with its historical `app` command identity; the next
mutating operation hard-switches it to the project slug. A read-only `update --check` always performs
the isolated render and three-way comparison, so it can report that break and detect same-version
template refreshes without touching managed files, state, baseline, or conflict artifacts.

Preview and apply return one shared result model with stable, sorted paths. Baselines normalize tar
and gzip metadata, ordering, ownership, timestamps, and permissions, making equal renders byte
identical. An up-to-date update writes nothing. Extraction rejects archives above the compressed,
member-count, per-member, or total-uncompressed limits before creating output, and every project
write rejects symlink or Windows-junction components. Obstructed conflict diagnostics fall back to a
regular file directly inside the verified project root.

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
validation logs without bodies, credentials, cookies, or secrets. `<command-name> config check --json` exposes
only a redacted effective-settings summary. Event relays reclaim stale pending deliveries, bound
attempts, park failed outbox rows, and require explicit operator replay after remediation.

Every generated process configures one logging domain and writes rotated JSON Lines beneath
`logs/<domain>/<instance>/`. Business, debug, error, and SQL channels are routed independently;
slow and failed SQL also reaches the error channel, while SQL never reaches the console. Context
variables carry request, operation, actor, workspace, event, and message identifiers across layers.
The repository connection records only rendered statements with named placeholders, duration,
row count, transaction ID, and repository label—never parameter values. Formatters bound every
field and line, recursively redact sensitive names, and omit raw exception values. The generated
logging harness enforces static messages/events, explicit safe fields, and the domain/Service/
Repository ownership boundary.

The generated frontend keeps server state in Vue Query, client-owned locale, Aura color-scheme
preference, and per-user workspace selection in Pinia, DTO types in one of four real FastAPI OpenAPI
contracts, and locale state in one
i18n module that also updates PrimeVue's locale object. Its application shell has explicit loading,
guest, and authenticated states; protected queries do not mount for guests.

CI treats every valid render as a product: Python 3.13 runs the complete parallelized render/quality
matrix, while 3.11, 3.12, and 3.14 run the compatibility-marked CLI, state-migration, and update
contract. OpenAPI contracts run independently. Representative CLI flows (including a real Windows
junction) smoke-test macOS and Windows; supported Node LTS checks, dependency audits, coverage gates,
Compose readiness, wheel isolation, checksums, SBOM, and provenance protect the delivery path.
