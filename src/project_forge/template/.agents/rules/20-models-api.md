# Models and API

- Use Pydantic v2 with strict project base models, explicit `Field` declarations, and `extra=forbid`.
- Python names are snake_case; API aliases are camelCase.
- Serialize external payloads with aliases and reject unknown fields.
- Use timezone-aware timestamps and `Decimal` for monetary or quantity values.
- FastAPI parameters and dependencies use `Annotated`; routers own their prefix and tags.
