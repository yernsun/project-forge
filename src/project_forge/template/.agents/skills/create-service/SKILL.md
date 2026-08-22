---
name: create-service
description: Add or modify Service-layer use cases, transaction boundaries, and business workflows in this generated project.
---

Keep orchestration in the Service. Open one Unit of Work for the atomic use case, call repositories
through it, enqueue outbox events before commit when enabled, and return domain values rather than
database rows. Test commit, rollback, and business failure behavior.
