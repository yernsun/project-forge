# Project Forge 常见问题

简体中文 | [English](FAQ.md)

本文整理 Project Forge 初始化工程后常见的运行与部署问题。除非命令另有说明，均在生成
工程根目录执行。提交问题时不要粘贴数据库密码、session/CSRF Cookie 或
`APP_AUTH_RATE_LIMIT_SECRET`。

## Docker 与环境选择

### 为什么设置了 `APP_ENV=development`，FastAPI 仍显示 production mode？

这些配置控制不同维度：

- `fastapi dev` 或 `fastapi run` 决定 FastAPI server mode。
- `APP_ENV=development|test|production` 决定应用安全默认值与启动校验。
- `docker compose -f docker-compose.dev.yml ...` 选择开发拓扑。
- 不带 `-f` 的 `docker compose ...` 使用 `docker-compose.yml` 生产拓扑。

检查实际运行的 stack 与命令：

```bash
docker compose ls
docker compose --env-file .env.dev -f docker-compose.dev.yml ps
docker compose --env-file .env.dev -f docker-compose.dev.yml logs --tail=100 api frontend
```

生成的开发 API 使用 `fastapi dev`，生产镜像默认使用 `fastapi run`。只修改 `APP_ENV`
不会改变 server command 或 Compose 拓扑。

### 不同启动方式分别读取哪个 `.env`？

| 启动方式 | 配置来源 |
|---|---|
| 生产 Compose | 根目录 `.env`，由 `docker-compose.yml` 展开 |
| 开发 Compose | `docker-compose.dev.yml` 的安全默认值，可由 `.env.dev` 覆盖 |
| 直接在主机运行后端 | `backend/.env` |
| 直接在主机运行前端 | `frontend/.env` |

生产与开发变量刻意隔离：生产使用 `APP_ALLOWED_ORIGINS` 等名称，开发 Compose 读取
`DEV_APP_ALLOWED_ORIGINS`。先复制受版本控制且不含秘密的示例，并始终显式传入：

```bash
cp .env.dev.example .env.dev
docker compose --env-file .env.dev -f docker-compose.dev.yml config
docker compose --env-file .env.dev -f docker-compose.dev.yml exec -T api printenv \
  APP_ENV APP_ALLOWED_ORIGINS APP_SESSION_COOKIE_SECURE APP_SIGNUP_ENABLED
```

不传 `.env.dev` 时，所有生成的主机端口都绑定到 `127.0.0.1`；示例中的有效值同样只绑定
回环地址。注释中的局域网配方只开放前端，PostgreSQL、Redis 和 API 仍只绑定回环地址。
不要把生产秘密复制到 `.env.dev`，也不要期望根目录 `.env` 配置开发栈。

每行只能包含一个 `KEY=value`。`.env` 必须使用纯 URL，不能粘贴 Markdown 链接：

```dotenv
# 正确
APP_ALLOWED_ORIGINS=https://172.20.0.10:8443

# 错误
APP_ALLOWED_ORIGINS=[https://172.20.0.10:8443](https://172.20.0.10:8443)
```

限制凭据文件权限：

```bash
chmod 600 .env backend/.env
```

### 为什么修改配置后容器没有变化？

应用在进程启动时读取并缓存配置。先校验最终 Compose model，再重新创建相关容器：

```bash
docker compose --env-file .env.dev -f docker-compose.dev.yml config --quiet
docker compose --env-file .env.dev -f docker-compose.dev.yml \
  up -d --build --force-recreate migrate api frontend
```

`docker compose restart` 不会使用新的环境变量重新创建容器。

## 局域网访问与 Origin

### 如何让局域网中的其他设备访问开发前端？

浏览器 Origin 由对外可见的协议、主机和宿主机端口组成。复制 `.env.dev.example`，将仅用于
文档的私有地址替换为开发主机的真实局域网地址，并让所有后端依赖继续只绑定回环地址：

```dotenv
DEV_FRONTEND_BIND_HOST=0.0.0.0
DEV_FRONTEND_PORT=8173
DEV_API_BIND_HOST=127.0.0.1
DEV_DB_BIND_HOST=127.0.0.1
DEV_APP_ALLOWED_ORIGINS=http://localhost:8173,http://127.0.0.1:8173,http://172.20.0.10:8173
```

```bash
docker compose --env-file .env.dev -f docker-compose.dev.yml up -d --build
```

然后访问 `http://172.20.0.10:8173`，并将示例地址替换为服务器稳定的局域网地址。
不要把 `0.0.0.0` 当作浏览器 URL 或允许的 Origin；它只是监听地址。

### 什么情况会返回 `origin_not_allowed`？

注册、登录以及所有已认证的 unsafe 请求都要求允许的 `Origin`，没有 Origin 时回退检查
允许来源的 `Referer`。去除末尾 `/` 后执行精确匹配：

