# Security policy

## Supported version

Security fixes currently target Project Forge `0.3.0` and projects updated with the latest packaged
`0.3.0` template digest. Install the latest tool build and run `project-forge update PATH` before
reporting a generated-project issue.

Controlled updates reject symbolic links and Windows junctions across managed files and metadata,
bound baseline archive resources before extraction, and write conflict diagnostics only beneath a
verified real project root.

Generated backends isolate rotated logs by process domain and instance, reject symlink/junction log
paths, recursively redact sensitive field names, omit raw exception values and SQL parameters, and
cap strings, collections, nesting, stack frames, and complete JSONL records. Logs are diagnostic;
security-relevant facts that require durable audit semantics must remain transactional data.

## Reporting

Do not open public issues for suspected vulnerabilities or include credentials, cookies, database
URLs, private IP inventories, or production logs in a report. Use the repository's private GitHub
security advisory flow and include only a minimal redacted reproduction.

The baseline authentication feature does not include email verification, password reset, OIDC,
MFA, or RBAC. Their absence is a product boundary, not a security control.
