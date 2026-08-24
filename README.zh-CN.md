# Project Forge

简体中文 | [English](README.md)

Project Forge 是一个带版本管理的工程生成器，用于创建可治理、可持续演进的前端、后端
和全栈代码库。它提供明确的工程基线，并通过 Git 干净工作区、三方比较和全量原子更新
持续接收模板升级。

正式入口是 `project-forge` CLI。生成工程自带架构 rules、Codex skills、验证 harness、
Docker 拓扑、CI、双语 i18n，以及可选的认证与事件处理能力。

## 生成内容

| Profile | 前端 | 后端 | sample 默认值 | 适用场景 |
|---|---:|---:|---:|---|
| `frontend` | 有 | 无 | 关闭 | 使用既有 API 的 SPA |
| `backend` | 无 | 有 | 开启 | API、worker 或服务工程 |
| `fullstack` | 有 | 有 | 开启 | 同源全栈 Web 应用 |

能力只能单向增加：

| 能力 | 依赖 | 新增内容 |
|---|---|---|
| `auth` | 后端 | PostgreSQL opaque session、CSRF、workspace、限流、登录注册 UI |
| `evented` | 后端 | PostgreSQL outbox、Redis Streams 基础设施、稳定 event ID 幂等 |
| `sample` | 所选 profile | 展示 API → Service → UoW → Repository 的 Items 纵切 |

后端支持 Python `>=3.11`，Docker 默认使用 Python 3.13，并包含 FastAPI、Pydantic v2、
Psycopg 3、PostgreSQL 16、前向迁移和 Repository SQL；前端支持 Node `>=22.12,<27`，
Docker 和生成项目 CI 默认使用 Node 24，并包含 Vue 3、Vite、TypeScript、PrimeVue、
Vue Query、仅保存客户端状态的 Pinia，以及 `zh-CN`/`en-US` 语言包。

## 环境要求

| 工具 | 何时必需 | 版本 |
|---|---|---|
| Python | 始终 | `>=3.11` |
| uv | 始终 | 当前稳定版 |
| Git | 受管演进 | 当前稳定版 |
| Node.js 与 npm | frontend/fullstack | Node `>=22.12,<27` |
| Docker Engine 与 Compose v2 | 容器工作流 | 当前稳定版 |

创建工程前检查当前机器：

```bash
project-forge doctor
project-forge doctor --require-docker
```

不传路径时，`doctor` 按默认 fullstack 检查；传入生成工程路径后，会读取保存的 profile，
并检查 `.project-forge.yml`、升级 baseline、Git 仓库及工作区是否干净。

## 安装 CLI

