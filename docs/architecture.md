# Architecture

Project Forge has three layers:

1. `ProjectState` validates profile and monotonic capability constraints.
2. Copier renders an isolated desired project from the packaged template.
3. The update engine compares the previous template baseline, the current project, and the new
   desired render. One-sided changes apply automatically; double-sided changes become `.rej`.

The generated backend follows API → Service → Unit of Work → Repository. A Service opens the
transaction, a single-use task-bound Unit of Work owns one Psycopg connection and repository
lifecycle, and repositories contain all persistence SQL and row mapping.

Conditional SQL deliberately uses two modes. Stable hot paths keep fixed statements for predictable
query plans. Complex searches accept a typed filter object, append predicates in canonical order,
bind named values, and whitelist every identifier and sort direction through `psycopg.sql`.
Highly ad-hoc shapes opt out of preparation; stable shapes retain driver-managed preparation.

The generated frontend keeps server state in Vue Query, client-owned state in Pinia, DTO types from
OpenAPI, and locale state in one i18n module that also updates PrimeVue's locale object.
