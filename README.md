# Project Forge

[简体中文](README.zh-CN.md) | English

Project Forge is a versioned project generator for governed frontend, backend, and full-stack
repositories. It creates an opinionated engineering baseline and keeps that baseline evolvable with
clean-Git, all-or-nothing, three-way template updates.

The public interface is the `project-forge` CLI. Generated repositories include architecture rules,
Codex skills, a validation harness, Docker topology, CI, bilingual i18n, and optional authentication
or event processing.

For generated-project Docker, LAN, Origin, cookie, authentication, and environment troubleshooting,
read the [FAQ](FAQ.md) ([简体中文](FAQ.zh-CN.md)).

## What gets generated

| Profile | Frontend | Backend | Default sample | Typical use |
|---|---:|---:|---:|---|
| `frontend` | Yes | No | Off | SPA backed by an existing API |
| `backend` | No | Yes | On | API, worker, or service repository |
| `fullstack` | Yes | Yes | On | Same-origin web application |

Optional capabilities are additive:

| Capability | Requires | Adds |
|---|---|---|
| `auth` | Backend | PostgreSQL opaque sessions, CSRF, workspaces, rate limiting, login/signup UI |
| `evented` | Backend | PostgreSQL outbox, Redis Streams foundations, stable event-ID deduplication |
| `sample` | Selected profile | Tested Items slice showing API → Service → UoW → Repository boundaries |

Generated backends support Python `>=3.11` and use Python 3.13 in Docker by default, with FastAPI,
Pydantic v2, Psycopg 3, PostgreSQL 16, forward migrations, and repository-owned SQL. Generated
frontends support Node LTS `>=22.13 <23 || >=24 <25` and use Node 24 for Docker and generated CI,
with Vue 3, Vite, TypeScript, PrimeVue using Aura with persisted system/light/dark switching,
Vue Query, Pinia for client-owned state, and
`zh-CN`/`en-US` catalogs.

Every generated backend also includes process-isolated rotated JSONL logs at
`logs/<domain>/<instance>/`, separate business/debug/error/SQL channels, request and event
correlation, parameter-free SQL timing, recursive secret redaction, an observability skill/rule,
and a static logging contract in the generated harness.

## Prerequisites

| Tool | When required | Supported version |
|---|---|---|
| Python | Always | `>=3.11` |
| uv | Always | Current stable |
| Git | Managed evolution | Current stable |
| Node.js and npm | Frontend/full-stack | Node LTS `>=22.13 <23 || >=24 <25` |
| Docker Engine and Compose v2 | Compose workflows | Current stable |

Check the machine before creating a project:

```bash
project-forge doctor
project-forge doctor --require-docker
```

Without a path, `doctor` checks the default full-stack toolchain. With a generated project path, it
uses the persisted profile and verifies `.project-forge.yml`, the update baseline, Git, and worktree
cleanliness.

## Install the CLI

