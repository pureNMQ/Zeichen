# 交接:贼船 Zeichen 实现(本地可跑 v1)

> 本会话为 wayfinder 地图 `.scratch/zeichen-impl/map.md` 的接力点。新会话从本文档开始。

## 现状

- **仓库**:`D:\Projects\agent-ops`(git master,已推 `origin=https://github.com/pureNMQ/Zeichen.git`)
- **规格书**(唯一依据):`docs/spec.md` v1.0(9 章,已定稿)
- **地图**:`.scratch/zeichen-impl/map.md`——7 张垂直切片构建票
- **已 resolved**:`01 工程骨架 + 数据模型 + 迁移`(Answer 见 ticket,含 cognee 镜像验证结论)
- **已认领**:`02 认证权限闭环`(Status: claimed,尚未动手)
- **环境**:Python 3.12.5(.venv 已装 backend `-e ".[dev]"`)、Node 24.15;Docker Desktop 已运行(compose postgres + cognee 镜像就位)

## 骨架现状(01 产出)

- `backend/`:FastAPI + SQLAlchemy 2.0 + Alembic;15 表全建,首迁移 `75887d8488b0`;SQLite 与 PG 双路径干净
- `frontend/`:Vite 8 + React 19 + TS 6 + Tailwind v4 + shadcn(radix-nova);`npm run build`/dev 通过,空页
- `docker-compose.yml`:postgres 16 + cognee 可起;api/mcp/web 注释占位
- 模型关键判定:工作区级实体无 project_id;api_key 用 revoked_at;activity 不可变;`metadata` 列 → 属性 `doc_metadata`;多态 target 枚举 `requirement/task/document/project/user`(扩展需迁移)
- cognee:官方镜像 `cognee/cognee:latest` = **1.4.1**,默认 auth=required;API 端口/健康端点待 05 票确认

## 立即要做的事(接 02 号票)

1. 读 `.scratch/zeichen-impl/issues/02-auth-permissions-slice.md`(Question 即任务)
2. 后端:账号+密码登录、会话(JWT/Cookie)、首用户引导(创建 admin)、成员添加(账号+角色,首登设密码)、API key 生命周期(仅 agent 签发/多 key 独立吊销/哈希存储/回看明文-管理员密码验证)、两级角色权限服务(admin 自动全项目 owner,判权只看角色)
3. Web:登录页、首用户引导注册页、用户菜单(改密码/退出)、项目列表页、成员管理页、Agent 管理页(含 key 管理/回看/吊销)
4. 测试:后端 pytest(认证流+权限矩阵)、前端组件测试(Vitest+RTL,需先装 Vitest 与 testing-library)
5. 完成后:ticket 追加 `## Answer`,`Status: resolved`,地图 Decisions so far 加一行;开 `03 需求任务切片`

## 关键约定

- **垂直切片**:每张票 = 后端 + MCP(如有)+ Web + 测试的完整闭环
- **测试**:后端 pytest 全量 + 前端 Vitest/RTL 组件测试,不做 E2E
- **技术栈**:FastAPI / SQLAlchemy 2.0+Alembic / 官方 mcp Python SDK(单代码库,api 与 mcp 共享 service 层,两进程入口)/ Vite+React+TS+Tailwind+Shadcn / React Router+TanStack Query(02 票起装)
- **登录**:账号+密码(username,不是邮箱);agent 走 API key
- **任务与需求**:五态状态机(待办→实现中→验收中→已完成,侧路已取消),自动流转
- **记忆**:100% 依赖 cognee(薄转接层),记忆删除透传 cognee 不软删
- 规格书 §9 列有待验证事实清单(实现时核对回填)

## 注意事项

- 地图/票/决策都在 `.scratch/` 下,是本地 markdown tracker(约定见 `docs/agents/issue-tracker.md`)
- 中文交流;有问题 grilling,不臆断规格
- Windows 环境坑:PowerShell 写 UTF-8 文件会坏中文(用 write 工具,不用 Set-Content);alembic.ini 保持 ASCII;TS 6 已弃用 `baseUrl`(paths 相对 tsconfig)
- shadcn CLI 读根 `tsconfig.json` 的 paths 解析别名(子 tsconfig 无效),`npx shadcn@latest add <comp>` 写错位时把 `@\` 目录内容移回 `src/`
