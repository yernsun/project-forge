# Observability and logging

## File isolation and event contract

- Configure logging once at each real process entrypoint with a validated lowercase domain. Every
  concurrent replica has a unique `APP_LOG_INSTANCE_ID`; its files belong under
  `logs/<domain>/<instance>/`.
- Use `app.observability.log_event` and `log_exception`. Messages and event names are static;
  structured values use snake_case fields. Event names follow `<domain>.<object>.<action>` and do
  not contain runtime identifiers or class names.
- Process context (`domain`, `instance`, `environment`, `pid`) is runtime-owned. Operation context
  propagates request, operation, actor, workspace, event, and message identifiers without
  overwriting explicit event fields.
- `business.log` receives non-SQL INFO+, `debug.log` receives non-SQL DEBUG, `error.log` receives
  WARNING+, and `sql.log` receives SQL observations. WARNING is the safety floor even when the
  configured normal level is ERROR.

## Layer ownership

- API adapters log transport completion and rejection without bodies or headers. Services log
  committed business changes and stable rejection reasons. A success event is emitted only after
  the Unit of Work exits successfully.
- Workers establish message/event context, log retry and DLQ decisions, and emit success only after
  commit and ACK. Never log an envelope payload.
- Domain code does not import logging or observability. Repositories do not emit business logs;
  the task-bound connection owns parameter-free SQL timing.
- Logs are diagnostics, not durable audit records. Persist audit facts and outbox events in the
  same business transaction when correctness depends on their existence.

## Safety

- Never log request bodies, headers, SQL parameter values, event payloads, credentials, database
  URLs, passwords, tokens, cookies, sessions, private keys, or raw exception messages.
- Pass identifiers and stable reason/error codes as structured fields. Do not serialize whole DTOs,
  domain entities, exceptions, or third-party responses.
- Extend `LogEvent` for shared application events. Use a static dotted literal only for a truly
  local event, and test its fields and level.
- Run `python harness/check_logging.py` and the full project harness after changing logging.
