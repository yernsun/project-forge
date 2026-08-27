# Changelog

All notable Project Forge changes are documented here. The project follows semantic versioning for
published artifacts; template content identity is tracked separately so controlled updates can
detect rebuilt `0.2.0` installations without changing the public version.

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
