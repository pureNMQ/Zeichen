# 01 工程骨架 + 数据模型 + 迁移

Status: resolved
Type: task
Blocked by:

## Question

搭建可运行的最小工程骨架并落地数据模型(规格书 §1/§2):
- 仓库结构:backend/(FastAPI + SQLAlchemy 2.0 + Alembic)、frontend/(Vite + React + TS + Tailwind + Shadcn/ui)、docker-compose.yml(骨架)
- 数据模型:规格书 §2.2 全部实体映射为 SQLAlchemy 模型(含多态 comment/activity 的 check 约束、软删五件套约定、reference 枚举、memory_grant)
- Alembic 迁移:首个迁移脚本可用,`alembic upgrade head` 干净执行
- 本地验证:backend 能起(空 API 冒烟)、frontend dev server 能起(空页)、pytest 冒烟通过

产出:可 clone 即跑的最小骨架 + 完整建表迁移。本票期间验证 cognee 官方镜像本地可用性(记入 Answer,供 09 用)。

## Answer

全部落地并验证通过。

**骨架结构**
- `backend/`:FastAPI + SQLAlchemy 2.0 + Alembic,`app/`(config/db/main/models/tests)+ `alembic/`;pyproject 可 `pip install -e ".[dev]"`
- `frontend/`:Vite 8 + React 19 + TS 6 + Tailwind v4 + shadcn/ui(radix-nova preset,button 组件就位);`@/*` 别名在根与 app 两个 tsconfig
- `docker-compose.yml`:postgres:16 + cognee 可起;api/mcp/web 注释占位(后续票)

**数据模型(15 张表全建)**
- 规格书 §2.2 全实体映射:`user/api_key/team/workspace_member/project/project_member/requirement/task/document/document_version/comment/activity/attachment/reference/memory_grant`
- check 约束:requirement/task 五态 status、document.doc_type、comment/activity/attachment 的 target_type(枚举 `requirement/task/document/project/user`,扩展需迁移)、reference from/to/type(derives/documents/implements/mentions)、memory_grant 非自授
- 判定(偏离字面五件套,已按语义落):**工作区级实体**(user/team/api_key/workspace_member/memory_grant)不带 project_id,workspace 根无此语义;api_key 用 `revoked_at` 生命周期(不叠加软删);activity 不可变只记 created_at;document_version 链只追加不软删
- 注意:`metadata` 是 SQLAlchemy Declarative 保留名 → 列名仍为 `metadata`,Python 属性为 `doc_metadata`

**迁移**
- 首迁移 `75887d8488b0_initial_schema`(autogenerate + 手检);`alembic upgrade head` 在 **SQLite 与 compose Postgres 双路径**干净执行,PG 上 15 业务表 + alembic_version 全建
- 默认 `DATABASE_URL` 指向 compose postgres;无容器开发可 `DATABASE_URL=sqlite:///./dev.db` 覆盖(仅开发/测试)
- Windows 注意:alembic.ini 须保持 ASCII(GBK 读配置会崩)

**验证结果**
- pytest:6 passed(冒烟 + 模型回环 + 3 个 check 约束违例)
- backend uvicorn:`GET /api/health` → `{"status":"ok"}` 200
- frontend:`npm run build` 通过;dev server 200 空页
- `docker compose config` 校验通过;postgres 容器已起且 healthcheck 通过

**cognee 官方镜像(供 09 记忆票)**
- `docker pull cognee/cognee:latest` 成功:1.85GB,digest `sha256:3a11fcd2431bd1d691ee8d52565beb0ef6d195b749058762e4d93b7f8f9a911e`
- 版本 **cognee 1.4.1**(Python 3.12.13);entrypoint `/app/entrypoint.sh`,CMD 空(需看脚本定默认端口,09 票验)
- 默认 auth posture:`authentication=required, multi_tenant=enabled`(与 §8.2 `ENABLE_BACKEND_ACCESS_CONTROL=True` 预期一致,无需改)
- 镜像未暴露声明端口(ExposedPorts null),API 端口/健康端点留 09 票确认
