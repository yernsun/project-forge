# Project Forge FAQ

[简体中文](FAQ.zh-CN.md) | English

This guide covers operational problems that commonly appear after Project Forge initializes a
repository. Run commands from the generated repository root unless a command says otherwise. Never
paste passwords, session cookies, CSRF tokens, or `APP_AUTH_RATE_LIMIT_SECRET` into issue reports.

## Docker and environment selection

### Why does FastAPI say "production mode" when `APP_ENV=development`?

These settings control different things:

- `fastapi dev` or `fastapi run` selects the FastAPI server mode.
- `APP_ENV=development|test|production` selects application security defaults and validation.
- `docker compose -f docker-compose.dev.yml ...` selects the development topology.
- `docker compose ...` without `-f` selects the production topology in `docker-compose.yml`.

Check which stack and command are actually running:

```bash
docker compose ls
docker compose --env-file .env.dev -f docker-compose.dev.yml ps
docker compose --env-file .env.dev -f docker-compose.dev.yml logs --tail=100 api frontend
```

The generated development API runs `fastapi dev`; the production image defaults to `fastapi run`.
Changing only `APP_ENV` does not change the server command or Compose topology.

### Which `.env` file controls each workflow?

| Workflow | Configuration source |
|---|---|
| Production Compose | Root `.env`, expanded by `docker-compose.yml` |
| Development Compose | Safe defaults in `docker-compose.dev.yml`, optionally overridden by `.env.dev` |
| Backend run directly on the host | `backend/.env` |
| Frontend run directly on the host | `frontend/.env` |

Production and development variables are deliberately isolated: production uses names such as
`APP_ALLOWED_ORIGINS`, while development Compose reads `DEV_APP_ALLOWED_ORIGINS`. Start by copying
the tracked, secret-free example and always pass it explicitly:

```bash
cp .env.dev.example .env.dev
docker compose --env-file .env.dev -f docker-compose.dev.yml config
docker compose --env-file .env.dev -f docker-compose.dev.yml exec -T api printenv \
  APP_ENV APP_ALLOWED_ORIGINS APP_SESSION_COOKIE_SECURE APP_SIGNUP_ENABLED
```

Without `.env.dev`, every generated host port binds to `127.0.0.1`. Its active example values are
also loopback-safe; the commented LAN recipe exposes only the frontend while PostgreSQL, Redis, and
the API remain loopback-only. Never copy a production secret into `.env.dev`, and never expect the
root `.env` to configure the development stack.

Keep one `KEY=value` assignment per line. An `.env` file must contain a plain URL, not Markdown:

```dotenv
# Correct
APP_ALLOWED_ORIGINS=https://172.20.0.10:8443

# Incorrect
APP_ALLOWED_ORIGINS=[https://172.20.0.10:8443](https://172.20.0.10:8443)
```

Protect files containing credentials:

```bash
chmod 600 .env backend/.env
```

### Why did a configuration change not affect the running container?

Application settings are read at process startup and cached. Validate the resolved Compose model,
then recreate the affected containers:

```bash
docker compose --env-file .env.dev -f docker-compose.dev.yml config --quiet
docker compose --env-file .env.dev -f docker-compose.dev.yml \
  up -d --build --force-recreate migrate api frontend
```

`docker compose restart` does not recreate a container with changed environment variables.

## LAN access and request origins

### How do I expose the development frontend to another device on my LAN?

The browser origin is the externally visible scheme, host, and host port. Copy `.env.dev.example`,
replace the documentation-only private address with the development host's actual LAN address, and
keep every backend dependency on loopback:

```dotenv
DEV_FRONTEND_BIND_HOST=0.0.0.0
DEV_FRONTEND_PORT=8173
DEV_API_BIND_HOST=127.0.0.1
DEV_DB_BIND_HOST=127.0.0.1
DEV_APP_ALLOWED_ORIGINS=http://localhost:8173,http://127.0.0.1:8173,http://172.20.0.10:8173
```

```bash
docker compose --env-file .env.dev -f docker-compose.dev.yml up -d --build
```

Then browse to `http://172.20.0.10:8173`. Replace the address with the server's stable LAN address.
Do not use `0.0.0.0` as a browser URL or allowed origin; it is only a listen address.

### What causes `origin_not_allowed`?

Authentication signup/login and every authenticated unsafe request require an allowed `Origin`,
with an allowed-origin `Referer` fallback. The match is exact after removing a trailing slash:

- `http` and `https` are different origins.
- `localhost`, `127.0.0.1`, and a LAN IP are different origins.
- Ports `5173`, `8173`, and `8700` are different origins.
- An origin never contains `/api/v1`, another path, credentials, a query, or a fragment.

`APP_ALLOWED_ORIGINS` must contain the browser page origin, not any of these internal addresses:

- `http://0.0.0.0:8000`
- `http://api:8000`
- `VITE_API_PROXY_TARGET`

Compare the browser's Network panel `Origin` request header with the value inside the API container:

```bash
docker compose --env-file .env.dev -f docker-compose.dev.yml exec -T api \
  printenv APP_ALLOWED_ORIGINS
```

