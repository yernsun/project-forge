# Documentation index

Use this page to route an engineering change to the rule set that owns it. Start with
`../AGENTS.md` and the repository README, then read the relevant document before editing code.

| Change | Read first | Key boundary |
|---|---|---|
| API, Service, UoW, or Repository | [Service, Repository, and UoW](architecture/service-repository-uow.md) | Services own transactions; API never bypasses Services |
| Filters, sorting, joins, or indexes | [Conditional SQL](architecture/conditional-sql.md) | Values are bound; identifiers and ordering are whitelisted |
| Schema evolution | [Migrations](architecture/migrations.md) | Forward-only DAG; startup requires all migrations applied |
| Vue state, API client, or translations | [Frontend and i18n](architecture/frontend-i18n.md) | Vue Query owns server state; both locales remain complete |
| Login, sessions, cookies, CSRF, or tenancy | [Authentication](architecture/auth.md) | PostgreSQL opaque sessions and workspace isolation |
| Outbox, Redis Streams, retries, or DLQ | [Events](architecture/events.md) | At-least-once delivery with stable event-ID deduplication |
| Logs, correlation, SQL timing, or process isolation | [Structured logging](architecture/logging.md) | One rotated file set per domain/instance; no secret or SQL parameter values |
| Compose, LAN, Origin, cookies, or runtime diagnosis | [FAQ](../FAQ.md) | Compare browser-visible values with resolved container configuration |

Run the governed checks from the repository root after a change:

```bash
python harness/check.py
```

For CI-equivalent tool and Compose requirements:

```bash
HARNESS_STRICT=1 HARNESS_DOCKER=1 python harness/check.py
```

The static architecture, SQL, and i18n harnesses can also be run independently while iterating:

```bash
python harness/check_architecture.py
python harness/check_logging.py
python harness/check_sql.py
python harness/check_i18n.py
```
