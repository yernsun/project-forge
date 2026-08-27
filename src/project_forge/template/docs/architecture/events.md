# Outbox and Redis Streams

When enabled, a Service writes domain state and a PostgreSQL outbox row in one transaction. A relay
claims unpublished rows, publishes normalized envelopes to Redis Streams, and records publication.
Consumers use groups, acknowledge only after their database transaction commits, track stable
business event IDs, retry a bounded number of times, and move exhausted messages to a DLQ. Redis
stream entry IDs are transport metadata and must never be used as the durable idempotency key: an
outbox retry can publish the same event under a new stream entry ID.

Delivery is at least once. Idempotency is mandatory; processing is never assumed exactly once.
`0031_event_idempotency` preserves legacy processed rows while changing all new markers to the
envelope `eventId`.

`0032_event_reliability` adds bounded failure metadata and indexes pending and parked rows
separately. The relay uses `APP_EVENT_RELAY_MAX_ATTEMPTS`, reclaims stale Redis pending entries with
`XAUTOCLAIM`, and records only a sanitized failure code. It never stores arbitrary exception text or
message payloads in the failure column. Once attempts are exhausted, PostgreSQL rows are parked and
terminal Redis failures are moved to the DLQ and acknowledged so poison messages cannot spin
forever.

Use operator commands before and after remediation:

```bash
app events status --json
app events retry-failed --limit 100 --dry-run
app events retry-failed --limit 100
```

The retry command is intentionally bounded and explicit. Fix the dependency, schema, or handler
failure first; do not turn the worker into an unbounded automatic replay loop. Shutdown signals stop
new polling, allow the current unit of work to finish, and leave uncommitted messages reclaimable.
