# Authentication

When enabled, authentication uses database-backed opaque sessions. The browser receives a random
session token and a random CSRF token; PostgreSQL stores only SHA-256 token digests. Passwords use an
explicit Argon2id policy, missing-user login attempts execute the same Argon2 verification path, and
successful login upgrades hashes whose work factor is stale.

## HTTP boundary

- `POST /api/v1/auth/signup` and `POST /api/v1/auth/login` require an allowed `Origin` (or an
  allowed-origin `Referer` fallback). Production signup is disabled unless
  `APP_SIGNUP_ENABLED=true` is set explicitly.
- `GET /api/v1/auth/session` and safe workspace/resource reads require `CurrentSessionDep`.
- Every authenticated `POST`, `PUT`, `PATCH`, or `DELETE` must use `UnsafeSessionDep`. It validates
  the source origin, the readable CSRF cookie, the `X-CSRF-Token` header, and the digest bound to the
  resolved session. Adding a write endpoint without this dependency is a security defect.
- Authentication responses use `Cache-Control: no-store`. Errors have a stable `{code, message}`
  body and distinguish unauthenticated (401), CSRF/origin denial (403), conflict (409), and rate
  limiting (429).
- Every response includes `X-Request-ID`. Validation and access logs are structured and correlated
  by that ID, but never include request bodies, passwords, cookies, session/CSRF tokens, or secrets.
  `app config check --json` provides the redacted effective configuration needed for diagnosis.

Development cookies are named `<project-slug>-session` and `<project-slug>-csrf`. Secure deployments
use host-only `__Host-<project-slug>-session` and `__Host-<project-slug>-csrf` cookies with `Secure`,
`SameSite=Strict`, and `Path=/`; the session cookie is also `HttpOnly`. The CSRF cookie is intentionally
readable by the frontend so its value can be copied into the request header.

## Brute-force boundary

Login consumes a canonical-email-plus-client bucket (5 attempts per 300 seconds) and a client bucket
(30 attempts per 300 seconds). Combining email and client avoids globally locking an account; a
successful login clears only the combined bucket and preserves the client bucket. Signup consumes a
client bucket (5 attempts per 3600 seconds). Subjects are HMAC-SHA-256 pseudonyms keyed by
`APP_AUTH_RATE_LIMIT_SECRET`; raw emails and addresses are not persisted. Counter updates run in a
dedicated Unit of Work that commits before the credential transaction, so a rejected login cannot
roll its attempt back. Login consumes the client bucket first and stops there when it is already
limited, preventing rotated email addresses from creating unbounded combined-bucket rows. Run
`app auth purge-expired` periodically to remove expired sessions and limiter windows.
Use `app auth purge-expired --dry-run` to inspect counts first. PostgreSQL integration tests use the
shared `TEST_DATABASE_URL` convention and must point to a dedicated test database. The lifecycle
test that truncates shared tables also requires `PROJECT_FORGE_DESTRUCTIVE_PG_TESTS=1`; never set
that opt-in for a database containing data you need.

Production settings fail closed: cookies must be secure, allowed origins must use HTTPS, the database
URL must be explicit, and the rate-limit HMAC secret must be unique and at least 32 bytes. Set
`FORWARDED_ALLOW_IPS` to the comma-separated IP addresses or CIDRs of the immediate gateway and every
trusted proxy hop. The application rejects an empty value, malformed networks, and `*` in production.
Universal IPv4 and IPv6 networks (`0.0.0.0/0` and `::/0`) are rejected as equivalent wildcards.
The TLS terminator must overwrite client-supplied forwarding headers before appending its own hop;
never add a network you do not control. Uvicorn then derives `request.client` from the first untrusted
address in the chain, so the PostgreSQL IP buckets remain per client instead of collapsing to a
shared proxy address.

## Workspace isolation and upgrades

The forward-only `0021_auth_security` migration adds credential lifecycle columns, the canonical
email index, the shared limiter table, and the session-expiry index without changing the published
`0020_auth` checksum. The PostgreSQL acceptance suite first applies `0020_auth` in an isolated
schema with legacy data, then applies `0021_auth_security` and verifies that both data and security
objects survive the upgrade.

Before upgrading a database that accepted writes under `0020_auth`, check for case-colliding legacy
addresses and merge the intended accounts before migration:

```sql
SELECT lower(email) AS canonical_email, array_agg(user_id), array_agg(email)
FROM users
GROUP BY lower(email)
HAVING count(*) > 1;
```

`0021_auth_security` fails transactionally instead of choosing an account when this query returns
rows. It lowercases collision-free legacy addresses before creating the defensive canonical index.
For legacy internationalized addresses, export and review them with the application's Python
`str.casefold()` policy before upgrading; new API writes are already casefolded. The migration also
adds `(user_id, workspace_id)` for membership-scoped workspace reads.

Workspace membership is checked by Services before opening workspace-scoped use cases. The forward
`0022_auth_items` migration adds the database foreign key from sample items to workspaces as
`NOT VALID`, which still protects new writes. It validates immediately when no non-null orphan exists.
Projects that enable authentication after already storing unscoped items must explicitly backfill
their `workspace_id`; nullable legacy rows remain allowed by the database but inaccessible through
authenticated Services. Never edit an applied authentication migration because migration checksums
are immutable.

The baseline intentionally excludes email verification, password reset, password changes,
invitations, OIDC, MFA, RBAC, user disablement workflows, and both per-device and all-device logout.
Add those as separately reviewed capabilities rather than weakening the session, CSRF, or
transaction boundaries above.

Development Compose reads only `DEV_*` overrides from an explicitly supplied `.env.dev`; production
`.env` settings cannot silently alter it. Default ports remain loopback-only. A LAN recipe may bind
only the frontend and must list the exact browser origin in `DEV_APP_ALLOWED_ORIGINS`; the API,
PostgreSQL, and Redis stay on loopback.
