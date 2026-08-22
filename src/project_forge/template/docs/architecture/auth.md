# Authentication

When enabled, authentication uses random opaque session tokens. Only their hashes are stored in
PostgreSQL. Cookies are HttpOnly, SameSite, and Secure outside development. Unsafe requests require
an origin allowlist and a double-submit CSRF token whose hash is also tied to the session.

Workspace isolation is explicit in `/api/v1/workspaces/{workspaceId}` paths and every Service checks
membership before opening a workspace-scoped use case. The baseline intentionally excludes password
reset, email verification, invitations, OIDC, and role hierarchies.