For direct `curl` calls, send the header explicitly:

```bash
curl -H 'Origin: http://172.20.0.10:8173' \
  http://172.20.0.10:8173/api/v1/auth/session
```

### Can authentication support both HTTP and HTTPS?

Development may allow multiple comma-separated HTTP and HTTPS origins with
`APP_SESSION_COOKIE_SECURE=false`. Production intentionally allows HTTPS origins only and requires
Secure cookies. Do not weaken that production check.

Internal container traffic can remain HTTP. A normal production path is:

```text
browser https://app.example.com
  -> external TLS terminator
  -> http://127.0.0.1:8080
  -> http://api:8000
```

`APP_ALLOWED_ORIGINS` is the documentation-only `https://172.20.0.10:8443` in that example; replace
it with the exact external browser origin. Keep the production gateway on
`APP_BIND_HOST=127.0.0.1` unless a controlled network explicitly requires another binding.

## Authentication requests and cookies

### What causes `request_validation_failed` on signup?

The request reached FastAPI but failed the strict signup DTO before the Service ran. Authentication
responses intentionally hide field-level validation details so passwords and submitted credentials
cannot leak into responses.

The JSON contract is:

```json
{
  "email": "developer@example.com",
  "password": "correct-horse-battery",
  "workspaceName": "Personal"
}
```

Requirements:

- Send `Content-Type: application/json`, not form data.
- `email` must pass `EmailStr`; avoid local/IP-only addresses and special-use `.test` examples.
- Signup passwords contain 12–200 characters and are not automatically trimmed.
- `workspaceName` contains 1–120 characters and cannot be whitespace-only.
- Unknown fields such as `username`, `workspace`, or `confirmPassword` are rejected.
- External fields use camel case; use `workspaceName`.

Use the browser Network panel to inspect Request Payload without sharing the actual password. A
known-good LAN test is:

```bash
curl -i -c .cookies.txt \
  -H 'Origin: http://172.20.0.10:8173' \
  -H 'Content-Type: application/json' \
  --data '{"email":"developer@example.com","password":"correct-horse-battery","workspaceName":"Personal"}' \
  http://172.20.0.10:8173/api/v1/auth/signup
```

Expected success is `201 Created`. A duplicate email returns `409` instead of `422`.

### Why does signup return `signup_disabled`?

Production signup defaults to disabled. Enable it only for the intended enrollment window:

```dotenv
APP_SIGNUP_ENABLED=true
```

Recreate the API container after changing it. Disable public signup again after provisioning users
when open registration is not a product requirement.

### Why does signup return `201`, but session restore returns `401`?

Check the cookie boundary:

- HTTP development requires `APP_SESSION_COOKIE_SECURE=false`.
- HTTPS production requires Secure cookies and uses `__Host-<slug>-session/csrf` names.
- Always use the same browser host. A cookie created on `localhost` does not belong to a LAN IP.
- `SameSite=Strict` intentionally rejects cross-site cookie flows.
- Clear stale cookies after changing host, port, environment, or project slug.

The generated frontend uses an empty `VITE_API_BASE_URL` so API calls remain same-origin. Prefer that
arrangement instead of pointing the browser directly at container port `8000`.

### Why does an authenticated POST/PUT/PATCH/DELETE return `csrf_invalid` or `403`?

Unsafe authenticated requests require all of the following:

- a valid session cookie;
- an allowed Origin (or Referer fallback);
- the readable CSRF cookie;
- the same token in `X-CSRF-Token`;
- the session-bound CSRF digest stored in PostgreSQL.

The generated `openapi-fetch` middleware handles this automatically. Custom clients must copy the
CSRF cookie value into the header and keep the cookie jar.

## Proxies, rate limits, and secrets

### What belongs in `FORWARDED_ALLOW_IPS`?

Only the IPs/CIDRs of the immediate gateway and every controlled proxy hop. The API uses this trust
boundary to recover the real client address for PostgreSQL rate limits.

- `0.0.0.0/32` trusts only the single address `0.0.0.0`; it is not a wildcard.
- `0.0.0.0/0`, `::/0`, and `*` trust everyone and are rejected in production.
- Do not blindly trust every Docker or corporate network.
- A development Compose proxy may use a controlled project-network CIDR; production should use an
  explicitly managed network/proxy chain.

Inspect the immediate peer and project subnet before configuring them:

```bash
docker network inspect PROJECT_default
docker inspect PROJECT-gateway-1
```

If the proxy is not trusted, authentication still works, but many users may share the proxy's client
key and exhaust one rate-limit bucket together.

Development defaults `DEV_FORWARDED_ALLOW_IPS` to empty rather than guessing a Docker subnet. Set it
only after inspecting the immediate peer; it is unrelated to `origin_not_allowed` and is not needed
to make signup function.

### How should `APP_AUTH_RATE_LIMIT_SECRET` be created?

Generate a stable, environment-specific random value:

```bash
openssl rand -hex 32
```

Store it in the secret manager or untracked `.env`, never in Git. Production rejects the generated
development default and values shorter than 32 bytes. Keep the value stable across replicas and
restarts so all instances derive the same HMAC bucket keys.

