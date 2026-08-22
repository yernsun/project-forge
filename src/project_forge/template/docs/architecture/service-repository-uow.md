# Service, Repository, and Unit of Work

The API creates Services, not repositories. A Service opens one Unit of Work for a use case. The
Unit of Work borrows one Psycopg connection, opens the transaction, creates repositories, and then
commits or rolls back as its context exits. It cannot be reused or crossed into another async task.

Repositories have no transaction methods and no outbound integrations. They execute SQL, map rows,
and return domain values. Cross-repository orchestration stays in the Service.