推荐通过独立的 [uv tool](https://docs.astral.sh/uv/guides/tools/) 安装：

```bash
uv tool install --python 3.11 git+https://github.com/yernsun/project-forge.git
project-forge --version
```

私有 SSH 仓库：

```bash
uv tool install --python 3.11 git+ssh://git@github.com/yernsun/project-forge.git
```

若 shell 找不到命令，执行 `uv tool update-shell`，通过 `uv tool dir --bin` 查看目录，
然后打开新终端。

```bash
uv tool upgrade project-forge
uv tool uninstall project-forge
```

当 Project Forge 安装在当前 Python 环境中时，控制台命令与模块入口等价：

```bash
project-forge --version
python -m project_forge --version
```

开发 Project Forge 本身：

```bash
git clone https://github.com/yernsun/project-forge.git
cd project-forge
uv sync --all-groups
uv run project-forge --version
```

也可以将当前检出安装为可编辑的独立工具：

```bash
uv tool install --python 3.11 --editable .
```

Project Forge CI 覆盖 Python 3.11～3.14，生成后端容器仍默认使用 Python 3.13。前端 CI
覆盖 Node 22～26 的每个主版本；保留 Node 22 类型定义是为了将代码限制在最低支持版本
已有的 API 表面。生产默认使用 Node 24。Node 23 和 25 已 EOL，只作为兼容目标；状态见
[Node.js 发布表](https://nodejs.org/en/about/previous-releases)。

## 五分钟快速开始

创建包含 sample 和数据库认证的全栈工程：

```bash
project-forge doctor --require-docker
project-forge init ../acme-console --name "Acme Console" --auth
cd ../acme-console
git add .
git commit -m "chore: initialize with Project Forge"
python harness/check.py
docker compose -f docker-compose.dev.yml up --build
```

访问：

- 前端：[http://localhost:5173](http://localhost:5173)
- API 文档：[http://localhost:8000/docs](http://localhost:8000/docs)
- 存活检查：[http://localhost:8000/health/live](http://localhost:8000/health/live)
- 就绪检查：[http://localhost:8000/health/ready](http://localhost:8000/health/ready)

工具会初始化 Git，但不会自动提交。首次执行 `add`、`enable` 或 `update` 前，必须提交
生成基线并保持工作区干净。

## 初始化工程

```text
project-forge init DESTINATION [OPTIONS]
```

| 选项 | 默认值 | 含义 |
|---|---|---|
| `--name TEXT` | 目录名 | 面向用户的工程名 |
| `--slug TEXT` | 根据名称生成 | 小写 ASCII 文件系统/Cookie/Compose 标识 |
| `--profile frontend\|backend\|fullstack` | `fullstack` | 生成的组件 |
| `--auth / --no-auth` | 关闭 | 开启 PostgreSQL session 认证 |
| `--evented / --no-evented` | 关闭 | 开启 outbox 与 Redis Streams |
| `--sample / --no-sample` | 根据 profile | 显式包含或排除示例业务 |
| `--default-locale zh-CN\|en-US` | `zh-CN` | 初始前端语言 |
| `--git / --no-git` | 开启 Git | 初始化 Git 仓库 |

省略 `--sample` 时，backend/fullstack 默认开启，frontend 默认关闭；显式参数始终优先。
`auth` 和 `evented` 必须依赖后端。

### 初始化示例

```bash
# 默认英文的全栈认证工程
project-forge init ../customer-portal \
  --name "Customer Portal" \
  --profile fullstack \
  --auth \
  --default-locale en-US

# 不含 sample 的后端事件服务
project-forge init ../billing-events \
  --name "Billing Events" \
  --profile backend \
  --evented \
  --no-sample

# 接入既有 API 的最小前端
project-forge init ../operations-ui \
  --name "Operations UI" \
  --profile frontend

# 带 sample UI 和外部 API 代理的前端
project-forge init ../items-ui --profile frontend --sample

# 中文展示名与显式安全 slug
project-forge init ../order-service \
  --name "订单服务" \
  --slug order-service \
  --profile backend

# 不自动初始化 Git 的 CI 临时工程
project-forge init generated \
  --profile fullstack \
  --auth \
  --sample \
  --no-git
```

## 检查已有工程

```bash
# profile、能力、语言和模板版本
project-forge features ../customer-portal

# 人类可读与机器可读诊断
project-forge doctor ../customer-portal
project-forge doctor ../customer-portal --require-docker
project-forge doctor ../customer-portal --json
```

JSON 格式固定，适合自动化：

```json
{
  "ok": true,
  "project": "/absolute/path/to/customer-portal",
  "checks": [
    {
      "name": "python",
      "status": "pass",
      "required": true,
      "version": "Python 3.11.16",
      "message": "meets >=3.11"
    }
  ]
}
```

## 增加组件与能力

Project Forge 只支持单调演进：可以增加能力，不提供移除命令。

```bash
# frontend → fullstack
project-forge add backend -C ../operations-ui

# backend → fullstack
project-forge add frontend -C ../billing-events

# 开启可选能力
project-forge enable auth -C ../operations-ui
project-forge enable evented -C ../operations-ui
project-forge enable sample -C ../operations-ui
```

推荐流程：

```bash
cd ../operations-ui
git status --short
git add .
git commit -m "chore: checkpoint before Project Forge evolution"

project-forge add backend
project-forge enable auth

python harness/check.py
git diff --check
git status --short
```

frontend-only 工程不能直接开启 `auth` 或 `evented`，应先增加 backend。用户自有文件会被
保留，受管文件则依据记录的 baseline 进行三方比较。

## 升级生成工程

`update --check` 只比较工程记录版本与当前已安装 CLI 内置模板，不访问 GitHub 或其他远端：

```bash
uv tool upgrade project-forge
project-forge update --check ../customer-portal
project-forge update ../customer-portal
```

升级要求 Git 干净，并采用两阶段原子更新。任一受管文件发生冲突时，所有受管文件、状态和
baseline 都保持不变，只生成相邻的 `.rej`。人工把预期改动合并到目标文件，删除 `.rej`，
提交解决结果后再重新执行 `project-forge update`。工具不会调用 `git reset`、
`git clean` 或任何 force 操作。

## 安装内置 Codex skill

```bash
# 仓库级：.agents/skills/project-forge-init
cd ../customer-portal
project-forge install-skill

# 用户级：~/.agents/skills/project-forge-init
project-forge install-skill --scope user

# 自定义位置或覆盖已有普通目录
project-forge install-skill --destination .agents/skills/custom-project-forge
project-forge install-skill --overwrite
```

为防止越界删除，overwrite 会拒绝 symlink/junction 目标及其父路径。

## 在生成工程中开发

每个生成 README 都包含与 profile 匹配的命令。统一验证入口：

```bash
python harness/check.py
```

harness 会按能力运行架构、SQL、i18n、后端、前端、构建、测试及 OpenAPI 漂移检查。
严格 CI 模式还会验证两份 Compose 配置：

```bash
HARNESS_STRICT=1 HARNESS_DOCKER=1 python harness/check.py
```

启动开发 Compose：

```bash
docker compose -f docker-compose.dev.yml up --build
docker compose -f docker-compose.dev.yml down
```

生产 Compose 预期位于外部 TLS terminator 后方，gateway 默认只绑定 `127.0.0.1:8080`。
启动前替换全部占位值：

```bash
cp .env.example .env
docker compose config
docker compose up -d --build
```

认证部署必须配置 HTTPS Origin、Secure Cookie、唯一的限流 HMAC secret 和明确的可信代理链；
生产使用前阅读生成工程的 `docs/architecture/auth.md`。

## CLI 退出码

| 退出码 | 含义 |
|---:|---|
| `0` | 成功；`update --check` 未发现更高的已安装模板版本 |
| `1` | doctor 必需检查失败，或 `update --check` 发现可更新 |
| `2` | 用法、工程状态、Git 干净度或其他运行错误 |
| `3` | 更新冲突；只写入了 `.rej` |

## 常见问题

### 找不到 `project-forge`

执行 `uv tool update-shell`，通过 `uv tool dir --bin` 确认目录，然后打开新终端。

### 已安装模板不是最新

```bash
uv tool upgrade --reinstall project-forge
project-forge --version
git -C PATH status --short
project-forge update PATH
python3 PATH/harness/check.py
```

若重新安装记录的来源仍未刷新 Git 安装，可强制安装当前分支：

```bash
uv tool install --force --python 3.11 git+https://github.com/yernsun/project-forge.git
```

`update --check` 不会主动查询远端。本次兼容改造保持 `0.2.0`，旧 `0.2.0` 工程没有可供
`--check` 报告的版本差；刷新工具后应直接执行 `project-forge update PATH`。Git 干净工作区、
全量原子更新及冲突 `.rej` 规则仍然有效。

### 演进命令提示 Git 工作区不干净

检查 `git status --short`，提交或明确 stash 当前修改。不要绕过门禁；提交状态是受控演进的
恢复点。

### Docker 只显示 warn

普通 `doctor` 将 Docker 视为可选项。验收包含 Compose 时使用 `--require-docker`，并确保
Docker CLI、Compose v2 和 daemon 均可用。

### 前端拒绝当前 Node 版本

使用 Node `>=22.12,<27`。Node 22.0–22.11 低于
[Vite 运行时下限](https://vite.dev/guide/)，Node 27+ 超出已测试范围。Node 23 和 25
虽然兼容，但已经 EOL，不应用于生产。

## 开发 Project Forge

```bash
uv sync --all-groups
uv run --frozen python harness/check.py
uv run --frozen python harness/manage_openapi_contracts.py --check
```

有意修改 API route 或 DTO 后：

```bash
uv run --frozen python harness/manage_openapi_contracts.py --refresh
uv run --frozen python harness/manage_openapi_contracts.py --check
```

渲染矩阵覆盖全部合法 profile、feature、sample 和 locale 组合。生成器边界见
[架构说明](docs/architecture.md)，应用工程架构入口为生成后的 `docs/README.md`。
