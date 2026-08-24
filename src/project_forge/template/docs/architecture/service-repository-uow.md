# Service, Repository, and Unit of Work

The API creates Services, not repositories. A Service opens one Unit of Work for a use case. The
Unit of Work borrows one Psycopg connection, opens the transaction, creates repositories, and then
commits or rolls back as its context exits. It cannot be reused or crossed into another async task.

Repositories have no transaction methods and no outbound integrations. They execute SQL, map rows,
and return domain values. Cross-repository orchestration stays in the Service.

The dependency direction is enforced rather than conventional: domain modules import no framework
or infrastructure package; API modules import Services rather than repositories or database types;
Services import Unit of Work and domain types but no FastAPI or Psycopg symbols. Repository and
database-adapter modules are the only places that execute SQL. Run `python harness/check.py` after
moving code between layers so `check_architecture.py` can catch boundary regressions immediately.