### Why am I receiving `429 Too Many Requests` during testing?

Login and signup limits are shared in PostgreSQL. Read the `Retry-After` header and wait for the
window to expire. Wrong login credentials consume attempts; request DTO and Origin rejection happen
before credential verification. Inspect or remove expired buckets with:

```bash
cd backend
uv run content-agent auth purge-expired --dry-run
uv run content-agent auth purge-expired
```

Do not raise production limits merely to hide a broken proxy/client-address configuration.

## Log files and isolation

### Where are backend logs written?

Each process writes to `logs/<domain>/<instance>/` when run from `backend/`. The four rotated
channels are `business.log`, `debug.log`, `error.log`, and `sql.log`. Compose uses
`APP_LOG_ROOT=/app/logs` and persists that directory in the `runtime-logs` named volume.

```bash
cd backend
uv run content-agent config check --json
find logs -type f -maxdepth 4 -print

docker compose exec -T api find /app/logs -type f -maxdepth 4 -print
docker volume inspect PROJECT_runtime-logs
```

The API, CLI, and event relay use different domains. The default instance is the hostname, which
isolates normal Compose containers. Set a stable, unique `APP_LOG_INSTANCE_ID` for every concurrent
same-domain process that shares a host directory.

### Why are logs missing, mixed, or growing unexpectedly?

- Recreate the process after changing `APP_LOG_*`; settings are loaded at startup.
- Confirm the effective root, instance, level, rotation size/count, and SQL switch with
  `content-agent config check --json`.
- A duplicate domain/instance intentionally targets the same files. Assign unique instance IDs
  instead of allowing multiple OS processes to rotate one file set.
- Invalid names, non-writable directories, and symlink or Windows-junction path components fail
  startup rather than silently redirecting logs.
- `debug.log` is populated only at `APP_LOG_LEVEL=DEBUG`; `sql.log` requires
  `APP_LOG_SQL_ENABLED=true`. SQL never appears on the console.

Rotation is bounded per file by `APP_LOG_MAX_BYTES` and `APP_LOG_BACKUP_COUNT`, but the Compose
volume survives `docker compose down`. Ship or back up JSONL externally when retention is required,
and remove the named volume only through an intentional operational cleanup. Do not attach raw log
files to public reports: redaction is defense in depth, not permission to disclose production data.

## Diagnosis and project maintenance

### What should I collect before reporting a Compose/authentication problem?

Use redacted output; never print secrets or complete cookies:

```bash
docker compose ls
docker compose --env-file .env.dev -f docker-compose.dev.yml ps
docker compose --env-file .env.dev -f docker-compose.dev.yml config --quiet
docker compose --env-file .env.dev -f docker-compose.dev.yml exec -T api content-agent config check --json
docker compose --env-file .env.dev -f docker-compose.dev.yml exec -T api printenv \
  APP_ENV APP_ALLOWED_ORIGINS APP_SESSION_COOKIE_SECURE \
  APP_SIGNUP_ENABLED FORWARDED_ALLOW_IPS APP_LOG_ROOT APP_LOG_INSTANCE_ID \
  APP_LOG_LEVEL APP_LOG_SQL_ENABLED
docker compose --env-file .env.dev -f docker-compose.dev.yml logs --tail=100 api frontend
curl -i http://localhost:5173/health/ready
python harness/check.py
```

Every API response includes `X-Request-ID`. When a public response intentionally omits sensitive
validation details, use that identifier to find the matching structured API log. `content-agent config check
--json` reports only a redacted effective configuration summary; it never prints database URLs,
passwords, cookies, session/CSRF tokens, or the rate-limit secret.

Use `HARNESS_STRICT=1` when missing `uv`, npm, or Docker must fail rather than skip:

```bash
HARNESS_STRICT=1 HARNESS_DOCKER=1 python harness/check.py
```

### Why should I commit the generated baseline before local customization?

Project Forge update/add/enable commands require a clean Git worktree. Commit the generated baseline
before changing ports or Compose files so Git provides a recovery point and later three-way updates
can distinguish generated changes from local ones. Never commit `.env`, cookie jars, or secrets.

## Quick error lookup

| Symptom/code | First checks |
|---|---|
| FastAPI reports production mode | Compose file and `fastapi dev` versus `fastapi run` command |
| `origin_not_allowed` | Exact browser scheme/host/port versus API container allowed origins |
| `request_validation_failed` | JSON Content-Type, valid email, password length, `workspaceName`, extra fields |
| `signup_disabled` | `APP_SIGNUP_ENABLED` and whether production registration should be open |
| Signup `201`, session `401` | Secure flag, hostname consistency, stale cookies, same-origin API base URL |
| `csrf_invalid` / authenticated `403` | Session cookie, Origin, CSRF cookie/header pair |
| `429` | `Retry-After`, trusted proxy chain, shared PostgreSQL limiter buckets |
| Settings change ignored | Resolved Compose config and container recreation |
| Logs missing or mixed | Effective log root/domain/instance, unique instance ID, permissions, process recreation |
