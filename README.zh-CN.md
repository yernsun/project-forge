# Project Forge

Project Forge 用于初始化可治理、可持续升级的前端、后端或全栈工程。它由 Copier 模板、
轻量 Typer CLI 和可安装的 Codex skill 组成；生成后的工程通过 Git 干净工作区和三方合并
接收模板升级。

## 快速开始

```bash
uv sync --all-groups
uv run project-forge doctor
uv run project-forge init ../my-app --name "My App"
uv run project-forge init ../order-service --name "订单服务" --slug order-service
```

也可以直接从本地 Git 仓库通过 `uvx` 运行：

```bash
uvx --from git+file:///absolute/path/to/project-forge project-forge init ../my-app
```

无交互默认值为：`fullstack`、包含示例纵切、关闭认证、关闭事件能力、默认语言 `zh-CN`。
前后端可以分别或同时初始化：

```bash
uv run project-forge init ../api-only --profile backend --evented --no-sample
uv run project-forge init ../ui-only --profile frontend --default-locale en-US
```

首次提交后可单向增加能力：

```bash
uv run project-forge add backend -C ../ui-only
uv run project-forge enable auth -C ../my-app
uv run project-forge update ../my-app
```

升级前必须保持 Git 工作区干净。工程和模板同时修改的文件不会被覆盖，而是生成 `.rej`
供人工处理；工具不会执行 `reset`、`clean` 或任何强制 Git 操作。

完整能力与验证方式见 [README.md](README.md) 和 [docs/architecture.md](docs/architecture.md)。
