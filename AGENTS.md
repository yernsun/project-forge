# Project Forge Agent Guide

Project Forge is an independent project generator. Preserve its ability to render every valid
profile and feature combination.

## Mandatory boundaries

- The packaged template under `src/project_forge/template/` is the rendering source of truth.
- Keep the root `copier.yml` questions aligned with the packaged template configuration.
- Generated backend transactions belong to Services; repositories only execute SQL and map rows.
- Generated SQL uses Psycopg named parameters and safe composables. Never interpolate values,
  identifiers, sort direction, or raw user fragments.
- Generated frontend external state uses Vue Query; Pinia is reserved for client-owned state.
- Every user-facing frontend string must exist in both `zh-CN` and `en-US` locale files.
- Capability changes are monotonic. Do not add feature-removal commands.
- Updates require clean Git and emit `.rej` on conflicts. Never introduce reset/clean/force logic.
- Do not copy names, package paths, abstractions, or custom SQL wrappers from a source application.

## Validation

Run `uv run --frozen python harness/check.py`. Changes to the template must also render the full combination
matrix. If Docker is available, render a full-stack fixture and run both Compose configurations.
