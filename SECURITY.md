# Security policy

## Supported version

Security fixes currently target Project Forge `0.2.0` and projects updated with the latest packaged
`0.2.0` template digest. Install the latest tool build and run `project-forge update PATH` before
reporting a generated-project issue.

## Reporting

Do not open public issues for suspected vulnerabilities or include credentials, cookies, database
URLs, private IP inventories, or production logs in a report. Use the repository's private GitHub
security advisory flow and include only a minimal redacted reproduction.

The baseline authentication feature does not include email verification, password reset, OIDC,
MFA, or RBAC. Their absence is a product boundary, not a security control.
