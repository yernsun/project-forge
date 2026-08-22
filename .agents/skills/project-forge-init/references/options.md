# CLI options

Create projects:

```bash
project-forge init PATH --profile frontend
project-forge init PATH --profile backend --evented
project-forge init PATH --profile fullstack --auth --default-locale en-US
project-forge init PATH --name "订单服务" --slug order-service
```

Defaults are full-stack, no auth, no event pipeline, sample enabled, and `zh-CN`.

After committing the generated baseline:

```bash
project-forge add frontend -C PATH
project-forge add backend -C PATH
project-forge enable auth -C PATH
project-forge enable evented -C PATH
project-forge enable sample -C PATH
project-forge update PATH
```

`auth` and `evented` require a backend. Additions are monotonic. Updates require a clean Git
worktree and preserve double-modified files by writing neighboring `.rej` files.
