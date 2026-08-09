# 贼船 Zeichen

面向**人类与 AI agent 协同**的项目管理平台:需求、任务、文档、记忆与 MCP 工具一体。

Zeichen(贼船)把软件开发的规格、需求、任务、词典、调研与长期记忆集中在一个系统里,并通过标准 MCP 协议把能力暴露给 Claude Code、Codex、opencode 等 agent 客户端——agent 与团队成员在同一个工作流中流转。

## 功能

- **项目与团队**:项目、团队、成员与角色权限管理,agent API key 签发
- **需求 / 任务**:需求(Requirement)与任务(Task)流转(backlog → in_progress → verifying → done / cancelled),指派与认领
- **文档工作台**:文档目录树、多版本、评论、附件(单文件 20MB、单项目 2GB)、实体间引用(derives / documents / implements / mentions)
- **代码引用库**:代码库 / 类型符号 / 版本(CodeLibrary、CodeSymbol)结构化沉淀
- **长期记忆**:基于 Cognee 的项目共享记忆图谱,agent 会话异步蒸馏(improve worker)
- **通知与搜索**:站内通知、跨域语义搜索(关键词 + 记忆混合)
- **MCP 工具集**:70+ 工具,按域命名 —— `requirements.*` / `tasks.*` / `docs.*`(wiki / glossary / code 代码引用库)/ `comment.*` / `ref.*` / `memory.*` / `project.*` / `agent.*` / `search.*` / `attachment.*`,统一 `code: message` 错误四件套

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16(开发可 SQLite) |
| MCP | 官方 MCP Python SDK(1.29+) FastMCP + Streamable HTTP,Bearer API key, DNS-rebinding 保护 |
| 记忆 | Cognee 1.4(图数据库),DeepSeek LLM,fastembed 本地嵌入 |
| 前端 | React 19, TypeScript, Vite 8, Tailwind CSS 4, shadcn/radix-ui, TanStack Query, Vditor |
| 部署 | Docker Compose 全链路(nginx 唯一入口),生产部署模板见 `deploy/` |

## 架构

```
                 ┌─────────────┐   /api    ┌─────────┐   ┌──────────┐
 浏览器(SPA) ────► │  nginx(web) │ ────────► │  api    │──►│ postgres │
                 │             │   /mcp    ├─────────┤   └──────────┘
 MCP 客户端 ─────► │             │ ────────► │  mcp    │   ┌──────────┐
 (Claude Code /  └─────────────┘            └────┬────┘──►│  cognee  │
  Codex / ...)                                   │        └──────────┘
                                                ┌▼────┐
                                                │worker│ (记忆蒸馏)
                                                └─────┘
```

- `api`(FastAPI):REST 业务接口,Web 与 MCP 共享同一套 service 层与权限模型
- `mcp`:独立进程暴露 `/mcp`(Streamable HTTP),Bearer API key 认证,只签发给 agent
- `worker`:轮询执行 Cognee 会话蒸馏任务(异步,不阻塞 MCP 请求)
- `cognee`:长期记忆图谱,API 进程是唯一主账号,项目角色由应用侧强制

## 快速开始

### 方式一:Docker Compose 一键起(推荐)

```bash
cp .env.example .env   # 填入 DEEPSEEK_API_KEY(cognee 记忆功能必需)
docker compose up -d --build
```

打开 http://localhost 完成初始化并创建首个用户。

> 说明:compose 中 `api` / `mcp` / `worker` 不发布宿主端口,nginx 是唯一入口;`postgres:5432` 与 `cognee:8000` 仅开发期暴露给宿主。

### 方式二:本地开发(Windows)

```powershell
# 1. 先起容器内的 postgres 与 cognee(宿主端口 5432 / 8000)
docker compose up -d postgres cognee

# 2. 一键启动前端 / API / MCP 三个进程(日志在 .scratch/)
.\start-all.ps1
```

- 前端 dev:http://localhost:5173(代理 API 与 MCP)
- API:http://localhost:8001,健康检查 `GET /api/health`
- MCP:http://localhost:8002/mcp

### 后端单独开发(需先有数据库)

```bash
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload          # API
python -m app.mcp_server                # MCP
python -m app.workers.memory_improve    # worker
```

### 前端单独开发

```bash
cd frontend
npm install
npm run dev        # 开发
npm run lint       # oxlint
npm test           # vitest
```

## 配置

后端与容器配置通过根目录 `.env` 注入(参见 `backend/app/config.py`),常用变量:

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | —(必填) | Cognee LLM 密钥,仅存在于被忽略的 `.env` |
| `DATABASE_URL` | `postgresql+psycopg://zeichen:zeichen@localhost:5432/zeichen` | 数据库连接(容器内指向 `postgres`) |
| `SESSION_SECRET` | dev 占位 | 生产必须覆盖,JWT 会话签名密钥 |
| `SESSION_COOKIE_SECURE` | `false` | 生产(HTTPS)设为 `true` |
| `COGNEE_BASE_URL` | `http://localhost:8000/api/v1` | Cognee 服务地址 |
| `MCP_ISSUER_URL` / `MCP_RESOURCE_SERVER_URL` | `http://localhost/...` | MCP OAuth 元数据地址,公网部署须指向外部 HTTPS |
| `MCP_ALLOWED_HOSTS` | `127.0.0.1:*,localhost:*,[::1]:*` | MCP Host 白名单(DNS-rebinding 保护) |

## MCP 客户端接入

在 Zeichen 前端签发 agent API key 后,以 Streamable HTTP 连接:

```
# Claude Code / Codex / opencode 的 mcp 配置
{
  "type": "http",
  "url": "https://<host>/mcp",
  "headers": { "Authorization": "Bearer <api-key>" }
}
```

## 测试

```bash
cd backend && pytest          # 后端(backend/app/tests)
cd frontend && npm test       # 前端 vitest
```

## 部署

生产部署(单机 Docker Compose 全栈、TLS nginx、每日备份/恢复与运维手册)见 [`deploy/README.md`](deploy/README.md)。

## 文档与协作

- 规格、需求、任务、词典与调研由 **Zeichen 自身**管理(通过本仓库的 MCP 接入),仓库内仅保留代码与本文件
- 开发约定见 [`AGENTS.md`](AGENTS.md)
- 前端模板说明见 [`frontend/README.md`](frontend/README.md)
