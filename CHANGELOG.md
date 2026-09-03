# Changelog

All notable Project Forge changes are documented here. The project follows semantic versioning for
published artifacts; template content identity is tracked separately so controlled updates can
detect rebuilt installations without changing the public version.

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

### Changed

- Schema v1/v2 backend projects hard-switch from the generated `app` command to their project slug
  on the next `update`, `add`, `enable`, or `configure`; no compatibility alias is emitted and
  user-owned scripts remain untouched.
- No-op controlled updates now return `up_to_date` without rewriting state or baseline files.

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
