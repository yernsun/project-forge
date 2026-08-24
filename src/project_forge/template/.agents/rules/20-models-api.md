# Models and API

- Use Pydantic v2 with strict project base models, explicit `Field` declarations, and `extra=forbid`.
- Python names are snake_case; API aliases are camelCase.
- Serialize external payloads with aliases and reject unknown fields.
- Keep API DTOs, public identities, credential records, domain entities, and persistence rows as
  separate model responsibilities. Mark secrets and hashes `repr=False`.
- Do not apply blanket whitespace stripping to credentials; validate passwords with `SecretStr` at
  the transport boundary and reveal them only at the hashing call.
- Use timezone-aware timestamps and `Decimal` for monetary or quantity values.
- FastAPI parameters and dependencies use `Annotated`; routers own their prefix and tags.
- Every endpoint declares a response type/model; error responses expose stable codes for clients.
