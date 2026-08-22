---
name: create-worker
description: Add or modify Redis Stream workers, outbox relays, retries, idempotency, acknowledgements, or DLQ behavior in this generated project.
---

Use normalized envelopes. Process inside a Service-owned transaction, record the message ID before
commit, and acknowledge only after commit. Bound retries, send exhausted work to the DLQ, and cover
duplicate delivery and crash-before-ack behavior in tests.
