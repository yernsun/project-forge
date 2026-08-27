# Optional capability rules

- Auth uses opaque database-backed sessions and explicit Argon2id settings; never place credentials
  or session tokens in logs, model reprs, URLs, or browser storage.
- Every authenticated unsafe operation uses the shared Session + Origin/Referer + session-bound
  double-submit CSRF dependency. Missing security headers are 403 responses, not validation errors.
- Unknown users take the dummy-hash verification path. Successful login upgrades stale hashes.
- Login and signup consume committed PostgreSQL rate-limit buckets before expensive password work;
  do not roll failed-attempt counters back with the authentication transaction.
- Production authentication fails closed unless cookies are Secure and allowed origins are HTTPS.
- Authentication/session responses are not cacheable, and external clients branch on stable error
  codes rather than server message text.
- Correlate HTTP diagnostics with `X-Request-ID`; structured logs and config summaries never include
  bodies, credentials, cookies, session/CSRF tokens, database URLs, or secrets.
- Workspace paths and membership checks are explicit; never infer tenant scope from payload data.
- Outbox writes share the domain transaction.
- Stream consumers acknowledge only after commit and must deduplicate by the envelope's stable
  business event ID, never by the Redis stream entry ID.
- Exhausted messages enter a DLQ; unknown outcomes are reviewed rather than retried forever.
- Reclaim stale pending entries, cap relay attempts, park exhausted outbox rows, and require a
  bounded explicit operator retry after the underlying failure is fixed.
