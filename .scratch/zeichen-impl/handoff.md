# 交接:贼船 Zeichen 实现(本地可跑 v1)

> 本会话为 wayfinder 地图 `.scratch/zeichen-impl/map.md` 的接力点。新会话从本文档开始。

## 现状

- **仓库**:`D:\Projects\agent-ops`(git master,工作区干净)
- **规格书**(唯一依据):`docs/spec.md` v1.0(9 章,已定稿)
- **地图**:`.scratch/zeichen-impl/map.md`——7 张垂直切片构建票
- **已认领**:`01 工程骨架 + 数据模型 + 迁移`(Status: claimed,尚未开始动手)
- **环境**:Python 3.12.5、Node 24.15、npm 11.12;`D:\Projects\agent-ops\.venv` 已创建(空,未装包)
- **上一张地图**(agent-ops,已走完):11 张决策票全 resolved,Decisions so far 在 `.scratch/agent-ops/map.md`

## 立即要做的事(接 01 号票)

1. 读 `.scratch/zeichen-impl/issues/01-scaffold-data-model.md`(Question 即任务)
2. 搭仓库结构:`backend/`(FastAPI + SQLAlchemy 2.0 + Alembic)、`frontend/`(Vite + React + TS + Tailwind + Shadcn/ui)、`docker-compose.yml` 骨架
3. 规格书 §2.2 全部实体映射为 SQLAlchemy 模型(多态 comment/activity 的 check 约束、软删五件套、reference 枚举、memory_grant)
4. Alembic 首个迁移,`alembic upgrade head` 干净执行
5. 验证:backend 空 API 冒烟、frontend dev server 空页、pytest 冒烟;验证 cognee 官方镜像本地可用性(记入 Answer,供 05 记忆票用)
6. 完成后:在 ticket 追加 `## Answer`,`Status: resolved`,地图 Decisions so far 加一行;开 `02 认证权限闭环`

## 关键约定

- **垂直切片**:每张票 = 后端 + MCP(如有)+ Web + 测试的完整闭环
- **测试**:后端 pytest 全量 + 前端 Vitest/RTL 组件测试,不做 E2E
- **技术栈**:FastAPI / SQLAlchemy 2.0+Alembic / 官方 mcp Python SDK(单代码库,api 与 mcp 共享 service 层,两进程入口)/ Vite+React+TS+Tailwind+Shadcn / React Router+TanStack Query
- **登录**:账号+密码(username,不是邮箱);agent 走 API key
- **任务与需求**:五态状态机(待办→实现中→验收中→已完成,侧路已取消),自动流转
- **记忆**:100% 依赖 cognee(薄转接层),记忆删除透传 cognee 不软删
- 规格书 §9 列有待验证事实清单(实现时核对回填)

## 注意事项

- 地图/票/决策都在 `.scratch/` 下,是本地 markdown tracker(约定见 `docs/agents/issue-tracker.md`)
- 中文交流;有问题 grilling,不臆断规格
