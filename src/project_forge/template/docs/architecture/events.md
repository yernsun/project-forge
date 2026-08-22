# Outbox and Redis Streams

When enabled, a Service writes domain state and a PostgreSQL outbox row in one transaction. A relay
claims unpublished rows, publishes normalized envelopes to Redis Streams, and records publication.
Consumers use groups, acknowledge only after their database transaction commits, track processed
message IDs, retry a bounded number of times, and move exhausted messages to a DLQ.

Delivery is at least once. Idempotency is mandatory; processing is never assumed exactly once.
