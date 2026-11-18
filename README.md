# 贼船 Zeichen

面向**人类与 AI agent 协同**的项目管理平台:需求、任务、文档与 MCP 工具一体。

规格、术语和调研保存在项目 Wiki。开发工作通过需求和任务流转，团队成员及其附属 Agent 共享项目权限。

## 功能

- **项目与团队**支持人类成员管理、项目角色和附属 Agent。Agent 动态继承主人的项目权限，主人可以签发和吊销其密钥。
- **需求和任务**包含待确认、待办、实现中、验收中、已完成和已取消六种需求状态。任务归属需求，使用待办、实现中、已完成和已取消四种状态，支持指派和认领；前置关系记录在需求之间。任务使用需求内编号，如 REQ-12-T1。需求和任务正文支持 Markdown、版本查看与恢复。
- **需求时间轴**汇集讨论、任务证据与系统事件，支持回复、修订和撤回。有效提及及回复可产生通知。
- **项目 Wiki**提供目录树、版本、属性和引用。项目文件库管理上传、关联和恢复，文件与项目限额可配置。
- **项目搜索**可检索需求、时间轴、Wiki 和文件。代码仓库支持登记版本控制系统、仓库地址和默认分支。
- **MCP 与工作流**通过标准 MCP 工具访问同一项目。客户端用 `tools/list` 查询当前契约，工作流示例见 `Skills/`。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16(开发可 SQLite) |
| MCP | 官方 MCP Python SDK(1.29+) FastMCP + Streamable HTTP,Bearer API key, DNS-rebinding 保护 |
| 前端 | React 19, TypeScript, Vite 8, Tailwind CSS 4, shadcn/radix-ui, TanStack Query, Vditor |
| 部署 | Docker Compose 全链路(nginx 唯一入口),生产部署模板见 `deploy/` |

## 架构

浏览器经 nginx 访问前端与 API，Agent 经同一入口访问 MCP。API 和 MCP 共用 PostgreSQL、项目文件卷及权限模型。v2 定时维护独立运行，只回收过期文件授权与废弃上传暂存；业务资源由各自的回收站管理。

## 快速开始

### 本机开发、远端发布（现有线上实例）

在 PowerShell 7 中提交 `develop` 上的修改，然后执行：

```powershell
.\deploy.ps1             # 推送 GitHub，经 SSH 远端测试、构建、备份并发布
.\deploy.ps1 -CheckOnly  # 只验证和构建，不切换线上服务
```

本机只需 Git、SSH 和 PowerShell，不需运行 Docker、数据库或开发服务器。
服务器按提交保存镜像，API/MCP 无源码挂载和热重载，Zeichen 前端为独立容器。
共享 Nginx 与 PostgreSQL 不重建；MochiSite 配置与文件受到发布前检查保护。
发布证据及备份保存在服务器 `/srv/zeichen/.release/`，其中包含私密配置，不可提交。
v2 日常发布要求候选与运行实例的 Alembic 版本相同。有迁移的候选走独立迁移流程。首次从 v1 切换须从同一停写快照准备独立数据库及文件卷。发布、恢复及定时维护见 [v2 运维说明](deploy/README.md)。

### 在空数据库上启动本地 v2 环境

```bash
cp .env.example .env   # 生产必须覆盖 SESSION_SECRET 等
docker compose up -d --build
```

打开 http://localhost 完成初始化并创建首个用户。升级已有 v1 数据库时使用上文的独立切换流程。

> 说明:默认启动 `web`、`api`、`mcp` 和 `postgres`。API 和 MCP 不发布宿主端口,nginx 是唯一入口;`postgres:5432` 仅开发期暴露给宿主。

### 方式二:本地开发(Windows)

```powershell
# 1. 先起容器内的 postgres(宿主端口 5432)
docker compose up -d postgres

# 2. 一键启动前端 / API / MCP 三个进程(日志在 .scratch/)
.\start-all.ps1
```

- 前端 dev:http://localhost:5173(代理 API)
- API:http://localhost:8001,健康检查 `GET /api/health`
- MCP:http://localhost:8002/mcp

### 后端单独开发(需先有数据库)

```bash
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --port 8001 --reload  # API
python -m app.mcp_server                # MCP
```

### 前端单独开发

```bash
cd frontend
npm install
npm run dev        # 开发
npm run lint       # 静态检查
npm test           # vitest
```

## 配置

后端与容器配置通过根目录 `.env` 注入(参见 `backend/app/config.py`),常用变量:

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://zeichen:zeichen@localhost:5432/zeichen` | 数据库连接(容器内指向 `postgres`) |
| `SESSION_SECRET` | dev 占位 | 生产必须覆盖,JWT 会话签名密钥 |
| `SESSION_COOKIE_SECURE` | `false` | 生产(HTTPS)设为 `true` |
| `MCP_ISSUER_URL` / `MCP_RESOURCE_SERVER_URL` | `http://localhost/...` | MCP OAuth 元数据地址,公网部署须指向外部 HTTPS |
| `MCP_ALLOWED_HOSTS` | `127.0.0.1:*,localhost:*,[::1]:*` | MCP Host 白名单(DNS-rebinding 保护) |

## 历史版本记录

### v0.1.1(2026-08-14)

- 新增:需求「待确认(pending)」状态(新需求默认待确认,确认后才可建任务)
- 新增:用户昵称与头像(自定义上传 / 恢复默认 / 保存前预览)
- 新增:Cognee 管理与受控重启(管理员在 Web 端配置 LLM / 嵌入模型并安全重启)
- 新增:项目代码仓库管理(登记 git / svn 仓库与默认分支)
- 新增:标准 Zeichen 工作流 Skills(agent 侧需求/任务/文档流转技能)
- 修复:构建镜像时支持受限网络(HTTP pip 镜像 trusted-host、fastembed 离线缓存)

### v0.1.0

- 首个完整版本:项目/团队/成员/Agent 管理,需求任务流转,文档工作台,代码引用库,长期记忆,通知搜索,70+ MCP 工具

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

v2 切换、日常发布与维护定时器见 [`deploy/README.md`](deploy/README.md)。

## 文档与协作

- 当前规格以 Zeichen 项目 Wiki 中的 DOC-41 为准。术语、ADR 与调研也在项目 Wiki 查阅。
- 开发约定见 [`AGENTS.md`](AGENTS.md)
- 前端模板说明见 [`frontend/README.md`](frontend/README.md)
