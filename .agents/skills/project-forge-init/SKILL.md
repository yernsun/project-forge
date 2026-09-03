---
name: project-forge-init
description: Initialize or evolve a governed frontend, backend, or full-stack repository with Project Forge. Use for new project scaffolding, adding a missing frontend/backend, or enabling auth, evented processing, and sample capabilities; do not use to remove capabilities.
---

# Project Forge Init

Use the `project-forge` CLI as the only project mutation boundary.

1. Run `project-forge doctor [PATH]` and report missing required tools. Use `--json` for automation
   and `--require-docker` when Compose validation is part of acceptance. Docker may be deferred only
   when the user accepts that Compose validation will remain pending.
2. Reuse choices already supplied by the user. Otherwise determine the destination, project name,
   profile (`frontend`, `backend`, or `fullstack`), and optional `auth`, `evented`, `sample`, and
   default locale choices. The generated command defaults to the project slug; pass
   `--command-name` only when the user wants a different command.
3. For a new repository, run `project-forge init`. Do not add undeclared optional capabilities.
4. Inspect `.project-forge.yml`, the generated directory set, and Git status.
5. Run `python harness/check.py` in the generated repository. It enforces architecture, structured
   logging, SQL, i18n, OpenAPI drift, backend tests, and frontend checks according to the selected
   profile. Run Docker checks when Docker is available and the selected profile emits containers.
6. For an existing generated repository, require a clean Git worktree before `add`, `enable`,
   `configure`, or `update`. Use `configure --command-name` for command changes, including
   frontend-only preconfiguration. Never bypass the guard. An update conflict must leave all
   managed files, state, and baseline unchanged and create only `.rej` files; report each rejection
   for manual resolution.
7. Do not infer permission to remove a component or capability; Project Forge intentionally supports
   monotonic additions only.

Read [references/options.md](references/options.md) for exact commands and constraints.
