# Structured logging and file isolation

Every backend process writes bounded JSON Lines to a directory owned by its process domain and
instance:

```text
logs/
  api/<instance>/{business,debug,error,sql}.log
  cli/<instance>/{business,debug,error,sql}.log
  event-relay/<instance>/{business,debug,error,sql}.log
  <worker-domain>/<instance>/{business,debug,error,sql}.log
```

`APP_LOG_ROOT` selects the root. `APP_LOG_INSTANCE_ID` defaults to the hostname; explicitly assign a
stable, unique value to every concurrent process that shares a filesystem. Compose mounts `/app/logs`
on the `runtime-logs` volume and lets each container hostname isolate its files. Do not run multiple
same-domain OS processes with one instance ID against the same directory.

## Channels and rotation

| Channel | Contents | Default behavior |
|---|---|---|
| `business.log` | Non-SQL INFO and higher | Business outcomes, lifecycle, HTTP completion |
| `debug.log` | Non-SQL DEBUG only | Written when `APP_LOG_LEVEL=DEBUG` |
| `error.log` | All WARNING and higher | Includes slow/failed SQL for one operational error view |
| `sql.log` | Parameter-free SQL observations at every level | Controlled by `APP_LOG_SQL_ENABLED` |

Each file rotates at `APP_LOG_MAX_BYTES` and retains `APP_LOG_BACKUP_COUNT` backups. Defaults are 10
MiB and five backups. `APP_LOG_SQL_SLOW_MS` defaults to 200 ms; slow SQL is written to both
`sql.log` and `error.log`. Console output stays readable and never includes SQL text.

## Event contract

Use `app.observability.log_event` or `log_exception`. A record always has a timestamp, level,
logger, static message, stable dotted event, event domain, outcome, process domain, instance,
environment, and PID. Bind relevant request, operation, correlation, causation, actor, workspace,
event, and message IDs through `operation_context`; the formatter adds them to every nested record.

API adapters own transport outcomes. Services own business outcomes and log success only after the
Unit of Work commits. Workers bind message/event context, log retry or DLQ decisions, and log
success only after commit and acknowledgement. Domain code never logs. Repositories contain SQL but
do not emit business logs; the task-bound repository connection records SQL operation, duration,
row count, transaction ID, and repository label.

SQL observations include the Psycopg statement with named placeholders, never the parameter map or
its values. Logs are diagnostics rather than a durable audit trail: persist any fact required for
correctness in the same transaction as the business change.

## Data safety and validation

Never log bodies, headers, event payloads, DTOs, entities, credentials, database URLs, cookies,
tokens, sessions, private keys, raw exception messages, or third-party responses. Sensitive field
names are recursively redacted, unknown objects are represented only by type, exception output is
limited to type and stack-frame locations, collections and strings are bounded, and every JSON line
is capped at 64 KiB.

Logging startup rejects invalid domain/instance values and any symlink or Windows junction in the
managed log path. Run these checks after changing instrumentation:

```bash
python harness/check_logging.py
python harness/check.py
```

The static logging check rejects direct logger calls, dynamic messages/events, implicit keyword
maps, and sensitive structured field names outside the observability core.
