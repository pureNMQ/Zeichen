# 01 工程骨架 + 数据模型 + 迁移

Status: open
Type: task
Blocked by:

## Question

搭建可运行的最小工程骨架并落地数据模型(规格书 §1/§2):
- 仓库结构:backend/(FastAPI + SQLAlchemy 2.0 + Alembic)、frontend/(Vite + React + TS + Tailwind + Shadcn/ui)、docker-compose.yml(骨架)
- 数据模型:规格书 §2.2 全部实体映射为 SQLAlchemy 模型(含多态 comment/activity 的 check 约束、软删五件套约定、reference 枚举、memory_grant)
- Alembic 迁移:首个迁移脚本可用,`alembic upgrade head` 干净执行
- 本地验证:backend 能起(空 API 冒烟)、frontend dev server 能起(空页)、pytest 冒烟通过

产出:可 clone 即跑的最小骨架 + 完整建表迁移。本票期间验证 cognee 官方镜像本地可用性(记入 Answer,供 09 用)。
