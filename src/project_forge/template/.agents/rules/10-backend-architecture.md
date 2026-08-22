# Backend architecture

- API handlers parse and serialize; they do not manage transactions or issue SQL.
- Services open Unit of Work contexts and coordinate repositories.
- Each Unit of Work is single-use and bound to one async task.
- Repositories execute SQL and map persistence rows only. They do not commit.
- Startup validates migration history but never applies migrations.