- `http` 与 `https` 是不同 Origin。
- `localhost`、`127.0.0.1` 和局域网 IP 是不同 Origin。
- `5173`、`8173` 与 `8700` 是不同 Origin。
- Origin 不包含 `/api/v1`、其他 path、凭据、query 或 fragment。

`APP_ALLOWED_ORIGINS` 必须填写浏览器页面 Origin，而不是以下内部地址：

- `http://0.0.0.0:8000`
- `http://api:8000`
- `VITE_API_PROXY_TARGET`

对比浏览器 Network 面板中的 `Origin` 请求头和 API 容器的实际值：

```bash
docker compose --env-file .env.dev -f docker-compose.dev.yml exec -T api \
  printenv APP_ALLOWED_ORIGINS
```

直接使用 `curl` 时必须显式发送 Origin：

```bash
curl -H 'Origin: http://172.20.0.10:8173' \
  http://172.20.0.10:8173/api/v1/auth/session
```

### 认证能否同时支持 HTTP 和 HTTPS？

开发环境可以用逗号配置多个 HTTP/HTTPS Origin，并设置
`APP_SESSION_COOKIE_SECURE=false`。生产环境有意只允许 HTTPS Origin，且强制 Secure
Cookie，不应削弱这项生产校验。

容器内部链路仍可使用 HTTP。正常生产路径是：

```text
浏览器 https://app.example.com
  -> 外部 TLS terminator
  -> http://127.0.0.1:8080
  -> http://api:8000
```

此时 `APP_ALLOWED_ORIGINS` 使用仅供文档说明的 `https://172.20.0.10:8443`；请替换为浏览器
实际访问的精确外部 Origin。除非受控网络明确要求其他绑定，
生产 gateway 应保持 `APP_BIND_HOST=127.0.0.1`。

## 认证请求与 Cookie

### 注册为什么返回 `request_validation_failed`？

请求已经到达 FastAPI，但在 Service 执行前未通过严格的 signup DTO。认证接口会主动隐藏
字段级错误，避免密码和提交的凭据进入响应。

JSON 合约为：

```json
{
  "email": "developer@example.com",
  "password": "correct-horse-battery",
  "workspaceName": "Personal"
}
```

约束如下：

- 使用 `Content-Type: application/json`，不能使用 form data。
- `email` 必须通过 `EmailStr`；不要使用本地/IP-only 地址或 `.test` 特殊用途示例。
- 注册密码为 12～200 个字符，且不会自动 trim。
- `workspaceName` 为 1～120 个字符，不能全是空格。
- `username`、`workspace`、`confirmPassword` 等未知字段会被拒绝。
- 外部字段使用 camelCase，填写 `workspaceName`。

通过浏览器 Network 面板检查 Request Payload，分享问题时不要提供真实密码。已知可用的
局域网请求示例：

```bash
curl -i -c .cookies.txt \
  -H 'Origin: http://172.20.0.10:8173' \
  -H 'Content-Type: application/json' \
  --data '{"email":"developer@example.com","password":"correct-horse-battery","workspaceName":"Personal"}' \
  http://172.20.0.10:8173/api/v1/auth/signup
```

成功状态为 `201 Created`；重复邮箱返回 `409`，而不是 `422`。

### 注册为什么返回 `signup_disabled`？

生产环境默认关闭注册。仅在计划开放注册的时段启用：

```dotenv
APP_SIGNUP_ENABLED=true
```

修改后重新创建 API 容器。如果产品不需要公开注册，在初始化用户后应再次关闭。

### 注册返回 `201`，但恢复 session 为什么返回 `401`？

检查 Cookie 边界：

- HTTP 开发环境需要 `APP_SESSION_COOKIE_SECURE=false`。
- HTTPS 生产环境强制 Secure Cookie，并使用 `__Host-<slug>-session/csrf` 名称。
- 始终使用相同浏览器主机；`localhost` 创建的 Cookie 不属于局域网 IP。
- `SameSite=Strict` 会有意拒绝跨站 Cookie 流程。
- 修改主机、端口、环境或 project slug 后应清除旧 Cookie。

生成前端默认让 `VITE_API_BASE_URL` 为空，以保持 API 同源。不要让浏览器绕过同源代理
直接访问容器 `8000` 端口。

### 已登录的 POST/PUT/PATCH/DELETE 为什么返回 `csrf_invalid` 或 `403`？

已认证 unsafe 请求必须同时具备：

- 有效 session Cookie；
- 允许的 Origin（或 Referer 回退）；
- 可读 CSRF Cookie；
- 值相同的 `X-CSRF-Token`；
- PostgreSQL 中与当前 session 绑定的 CSRF digest。

生成的 `openapi-fetch` middleware 会自动处理。自定义客户端必须保存 Cookie jar，并把
CSRF Cookie 值复制到请求头。

