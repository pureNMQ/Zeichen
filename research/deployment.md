# 部署与运维方案 — 调研事实清单

Ticket: `.scratch/agent-ops/issues/04-deployment.md`
调研对象:agent-ops(单实例自托管,单台云 VPS + Docker Compose:web / api / mcp / cognee / postgres / 反向代理)
调研日期:2026-08-01
主要来源:官方 cognee 文档(https://docs.cognee.ai/)、cognee 仓库(https://github.com/topoteretes/cognee)、Docker 官方文档、MCP 规范(https://modelcontextprotocol.io/)。每条结论均附来源 URL;标注「实测」的条目为本次调研在命令行直接验证的结果。

---

## 0. 结论速览

1. **镜像事实更正**:ticket 中假设的 `ghcr.io/topoteretes/cognee` 不存在(ghcr 实测返回 `denied`);官方预构建镜像在 Docker Hub:`cognee/cognee`(API)与 `cognee/cognee-mcp`(MCP),每次 push 到 `main` 即发布,`main` 是滚动 tag(https://github.com/topoteretes/cognee)。
2. **服务布局**:公开入口只有反向代理(80/443);postgres、cognee、api、mcp 一律不发布宿主端口。React SPA 构建为静态文件由 nginx 直接服务,`/api` 与 `/mcp` 反代到后端——这是官方文档认可的反代模式(https://docs.cognee.ai/cognee-mcp/mcp-quickstart)。
3. **mcp 独立容器**:推荐独立容器。MCP 远程部署的两种标准传输是 stdio(仅限同机子进程)与 Streamable HTTP(独立进程单端点);cognee 官方即采用「后端 API + 独立 cognee-mcp 容器(API 模式)」的生产形态(https://docs.cognee.ai/cognee-mcp/mcp-quickstart)。
4. **cognee 数据**:全部数据在 `DATA_ROOT_DIRECTORY`/`SYSTEM_ROOT_DIRECTORY` 两个目录(Kuzu 图库、LanceDB 向量、SQLite 都是嵌入式文件),必须挂命名卷;官方 shipped compose 的 `postgres_data` 卷声明了但没挂载,照抄会丢数据(https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker)。
5. **备份**:postgres 用 `pg_dump` 逻辑备份;cognee 文件数据用卷 tar/rsync;加 .env 与异地拷贝,单 VPS 够用。
6. **安全**:cognee 默认 `ENABLE_BACKEND_ACCESS_CONTROL=True` 强制认证;`FASTAPI_USERS_JWT_SECRET` 默认 `super_secret` 必须改;首用户通过 `/api/v1/auth/register` 引导(https://docs.cognee.ai/setup-configuration/security)。
7. **升级/回滚**:固定镜像 tag,`docker compose pull && up -d` 升级,改回 tag 即回滚;`docker compose down` 保留卷,`down --volumes` 删数据(https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker)。

---

## 1. 服务布局:端口规划与容器化

### 1.1 cognee 官方 compose 事实(端口与镜像)

官方仓库根目录的 `docker-compose.yml` 定义了 7 个服务,全部加入 `cognee-network` 内部网络,服务名即内网主机名:

| 服务 | profile | 宿主端口 → 容器端口 | 说明 |
|---|---|---|---|
| `cognee` | (默认) | `8000→8000`,`5678→5678` | FastAPI REST API;`5678` 是 debugpy(仅 `DEBUG=true` 时启用) |
| `cognee-mcp` | `mcp` | `8001→8000`,`5679→5678` | MCP server;容器内仍监听 8000,`TRANSPORT_MODE=sse`;以 `--no-migration` 启动,不跑 Alembic 迁移(迁移归 `cognee` 服务管) |
| `frontend` | `ui` | `3000→3000` | 实验性 Next.js UI,`NEXT_PUBLIC_BACKEND_API_URL` 默认 `http://localhost:8000` |
| `postgres` | `postgres` | `5432→5432` | `pgvector/pgvector:pg17`,默认 cognee/cognee/cognee_db;**`postgres_data` 卷声明了但挂载被注释,容器移除即丢数据** |
| `neo4j` | `neo4j` | `7474`,`7687` | `neo4j:5.26`,APOC/GDS 插件 |
| `redis` | `redis` | `6379→6379` | `redis:7-alpine` 会话缓存(`redis_data` 卷) |
| `redisinsight` | (默认) | `5540` | 开发者工具,生产可删 |

来源:https://raw.githubusercontent.com/topoteretes/cognee/main/docker-compose.yml ;https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker-compose-reference

镜像事实(实测 + 官方 README):
- `ghcr.io/topoteretes/cognee:latest` / `:main` → ghcr registry 均返回 `denied`(实测,2026-08-01),该路径没有公开包。
- 官方 README 原文:"Cognee publishes prebuilt images to Docker Hub on every push to `main`: [`cognee/cognee`](https://hub.docker.com/r/cognee/cognee) (the API server) and [`cognee/cognee-mcp`](https://hub.docker.com/r/cognee/cognee-mcp) (the MCP server)."
  来源:https://github.com/topoteretes/cognee (README「Run with Docker」节)
- 官方文档的最小 compose 直接用 `image: cognee/cognee:main`,配 `${LLM_API_KEY:?set LLM_API_KEY to your OpenAI API key}` 守卫;`main` 是滚动 tag(每次 push 更新),生产建议固定到具体版本 tag。
  来源:https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker
- 端口可配置:`HTTP_PORT`(默认 8000,容器内监听)、`BIND_ADDRESS`(默认 0.0.0.0);`HEALTHCHECK` 已烤进镜像:`curl -f http://localhost:8000/health`,30s 间隔/10s 超时/40s 启动宽限/3 次重试;`cognee-mcp` 的 healthcheck 在 stdio 模式下跳过网络探测。
  来源:https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker

### 1.2 mcp 独立容器,还是 api 进程内的另一个面?

MCP 规范定义了两种标准传输(2025-06-18 修订):
- **stdio**:客户端把 MCP server 作为子进程启动、走 stdin/stdout。语义上只能"同机、由客户端拉起",不适合自托管远程服务。
- **Streamable HTTP**:server 是独立进程、可服务多客户端;单端点同时支持 POST(JSON-RPC 消息,可 SSE 流式返回)与 GET(SSE 流);规范要求校验 `Origin` 头防 DNS rebinding、建议实现认证。旧版 HTTP+SSE(2024-11-05)已废弃。
  来源:https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
  (注:现行规范修订为 2026-07-28,传输面仍以 stdio 与 Streamable HTTP 为主;与本仓库 sibling ticket 03 的结论交叉验证:https://github.com/topoteretes/cognee 仓库外参考本仓库 `research/mcp-standards.md`)

结论:远程/云端部署的 MCP server **必然走 HTTP 类传输**,即"一个 HTTP 端点"。这决定了:
- stdio 只在「agent 与 mcp 同机」时可用(如 IDE 本地开发),不适用于 VPS 上对外提供 MCP 服务。
- 该端点可以由独立的 mcp 容器暴露,也可以由 api(FastAPI)进程内挂载 `/mcp` 路由暴露——两种都符合规范。

cognee 的官方做法是**独立容器(API 模式)**:`cognee-mcp` 容器设置 `TRANSPORT_MODE=http` 与 `API_URL=http://cognee-backend:8000`,多客户端各连一个 MCP 实例、共享同一后端图谱;官方生产 compose 示例即「cognee-backend + cognee-mcp」两个服务。官方还说明 MCP 的两种架构模式:**Standalone 模式**(MCP 自带整套库与自己的数据库)与 **API 模式**(MCP 只做接口,数据在集中后端)。
来源:https://docs.cognee.ai/cognee-mcp/mcp-quickstart ;https://docs.cognee.ai/cognee-mcp/mcp-overview

对本项目的建议:**独立 mcp 容器**,理由:
1. 官方生态先例(cognee-mcp 独立镜像;官方 compose 为 mcp 单设资源上限 2 CPU/4 GB,API 为 4 CPU/8 GB,互不抢占)。
2. 生命周期解耦:api 升级/重启不会打断 agent 的 MCP 长连接;也可为不同 agent 各起一个 mcp 实例(官方文档演示了多实例不同端口)。
3. 反向代理层只需暴露 `/mcp` 一个路径,认证在代理或 api 层统一。
备选:若想少一个容器,把 FastMCP 以 ASGI 挂进 api 进程的 `/mcp` 也是合规简化方案(规范只要求单端点),代价是耦合生命周期与资源。

### 1.3 React SPA 如何服务

两种方式,官方均有事实依据:
- **方式 A(推荐,生产):静态构建 + nginx 反代**。SPA 在构建期 `npm run build` 产出静态文件,由 nginx 直接服务(SPA 路由用 `try_files ... /index.html`);`location /api` → `proxy_pass http://api:8000`;`location /mcp` → `proxy_pass http://mcp:8000`(若 mcp 独立)。镜像做成多阶段 `node:20-alpine 构建 → nginx:alpine 静态`,生产环境没有 Node 运行时。nginx 静态服务与反代的标准做法见官方 nginx 文档(static content 的 `root`/`location` 与 `proxy_pass`):https://nginx.org/en/docs/beginners_guide.html
- **方式 B:cognee 官方形式**——独立的 `frontend` 容器(Next.js,监听 3000,`NEXT_PUBLIC_BACKEND_API_URL` 指向后端),用 `ui` profile 启停。cognee 自己标注该 UI "experimental / work in progress"。
  来源:https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker-compose-reference ;https://raw.githubusercontent.com/topoteretes/cognee/main/docker-compose.yml

cognee 官方明确认可反向代理放置于前的部署:"If you place a reverse proxy (Nginx, Caddy) in front, you do **not** need to set a `Host: localhost` header — the backend accepts requests on any host."
来源:https://docs.cognee.ai/cognee-mcp/mcp-quickstart (Networking notes)

端口规划(本工具,单 VPS):

| 服务 | 容器内端口 | 是否发布宿主端口 | 说明 |
|---|---|---|---|
| proxy (nginx/caddy) | 80/443 | **是**(唯一公网入口) | TLS 终止 |
| web (静态) | 由 proxy 直接服务 | 否 | SPA 静态文件,无独立端口 |
| api (FastAPI) | 8000 | 否 | 仅内网,`/health` 健康检查 |
| mcp (FastMCP,独立容器) | 8000 | 否(经 proxy `/mcp`);可选 8001 直连 | `TRANSPORT_MODE=http`,端点 `/mcp` |
| cognee | 8000 | 否 | `cognee/cognee:<固定tag>`,内网供 api 调用(其 REST API 以 `/api/v1` 为前缀) |
| postgres | 5432 | 否 | 业务库(也可兼作 cognee 的关系/向量库,见 2.1) |

---

## 2. 数据持久化与备份

### 2.1 cognee 数据目录与卷

- cognee 有两个本地可写目录,即使全部走外部数据库也**仍然必需**(存摄取产物、文件缓存、loader 输出):
  - `DATA_ROOT_DIRECTORY`(默认 `.data_storage` → 容器内 `/app/cognee/.data_storage`)
  - `SYSTEM_ROOT_DIRECTORY`(默认 `.cognee_system` → 容器内 `/app/cognee/.cognee_system`)
  - 不挂载会 `PermissionError`;官方推荐把两个目录都指向同一命名卷:设 `DATA_ROOT_DIRECTORY=/cognee-data/data`、`SYSTEM_ROOT_DIRECTORY=/cognee-data/system` 并 `cognee_data:/cognee-data`。
- 默认存储形态(全嵌入式、纯文件,都在上述目录内):
  - 关系库 `DB_PROVIDER=sqlite`(默认);官方 `.env.template` 对 Docker 设置图库 `GRAPH_DATABASE_PROVIDER=kuzu`(未设时应用默认 `ladybug`,同为嵌入式文件图库);向量 `VECTOR_DB_PROVIDER=lancedb`(默认)。
  - 因此 Kuzu 图库文件、LanceDB 向量目录、SQLite 文件、原始文件缓存 = 两个目录下的文件;备份 = 备份这两个目录。
- 官方最小 compose 不挂任何卷,数据随容器删除丢失;生产必须挂命名卷。
  来源:https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker (Data Persistence and Host Files / PermissionError 两节)

- postgres 卷:官方 compose 的 `postgres_data` 卷**声明了但挂载被注释**,照抄官方文件=容器重建丢库。生产必须显式挂 `postgres_data:/var/lib/postgresql/data`。
  来源:https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker-compose-reference ;https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker
- 官方 postgres 镜像文档要点:PGDATA 数据目录默认 `/var/lib/postgresql/data`(PG 17 及以下**必须**挂 `/var/lib/postgresql/data` 而非 `/var/lib/postgresql`,后者不会持久化);PG 18+ 改为 `/var/lib/postgresql/18/docker`(升级注意)。
  来源:https://github.com/docker-library/docs/blob/master/postgres/README.md (PGDATA 一节)
- 选项:cognee 官方也支持把关系/向量/图全部落到同一个 postgres(`DB_PROVIDER=postgres`、`VECTOR_DB_PROVIDER=pgvector`、`GRAPH_DATABASE_PROVIDER=postgres`、`CACHE_BACKEND=postgres`),即"一个 postgres 跑全套记忆层";但 **postgres 图后端官方标注为 demo 特性,生产推荐图库用 Kuzu/Neo4j**。
  来源:https://github.com/topoteretes/cognee (README「Run the Whole Memory Layer on Postgres」节)

### 2.2 备份策略(单 VPS)

原则:postgres 用逻辑备份(pg_dump,官方推荐,可跨版本恢复,https://www.postgresql.org/docs/current/backup-dump.html);cognee 文件数据用卷级 tar 或 rsync;备份物必须离开本机。

**备份 checklist(建议直接进运维手册):**
1. [ ] postgres 每日逻辑备份(cron,凌晨低峰):
   `docker compose exec -T postgres pg_dump -U <user> -d <db> | gzip > /backup/pg/$(date +%F).sql.gz`
2. [ ] cognee 数据每日备份:停 cognee 容器后对卷打 tar(官方卷备份法:`docker run --rm --volumes-from <cognee容器> -v /backup:/backup ubuntu tar cvf /backup/cognee-data.tar /cognee-data`,来源:https://docs.docker.com/engine/storage/volumes/#back-up-restore-or-migrate-data-volumes);或对宿主挂载目录直接 rsync。热拷贝图库文件有损坏风险,尽量停服几秒。
3. [ ] `.env`(含密钥)与 compose 文件:密钥用占位符进 git,真实 `.env` 单独加密归档;compose 定义本身进 git。
4. [ ] 异地拷贝:每日 tar 包 rsync 到另一台机器/对象存储,保留 N 天(如 14 天)轮转。
5. [ ] 每月一次恢复演练(在临时目录 `docker compose up` 新实例,灌入最近一次 pg_dump 与 cognee tar,验证 `/health` 与一次 recall)。

---

## 3. 安全基线

### 3.1 公网入口与 TLS
- 唯一公网暴露 80/443(反向代理,TLS 终止);postgres/cognee/mcp/api 一律不发布宿主端口,仅走 compose 内部网络(服务名即内网主机名)。
- Streamable HTTP 的 MCP 端点:规范要求校验 `Origin` 头(防 DNS rebinding)、本地宜只绑 localhost、应实现认证——反向代理层做 Origin 校验 + 认证是合规做法。
  来源:https://modelcontextprotocol.io/specification/2025-06-18/basic/transports

### 3.2 cognee 安全变量(官方 Security & Privacy 页,https://docs.cognee.ai/setup-configuration/security)
| 变量 | 默认 | 生产要求 |
|---|---|---|
| `ENABLE_BACKEND_ACCESS_CONTROL` | `True` | 保持 `True`(多租户隔离 + 强制认证;设 `false` 会同时关掉认证,仅限本地) |
| `REQUIRE_AUTHENTICATION` | 继承上者 | 显式 `True` |
| `FASTAPI_USERS_JWT_SECRET` | `super_secret` | **必须改**为长随机串(多实例需一致) |
| `JWT_LIFETIME_SECONDS` | 3600 | 按需 |
| `DEFAULT_USER_EMAIL` / `DEFAULT_USER_PASSWORD` | `default_user@example.com` / `default_password` | 默认超级用户首次使用时自动创建;要在**首次创建前**设成已知凭据,事后改不生效 |
| `HASH_API_KEY` | `False` | 设 `True`(API key 以 SHA-256 存储;已有明文 key 的存量系统启用会全部失效,需重建 key) |
| `ACCEPT_LOCAL_FILE_PATH` | `True` | 服务端部署设 `False`(否则认证用户可读进程能读到的任意本地文件) |
| `ALLOW_CYPHER_QUERY` | `True` | 设 `False` 则禁用裸 Cypher 查询,只留高级语义检索 |
| `ALLOW_HTTP_REQUESTS` | `True` | 内置 SSRF 防护(拒绝内网/回环/云元数据地址,不跟随重定向);若产品不摄取公网 URL 可设 `False` |
| `CORS_ALLOWED_ORIGINS` | compose 里默认 `*` | 收紧为实际域名(官方 compose 注释明确 "Override with specific domains in production") |
| `NEO4J_ENCRYPTION_KEY` | `test_key` | 仅用 neo4j_aura_dev 时相关,生产必改 |

官方"Recommended Production Settings"示例:https://docs.cognee.ai/setup-configuration/security (Recommended Production Settings 节)

### 3.3 密钥管理与首用户引导
- **密钥管理**:compose 自动从项目目录 `.env` 读取变量并做插值;`${VAR:?错误信息}` 守卫可在变量缺失时让 `docker compose up` 直接失败(官方最小 compose 即用此模式),这是 Compose 标准插值语义:https://docs.docker.com/compose/how-tos/environment-variables/ 与 https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker (Quick Start)。`.env` 不入 git、宿主权限 `chmod 600`;compose 文件里不写明文密钥,一律 `${VAR}`。
- **首用户引导**:cognee 认证端点 `POST /api/v1/auth/register`(邮箱+密码)→ `POST /api/v1/auth/login`(OAuth2 表单)→ Bearer token / cookie;代理/agent 可用 `/api/v1/auth/api-keys` 发 API key。首用户为管理员(默认用户机制,见 3.2 表)。本工具自身的首用户引导同理:api 提供 register,或由部署脚本预置。
  来源:https://docs.cognee.ai/guides/deploy-rest-api-server (Authentication 节)
- **基础加固**:镜像固定 tag(不用 `latest`/滚动 `main`);`depends_on` + `condition: service_healthy` 等数据库就绪(官方示例:postgres `pg_isready` healthcheck,10s 间隔/5s 超时/5 次重试);资源上限(`deploy.resources.limits`);非必要镜像不装 dev 工具;host 防火墙只放行 22/80/443。

---

## 4. 升级与回滚(Compose 简单路径)

官方运维语义(https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker,「Managing the Docker Deployment」节):
- **`.env` 变更**:容器启动时读一次 `.env`,改后只需 `docker compose restart <service>`;compose 定义本身变了(ports/volumes/environment)则 `docker compose up -d --force-recreate <service>`。
- **升级**:固定 tag(如 `cognee/cognee:<版本>`,不追 `:main` 滚动 tag)→ `docker compose pull && docker compose up -d`;无需 `--build`(只改 `Dockerfile`/依赖/`COGNEE_EXTRAS` 才需要 build)。
- **回滚**:把 compose 里镜像 tag 改回上一版本 → `docker compose up -d`(容器重建但卷不动)。前提:数据兼容(见下)。
- **卷安全**:`docker compose down` 只停容器、保留卷(数据安全);`docker compose down --volumes` **删除全部数据**——运维手册里应把它列为危险操作。
- **cognee schema 迁移**:由 `cognee` 服务启动时自动跑 Alembic 迁移;`cognee-mcp` 以 `--no-migration` 启动、不碰 schema(两个服务共享同一 DB 时,迁移权归 api 侧)。本工具同理:api 容器持有迁移权,mcp 容器只读。
- 升级前动作:按 2.2 checklist 做一次全量备份;升级后验证 `/health` + 一次真实 recall。cognee 镜像健康状态是镜像内建元数据,旧 tag 可能没有(官方提示 "pull a newer tag")。
  来源:https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker (Managing the Docker Deployment / Health Status 节)

---

## 5. 草案 compose 骨架

> 占位说明:`web`/`api`/`mcp` 为本工具自建镜像(`build:` 指向仓库子目录,多阶段构建);`cognee`/`postgres` 用官方镜像。密钥一律 `${VAR}`,来自项目根 `.env`。

```yaml
# docker-compose.yml(草案骨架,单机 VPS)
name: agent-ops

services:
  proxy:                                   # 唯一公网入口, TLS 终止
    image: nginx:1.27-alpine               # 备选: caddy:2(Caddyfile 自动 TLS)
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./certs:/etc/nginx/certs:ro         # certbot 续期物(或 Caddy 内置自动 TLS)
    depends_on:
      api: { condition: service_started }
    networks: [front]

  web:                                     # React SPA: node 构建 -> nginx 静态
    build: ./web                            # 多阶段: FROM node:20-alpine AS build + FROM nginx:alpine
    restart: unless-stopped
    networks: [front]                       # 只由 proxy 访问,不发布端口

  api:                                     # FastAPI 业务后端(含健康检查)
    build: ./api
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      JWT_SECRET: ${JWT_SECRET}
      COGNEE_API_URL: http://cognee:8000
      COGNEE_API_TOKEN: ${COGNEE_API_TOKEN}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    depends_on:
      postgres: { condition: service_healthy }
      cognee: { condition: service_healthy }
    networks: [front, internal]

  mcp:                                     # FastMCP, Streamable HTTP,独立容器
    build: ./mcp                            # TRANSPORT_MODE=http,端点 /mcp
    restart: unless-stopped
    environment:
      TRANSPORT_MODE: http
      API_URL: http://api:8000              # MCP 走 api 的业务面
      API_TOKEN: ${MCP_API_TOKEN}
    depends_on:
      api: { condition: service_healthy }
    networks: [front, internal]
    deploy: { resources: { limits: { cpus: "1.0", memory: 1GB } } }

  cognee:                                  # 记忆服务(官方镜像,固定 tag)
    image: cognee/cognee:v1.4.0            # 不用滚动 tag :main;以实际发布版本为准
    restart: unless-stopped
    environment:
      LLM_API_KEY: ${LLM_API_KEY:?set LLM_API_KEY}
      LLM_PROVIDER: ${LLM_PROVIDER:-openai}
      LLM_MODEL: ${LLM_MODEL:-openai/gpt-5-mini}
      DATA_ROOT_DIRECTORY: /cognee-data/data
      SYSTEM_ROOT_DIRECTORY: /cognee-data/system
      ENABLE_BACKEND_ACCESS_CONTROL: "true"
      FASTAPI_USERS_JWT_SECRET: ${COGNEE_JWT_SECRET}
      HASH_API_KEY: "true"
      ACCEPT_LOCAL_FILE_PATH: "false"
      ALLOW_CYPHER_QUERY: "false"
      CORS_ALLOWED_ORIGINS: ${PUBLIC_ORIGIN}
      # 可选: 与业务库共用 postgres(关系/向量)——
      # DB_PROVIDER: postgres / VECTOR_DB_PROVIDER: pgvector
      # DB_HOST: postgres / DB_USERNAME / DB_PASSWORD / DB_NAME
    volumes:
      - cognee_data:/cognee-data            # Kuzu 图库 + LanceDB + SQLite 全在此卷
    healthcheck:                            # 镜像已内建 healthcheck,可省略/覆盖
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    # 若 cognee 改用外部 postgres(见环境变量注释),加:
    # depends_on:
    #   postgres: { condition: service_healthy }
    networks: [internal]

  postgres:                                # 业务库(pgvector 镜像,顺带支持向量)
    image: pgvector/pgvector:pg17
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-cognee}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB:-cognee_db}
    volumes:
      - postgres_data:/var/lib/postgresql/data   # 官方 compose 的坑: 挂载必须显式写
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-cognee} -d ${POSTGRES_DB:-cognee_db}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks: [internal]

networks:
  front:                                   # proxy <-> web/api/mcp
  internal:                                # api/mcp/cognee/postgres 互访

volumes:
  postgres_data:
  cognee_data:
```

配套 `deploy/nginx.conf` 草案要点(nginx 官方文档见 https://nginx.org/en/docs/beginners_guide.html):
- `location /` → `root /usr/share/nginx/html; try_files $uri /index.html;`(web 容器内的静态文件;SPA 路由回退)
- `location /api/ { proxy_pass http://api:8000; }`(含 `proxy_set_header X-Forwarded-*`、`X-Forwarded-Proto`)
- `location /mcp { proxy_pass http://mcp:8000; }`(Streamable HTTP 单端点;注意保留 POST/GET 语义与 SSE 的 `proxy_buffering off` 或 `proxy_http_version 1.1`)
- 443 上挂证书;`/health` 可由 `api`/`cognee` 直接提供,做探活。

---

## 6. 主要来源清单

- Cognee Docker 部署(compose profile、持久化、healthcheck、运维命令):https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker
- Cognee compose 参考(7 服务逐一说明、postgres_data 未挂载警告):https://docs.cognee.ai/how-to-guides/cognee-sdk/deployment/docker-compose-reference
- Cognee 官方 shipped compose:https://raw.githubusercontent.com/topoteretes/cognee/main/docker-compose.yml
- Cognee README(镜像发布位置、Postgres 全套记忆层):https://github.com/topoteretes/cognee
- Cognee 安全与隐私(生产设置清单):https://docs.cognee.ai/setup-configuration/security
- Cognee REST API 部署与认证端点:https://docs.cognee.ai/guides/deploy-rest-api-server
- Cognee MCP 概览(Standalone vs API 模式):https://docs.cognee.ai/cognee-mcp/mcp-overview
- Cognee MCP 快速上手(TRANSPORT_MODE 表、API 模式生产 compose):https://docs.cognee.ai/cognee-mcp/mcp-quickstart
- MCP 规范·传输(stdio / Streamable HTTP / Origin 校验):https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- Docker 卷备份/恢复/迁移:https://docs.docker.com/engine/storage/volumes/
- Docker 官方 postgres 镜像文档(PGDATA、挂载位置):https://github.com/docker-library/docs/blob/master/postgres/README.md
- PostgreSQL 逻辑备份(pg_dump):https://www.postgresql.org/docs/current/backup-dump.html
- Compose 环境变量与插值:https://docs.docker.com/compose/how-tos/environment-variables/
- nginx 静态服务与反代基础:https://nginx.org/en/docs/beginners_guide.html

## 7. 待办/未决(供规格书或后续 ticket)

- [ ] cognee 与业务 postgres 是否同库(pgvector 共用 vs 嵌入式 Kuzu/LanceDB 分卷)——影响备份清单与卷数;本草案按官方推荐(生产图库用嵌入式 Kuzu)处理,同库仅作选项列出。
- [ ] 反向代理选型 nginx vs caddy(自动 TLS/零配置 vs 生态通用性)未定,草案以 nginx 为主。
- [ ] cognee 镜像的具体固定 tag(以发布页为准,草案占位 `v1.4.0` 需核对)与 `cognee/cognee` 镜像是否满足离线/内网拉取(官方说明镜像内建 Kuzu JSON 扩展,mcp 镜像另有 CUDA 依赖体积问题:https://docs.cognee.ai/cognee-mcp/mcp-quickstart)。
