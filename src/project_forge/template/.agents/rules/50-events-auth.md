# Optional capability rules

- Auth uses opaque database-backed sessions, Argon2 password hashing, origin checks, and CSRF.
- Workspace paths and membership checks are explicit; never infer tenant scope from payload data.
- Outbox writes share the domain transaction.
- Stream consumers acknowledge only after commit and must be idempotent.
- Exhausted messages enter a DLQ; unknown outcomes are reviewed rather than retried forever.
