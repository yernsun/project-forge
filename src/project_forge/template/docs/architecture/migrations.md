# Migrations

Migrations are immutable nodes with an ID, dependency list, checksum, and one forward SQL payload.
The runner topologically sorts the DAG, rejects missing dependencies or cycles, verifies checksums
for applied nodes, and applies pending nodes under a PostgreSQL advisory lock.

There is intentionally no automatic startup migration and no `down` operation. Application startup
only validates that applied history is known and unmodified. Operators run `app migrate status`,
`app migrate validate`, and `app migrate up` explicitly.
