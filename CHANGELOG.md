# Changelog

All notable Project Forge changes are documented here. The project follows semantic versioning for
published artifacts; template content identity is tracked separately so controlled updates can
detect rebuilt installations without changing the public version.

## Unreleased

## [0.3.1] - 2026-11-01

### Added

- Bundle the local `primevue-skilld` snapshot and all 148 reference files in generated repositories
  and published packages, linked from frontend rules and the project-specific skill.
- Audit the complete generated backend dependency set, including auth and evented extras, in
  generator CI; fail frontend audits for every reported severity.

### Changed

- Refresh generator and generated-project dependencies and locks, including FastAPI 0.162,
  Pydantic 2.14, Redis client 8.1, Vite 8.3, Vitest 5, Pinia 4, and Nginx 1.30.6.
- Keep the MIT-licensed PrimeVue 4, Themes 1, and PrimeIcons 7 lines. Retain TypeScript 5.9 for
  OpenAPI tooling and Vue Test Utils 2.4 for the supported Node 22.13+/24 runtime floor.
- Override vulnerable glob/minimatch dependencies; preserve the OpenAPI generator's Redocly 1
  interface through a process-local callable-export adapter. Remove unused FastAPI cloud
  deployment dependencies.
- Adapt Redis 8 async typing and missing DLQ fields, and exclude dependency/build caches before
  Copier traverses the template rather than copying them into temporary renders.
- Check the bundled PrimeVue skill in the initialized project during wheel smoke tests, separately
  from the standalone Project Forge skill installation, and trace the failing shell command.

## [0.3.0] - 2026-09-03

### Added

- State schema v3 and configurable generated console commands through `init --command-name` and
  clean-Git `configure --command-name`; new projects default to their project slug.
- Stable JSON results for update preview/apply, including template identity, sorted path sets, and
  explicit breaking-change records.
- Deterministic baseline archives, bounded extraction resources, and symlink/Windows-junction
  protection for managed files, metadata, and conflict diagnostics.
- Parallel root quality tests, focused Python compatibility gates, an independent OpenAPI gate, and
  isolated wheel smoke tests for default and custom generated commands.
- Generated backend logging with rotated domain/instance file isolation, separate business,
  debug, error, and parameter-free SQL channels, bounded correlation context, recursive redaction,
  plus dedicated observability rules, skill, documentation, tests, and static harness enforcement.
- Generated frontend UUID compatibility for LAN HTTP origins, preserving native `randomUUID()` when
  available and otherwise deriving RFC 4122 version 4 UUIDs from `crypto.getRandomValues()`.

### Changed

- Schema v1/v2 backend projects hard-switch from the generated `app` command to their project slug
  on the next `update`, `add`, `enable`, or `configure`; no compatibility alias is emitted and
  user-owned scripts remain untouched.
- No-op controlled updates now return `up_to_date` without rewriting state or baseline files.
- API, Service, worker, lifecycle, and repository-connection instrumentation now shares one stable
  event/outcome model; Services emit success only after commit and worker success follows ACK.

## [0.2.0] - 2026-08-27

### Added

- Python 3.11–3.14 and Node 22.13+/24 LTS compatibility contracts with maintained ESLint 10 tooling.
- Global CLI, monotonic project evolution, atomic three-way updates, and template content digests.
- Optional PostgreSQL authentication/workspaces and Redis Streams event processing.
- Configurable loopback-safe development Compose plus LAN examples using `172.20.0.0/16` addresses.
- Redacted configuration diagnostics, request correlation, structured logs, coverage gates,
  dependency audits, cross-platform generator smoke tests, and production-topology smoke tests.
- Bounded outbox/Redis failure recovery and a pytest 9 upgrade that removes the locked
  `PYSEC-2026-1845` development dependency vulnerability.
- Bilingual README and FAQ documentation.

[0.2.0]: https://github.com/yernsun/project-forge/releases/tag/v0.2.0
[0.3.0]: https://github.com/yernsun/project-forge/releases/tag/v0.3.0
[0.3.1]: https://github.com/yernsun/project-forge/releases/tag/v0.3.1
