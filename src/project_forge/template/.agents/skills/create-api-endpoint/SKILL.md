---
name: create-api-endpoint
description: Add or modify FastAPI endpoints, DTOs, dependencies, and frontend-facing contracts in this generated project.
---

Read the API, model, and architecture rules. Define strict request/response DTOs, place the router
prefix and tags on the router, use `Annotated` dependencies, and delegate the use case to a Service.
Rely on request middleware for access logs; add only stable transport rejection context and never
log bodies or headers. Add API tests and regenerate frontend OpenAPI types when the public contract
changes.