## 代理、限流与 Secret

### `FORWARDED_ALLOW_IPS` 应填写什么？

只能填写直接 gateway 及受控代理链中每一跳的 IP/CIDR。API 依靠这个边界恢复真实客户端
地址，并用于 PostgreSQL 共享限流。

- `0.0.0.0/32` 只信任单个地址 `0.0.0.0`，它不是通配符。
- `0.0.0.0/0`、`::/0` 和 `*` 会信任所有来源，生产环境会拒绝。
- 不要无条件信任整个 Docker 或公司网络。
- 开发 Compose 可以使用受控的项目网络 CIDR；生产必须使用明确管理的网络与代理链。

配置前检查直接 peer 与项目 subnet：

```bash
docker network inspect PROJECT_default
docker inspect PROJECT-gateway-1
```

代理未被信任时认证仍可能工作，但多个用户会共享代理地址对应的限流 key，并可能共同耗尽
一个 bucket。

开发环境默认让 `DEV_FORWARDED_ALLOW_IPS` 为空，不猜测 Docker subnet。只有检查直接 peer
后才能设置；它与 `origin_not_allowed` 无关，也不是注册成功的必要条件。

### 如何生成 `APP_AUTH_RATE_LIMIT_SECRET`？

为每个环境生成并持久保存独立随机值：

```bash
openssl rand -hex 32
```

将其放入 secret manager 或未跟踪的 `.env`，不要提交 Git。生产环境拒绝生成模板中的开发
默认值和不足 32 字节的值。所有副本和重启必须保持一致，才能得到相同的 HMAC bucket key。

### 测试时为什么返回 `429 Too Many Requests`？

登录与注册限流共享存储在 PostgreSQL 中。读取 `Retry-After` 并等待窗口结束。错误登录凭据
会消耗次数；DTO 或 Origin 拒绝发生在凭据验证之前。检查或清理过期 bucket：

```bash
cd backend
uv run content-agent auth purge-expired --dry-run
uv run content-agent auth purge-expired
```

不要通过提高生产限额掩盖错误的代理/客户端地址配置。

## 诊断与工程维护

### 报告 Compose/认证问题前应收集什么？

只提供脱敏输出，不要打印 secret 或完整 Cookie：

```bash
docker compose ls
docker compose --env-file .env.dev -f docker-compose.dev.yml ps
docker compose --env-file .env.dev -f docker-compose.dev.yml config --quiet
docker compose --env-file .env.dev -f docker-compose.dev.yml exec -T api content-agent config check --json
docker compose --env-file .env.dev -f docker-compose.dev.yml exec -T api printenv \
  APP_ENV APP_ALLOWED_ORIGINS APP_SESSION_COOKIE_SECURE \
  APP_SIGNUP_ENABLED FORWARDED_ALLOW_IPS
docker compose --env-file .env.dev -f docker-compose.dev.yml logs --tail=100 api frontend
curl -i http://localhost:5173/health/ready
python harness/check.py
```

每个 API 响应都带有 `X-Request-ID`。当公开响应出于安全原因省略字段级校验详情时，可用
该标识在 API 结构化日志中查找对应记录。`content-agent config check --json` 只输出脱敏后的有效配置
摘要，绝不会打印数据库 URL、密码、Cookie、session/CSRF token 或限流秘密。

需要把缺失的 uv、npm 或 Docker 视为失败时，使用严格模式：

```bash
HARNESS_STRICT=1 HARNESS_DOCKER=1 python harness/check.py
```

### 为什么应在本地定制前提交生成基线？

Project Forge 的 update/add/enable 要求 Git 工作区干净。修改端口或 Compose 文件前先提交
生成基线，使 Git 成为恢复点，并让后续三方更新区分模板变化与本地变化。不要提交 `.env`、
Cookie jar 或 secret。

## 错误快速索引

| 现象/错误码 | 优先检查 |
|---|---|
| FastAPI 显示 production mode | Compose 文件，以及 `fastapi dev`/`fastapi run` command |
| `origin_not_allowed` | 浏览器协议/主机/端口与 API 容器 allowed origins 是否精确一致 |
| `request_validation_failed` | JSON Content-Type、有效邮箱、密码长度、`workspaceName`、额外字段 |
| `signup_disabled` | `APP_SIGNUP_ENABLED` 及生产环境是否应开放注册 |
| 注册 `201`、session `401` | Secure 标志、主机一致性、旧 Cookie、同源 API base URL |
| `csrf_invalid` / 已认证请求 `403` | Session Cookie、Origin、CSRF Cookie/Header 对 |
| `429` | `Retry-After`、可信代理链、PostgreSQL 共享 limiter bucket |
| 配置修改未生效 | Compose 最终配置及是否重新创建容器 |
