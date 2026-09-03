---
name: instrument-observability
description: Add or revise structured application logs, process file isolation, correlation context, or SQL observations in this generated project.
---

Read `.agents/rules/15-observability.md` before editing. Preserve the existing
`logs/<domain>/<instance>/` routing and initialize logging only at a real API, CLI, or worker
entrypoint. Use `log_event`/`log_exception` with a static message, a stable dotted event, an explicit
outcome, and only the identifiers needed to diagnose the operation.

Place business success logs after the Service-owned Unit of Work commits. At worker boundaries,
bind message and event identifiers before handling and log success only after ACK. Keep domain code
free of logging and leave SQL timing to the injected repository connection. A log cannot replace a
transactional audit or outbox record.

Add routing/context/redaction tests for infrastructure changes and observable outcome tests for
business changes. Run `python harness/check_logging.py` followed by `python harness/check.py`.
