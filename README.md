# Project Forge

Project Forge generates governed frontend, backend, or full-stack repositories and keeps them
evolvable through clean-Git, three-way template updates. It combines a Copier template with a
small Typer CLI and ships a Codex skill for repeatable initialization.

## Quick start

```bash
uv sync --all-groups
uv run project-forge doctor
uv run project-forge init ../my-app --name "My App"
uv run project-forge init ../order-service --name "订单服务" --slug order-service
```

Run from a local Git checkout without installing it permanently:

```bash
uvx --from git+file:///absolute/path/to/project-forge project-forge init ../my-app
```

The non-interactive defaults are `fullstack`, sample vertical slice enabled, no authentication,
no event pipeline, and `zh-CN` as the initial locale. Override any choice explicitly:

```bash
uv run project-forge init ../api-only --profile backend --evented --no-sample
uv run project-forge init ../ui-only --profile frontend --default-locale en-US
```

After the first commit, capabilities can only grow:

```bash
uv run project-forge add backend -C ../ui-only
uv run project-forge enable auth -C ../my-app
uv run project-forge update ../my-app
```

Updates require a clean Git worktree. Files changed both by the project and by the template are
left untouched and receive a neighboring `.rej` file. Project Forge never calls Git reset, clean,
or force operations.

## Generated baselines

- Python 3.13, FastAPI, Pydantic v2, Psycopg 3, PostgreSQL 16
- Node 22, Vue 3, Vite, TypeScript, PrimeVue, Pinia, Vue Query
- `zh-CN` and `en-US` i18n with persisted locale and PrimeVue locale synchronization
- Service-owned transactions, single-use async Unit of Work, repository-only persistence
- Fixed SQL variants for hot paths and typed, whitelisted composable SQL for complex filters
- Immutable checksum-validated migration DAG; startup validates but never migrates
- Optional opaque session authentication and optional outbox/Redis Streams workers
- Docker development/production topology, Nginx same-origin proxy, GitHub Actions, and harness

See [README.zh-CN.md](README.zh-CN.md) and [docs/architecture.md](docs/architecture.md).

## Validation

```bash
uv run --frozen python harness/check.py
```

The test matrix renders every valid profile/feature/locale combination. Docker acceptance is a
separate check because it requires a running Docker engine.
