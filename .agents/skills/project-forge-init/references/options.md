# CLI options

Create projects:

```bash
project-forge init PATH --profile frontend
project-forge init PATH --profile backend --evented
project-forge init PATH --profile fullstack --auth --default-locale en-US
project-forge init PATH --name "订单服务" --slug order-service
project-forge init PATH --name "Content Agent" --command-name content-agent
```

Defaults are full-stack, no auth, no event pipeline, and `zh-CN`. When `--sample`/`--no-sample` is
omitted, backend and full-stack projects include the sample while frontend-only projects do not.

After committing the generated baseline:

```bash
project-forge add frontend -C PATH
project-forge add backend -C PATH
project-forge enable auth -C PATH
project-forge enable evented -C PATH
project-forge enable sample -C PATH
project-forge configure --command-name NAME -C PATH
project-forge update PATH
project-forge update --check PATH
project-forge update PATH --check --json
```

`auth` and `evented` require a backend. Additions are monotonic. Updates require a clean Git
worktree and preserve double-modified files by writing neighboring `.rej` files. Generated commands
default to the project slug and normalize explicit values to lowercase hyphen form. Schema v1/v2
backend projects report and hard-switch the historical `app` command on their next mutation; do not
add an alias or rewrite user-owned scripts.

Inspect prerequisites or machine-readable status with:

```bash
project-forge doctor PATH
project-forge doctor PATH --json
project-forge doctor PATH --require-docker
```
