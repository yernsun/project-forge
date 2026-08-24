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