The recommended installation is an isolated [uv tool](https://docs.astral.sh/uv/guides/tools/):

```bash
uv tool install --python 3.11 git+https://github.com/yernsun/project-forge.git
project-forge --version
```

For a private SSH checkout:

```bash
uv tool install --python 3.11 git+ssh://git@github.com/yernsun/project-forge.git
```

If the command is not on `PATH`, run `uv tool update-shell` and open a new terminal. Use
`uv tool dir --bin` to inspect the executable directory.

```bash
uv tool upgrade project-forge
uv tool uninstall project-forge
```

When installed in the current Python environment, the console and module entry points are
equivalent:

```bash
project-forge --version
python -m project_forge --version
```

For development of Project Forge itself:

```bash
git clone https://github.com/yernsun/project-forge.git
cd project-forge
uv sync --all-groups
uv run project-forge --version
```

Install the checkout as an editable isolated tool when desired:

```bash
uv tool install --python 3.11 --editable .
```

Python 3.11 through 3.14 are exercised in Project Forge CI. Python 3.13 remains the generated
backend container default. Frontend CI exercises the currently supported Node 22 and Node 24 LTS
lines only; the checked-in Node 22 type definitions intentionally restrict code to the oldest
supported API surface. Node 24 is the production default. Odd-numbered releases and a new even
release before it reaches LTS are outside the support contract; see the
[Node.js release table](https://nodejs.org/en/about/previous-releases).

## Five-minute quick start

Create a full-stack app with the sample slice and database-backed authentication:

```bash
project-forge doctor --require-docker
project-forge init ../acme-console --name "Acme Console" --auth
cd ../acme-console
git add .
git commit -m "chore: initialize with Project Forge"
python harness/check.py
cp .env.dev.example .env.dev
docker compose --env-file .env.dev -f docker-compose.dev.yml up --build
```

Open:

- frontend: [http://localhost:5173](http://localhost:5173)
- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- liveness: [http://localhost:8000/health/live](http://localhost:8000/health/live)
- readiness: [http://localhost:8000/health/ready](http://localhost:8000/health/ready)

The generated Git repository is not committed automatically. Commit the baseline before `add`,
`enable`, or `update`; managed evolution requires a clean worktree.

## Initialize a project

```text
project-forge init DESTINATION [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--name TEXT` | Directory name | Human-facing project name |
| `--slug TEXT` | Slugified name | Lowercase ASCII filesystem/cookie/Compose slug |
| `--command-name TEXT` | Project slug | Generated backend console command; normalized to lowercase hyphen form |
| `--profile frontend\|backend\|fullstack` | `fullstack` | Components to generate |
| `--auth / --no-auth` | Off | Enable PostgreSQL session authentication |
| `--evented / --no-evented` | Off | Enable outbox and Redis Streams |
| `--sample / --no-sample` | Profile-aware | Include or omit sample business code |
| `--default-locale zh-CN\|en-US` | `zh-CN` | Initial UI locale |
| `--git / --no-git` | Git enabled | Initialize a Git repository |

When `--sample` is omitted, backend/full-stack projects include it and frontend-only projects do
not. Explicit `--sample` or `--no-sample` always wins. `auth` and `evented` require a backend.

### Initialization examples

```bash
# Full-stack auth app with an English default locale
project-forge init ../customer-portal \
  --name "Customer Portal" \
  --profile fullstack \
  --auth \
  --default-locale en-US

# Backend event processor without sample code
project-forge init ../billing-events \
  --name "Billing Events" \
  --profile backend \
  --evented \
  --no-sample

# Display name/slug defaults to `content-agent`; an explicit command can differ
project-forge init ../content-agent \
  --name "Content Agent" \
  --profile backend \
  --command-name content-agent-worker

# Minimal frontend for an existing API
project-forge init ../operations-ui \
  --name "Operations UI" \
  --profile frontend

# Frontend with the sample UI and external API proxy
project-forge init ../items-ui --profile frontend --sample

# Non-ASCII display name with an explicit safe slug
project-forge init ../order-service \
  --name "订单服务" \
  --slug order-service \
  --profile backend

# Disposable CI fixture without Git initialization
project-forge init generated \
  --profile fullstack \
  --auth \
  --sample \
  --no-git
```

## Inspect an existing project

```bash
# Persisted profile, capabilities, locale, and template version
project-forge features ../customer-portal

# Human-readable and machine-readable diagnostics
project-forge doctor ../customer-portal
project-forge doctor ../customer-portal --require-docker
project-forge doctor ../customer-portal --json
```

The JSON form is stable and suited to automation:

```json
{
  "ok": true,
  "project": "/absolute/path/to/customer-portal",
  "checks": [
    {
      "name": "python",
      "status": "pass",
      "required": true,
      "version": "Python 3.11.16",
      "message": "meets >=3.11"
    }
  ]
}
```

## Add components and capabilities

Project Forge evolves repositories monotonically: it can add capabilities, but intentionally does
not remove them.

```bash
# frontend → fullstack
project-forge add backend -C ../operations-ui

# backend → fullstack
project-forge add frontend -C ../billing-events

# Optional capabilities
project-forge enable auth -C ../operations-ui
project-forge enable evented -C ../operations-ui
project-forge enable sample -C ../operations-ui
```

Recommended workflow:

```bash
cd ../operations-ui
git status --short
git add .
git commit -m "chore: checkpoint before Project Forge evolution"

project-forge add backend
project-forge enable auth

python harness/check.py
git diff --check
git status --short
```

`auth` and `evented` cannot be enabled on a frontend-only project; add the backend first. User-owned
files are preserved, while managed files are reconciled against the recorded baseline.

## Configure generated commands

New projects default the backend console command to the project slug, so `Content Agent` generates
`content-agent`, while Python imports remain under `app` and FastAPI remains `app.main:app`. Change
the console command through the same clean-Git, atomic update boundary:

```bash
project-forge configure --command-name content-agent-cli -C ../content-agent
```

`configure` also works before a backend exists: a frontend-only project persists the name and uses
it when `project-forge add backend` is run later. It never rewrites user-owned scripts.

## Upgrade a generated project

`update --check` renders and compares the project with the template bundled in the currently
installed CLI. State schema 3 records the command name and a deterministic template digest, so
refreshed template content is detected even when the public version is unchanged. The command never contacts GitHub
or another remote and never writes managed files, state, baseline, or `.rej` files:

```bash
uv tool upgrade project-forge
project-forge update --check ../customer-portal
project-forge update --check --json ../customer-portal
project-forge update ../customer-portal
```

Schema v1/v2 backend projects report the intentional `app → <project-slug>` breaking change before
updating. Running `update`, `add`, `enable`, or `configure` performs that hard switch without an
`app` alias; user-owned scripts are left untouched. JSON results stably report status, project,
target template identity, identity drift, sorted changed/conflict/rejection paths, and breaking
changes while preserving exit codes 0/1/2/3.

Updates require clean Git and use a two-phase, all-or-nothing process. If any managed file conflicts,
all managed files, state, and baseline remain unchanged; only neighboring `.rej` files are written.
Resolve a rejection by applying the intended change manually, removing the `.rej` file, committing
the resolution, and rerunning `project-forge update`. Project Forge never invokes `git reset`,
`git clean`, or force operations.

Baselines are byte-deterministic and preserve normalized executable permissions. Unchanged updates
write nothing. Archive extraction is bounded to 64 MiB compressed, 4,096 files, 16 MiB per file,
and 128 MiB uncompressed; managed writes reject symbolic links and Windows junctions.

## Use the bundled Codex skill

```bash
# Repository scope: .agents/skills/project-forge-init
cd ../customer-portal
project-forge install-skill

# User scope: ~/.agents/skills/project-forge-init
project-forge install-skill --scope user

# Explicit destination or replacement
project-forge install-skill --destination .agents/skills/custom-project-forge
project-forge install-skill --overwrite
```

For safety, overwrite refuses symbolic-link or junction destinations and parent paths.

## Work inside a generated repository

Every generated README contains profile-specific commands. The common validation entry point is:

```bash
python harness/check.py
```

The harness runs the applicable architecture, SQL, i18n, backend, frontend, build, test, and OpenAPI
drift checks. Strict CI-style validation also checks both Compose files:

```bash
HARNESS_STRICT=1 HARNESS_DOCKER=1 python harness/check.py
```

Start the generated development stack:

```bash
cp .env.dev.example .env.dev
docker compose --env-file .env.dev -f docker-compose.dev.yml up --build
docker compose --env-file .env.dev -f docker-compose.dev.yml down
```

Without the explicit development file, all published ports default to `127.0.0.1`; the active
example values are loopback-safe too. Its commented LAN recipe exposes only the frontend and uses
`172.20.0.10` as a documentation-only private address; replace it locally. Production `.env` values
cannot leak into the isolated `DEV_*` settings. The frontend keeps API requests same-origin and
rejects a cross-origin `VITE_API_BASE_URL`.

Generated backends also expose redacted runtime diagnostics, and evented projects include bounded
failure recovery controls:

```bash
cd backend
uv run content-agent config check --json
uv run content-agent events status --json
uv run content-agent events retry-failed --limit 100 --dry-run
```

Every API response carries `X-Request-ID`; structured logs use the same value without recording
request bodies or credentials.

Production Compose expects an external TLS terminator and binds its gateway to `127.0.0.1:8080` by
default. Replace every placeholder before starting:

```bash
cp .env.example .env
docker compose config
docker compose up -d --build
```

Authentication deployments require HTTPS origins, Secure cookies, a unique rate-limit HMAC secret,
and an explicit trusted-proxy chain. Read the generated `docs/architecture/auth.md` before
production use.

## CLI exit codes

| Code | Meaning |
|---:|---|
| `0` | Success; `update --check` found no installed-template difference |
| `1` | Required doctor check failed, or `update --check` found an update |
| `2` | Invalid usage, project state, dirty Git, or another runtime error |
| `3` | Update conflict; only `.rej` files were written |

## Troubleshooting

For generated-project runtime and authentication failures, start with the bilingual
[FAQ](FAQ.md).

### `project-forge: command not found`

Run `uv tool update-shell`, inspect `uv tool dir --bin`, and open a new terminal.

### The installed template appears stale

```bash
uv tool upgrade --reinstall project-forge
project-forge --version
git -C PATH status --short
project-forge update PATH
python3 PATH/harness/check.py
```

If reinstalling the recorded tool source does not refresh a Git installation, force-install the
current branch explicitly:

```bash
uv tool install --force --python 3.11 git+https://github.com/yernsun/project-forge.git
```

`update --check` intentionally does not query a remote repository. After reinstalling the tool, it
uses the stored template digest plus an actual dry render/three-way comparison, so it can report a
same-version refresh. Run `project-forge update PATH` when the check reports a difference.
The normal clean-Git and all-or-nothing conflict safeguards still apply.

### Managed evolution reports a dirty worktree

Review `git status --short` and commit or deliberately stash the changes. Do not bypass the guard:
the committed state is the recovery point for controlled evolution.

### Docker is only a warning

Docker is optional for normal `doctor` runs. Use `--require-docker` when Compose validation is part
of acceptance; the Docker CLI, Compose v2, and daemon must all be available.

### Frontend tools reject the Node version

Use Node LTS `>=22.13 <23 || >=24 <25`. Node 22.0–22.12 is below the maintained
[ESLint 10 runtime floor](https://eslint.org/docs/latest/use/getting-started); Vite itself permits
22.12+. Node 23 and 25 are EOL, while Node 26 remains outside
the support contract until a future Project Forge release explicitly adopts it after it reaches LTS.

## Develop Project Forge

```bash
uv sync --all-groups
uv run --frozen python harness/check.py
uv run --frozen python harness/check.py --mode quality
uv run --frozen python harness/check.py --mode contracts
uv run --frozen python harness/check.py --mode compatibility
uv run --frozen pip-audit
cd src/project_forge/template/frontend
npm audit --audit-level=high
```

Root tests enforce branch coverage, generated strict harnesses enforce backend/frontend coverage,
and CI adds macOS/Windows CLI smoke tests, Python 3.11–3.14, supported Node LTS lines, dependency
audits, a non-TLS internal production-Compose readiness smoke, wheel isolation, and authenticated
Compose E2E. Release tags are additionally checked against `pyproject.toml`; the release workflow
builds checksums, an SBOM, and provenance for the `0.3.0` release.

After an intentional API route or DTO change:

```bash
uv run --frozen python harness/manage_openapi_contracts.py --refresh
uv run --frozen python harness/manage_openapi_contracts.py --check
```

The render matrix covers every valid profile, feature, sample, and locale combination. See the
[architecture overview](docs/architecture.md) for generator boundaries and the generated
`docs/README.md` for application architecture.
