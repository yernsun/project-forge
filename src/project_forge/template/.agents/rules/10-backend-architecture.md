# Backend architecture

- API handlers parse and serialize; they do not manage transactions or issue SQL.
- API modules depend on Services, never concrete repositories, Psycopg, or database connections.
- Services open Unit of Work contexts and coordinate repositories.
- Services contain no FastAPI transport types and do not import concrete repository modules.
- Each Unit of Work is single-use and bound to one async task.
- Repositories execute SQL and map persistence rows only. They do not commit.
- Domain modules stay independent from API, Service, Repository, Unit of Work, and database packages.
- Startup validates migration history but never applies migrations.
- `harness/check_architecture.py` enforces these boundaries; exceptions belong in adapters, not
  inline suppressions.
