# 04 部署与运维方案

Status: resolved
Type: research
Blocked by:

## Question

调研并起草单机 Docker Compose 部署方案:
- 服务划分:web / api / mcp / cognee / postgres / 反向代理(TLS)的镜像与端口规划;mcp 是独立容器还是 api 进程内的另一个面
- 数据持久化与备份:postgres 卷、cognee 数据目录(Kuzu/LanceDB/SQLite)的备份策略
- 安全基线:公网入口、密钥管理(.env)、首用户引导
- 升级与回滚的简单路径

产出:compose 骨架草案与备选方案,写入 research/deployment 分支,链接回本 ticket。

## Answer

已由 research 子代理解决,完整事实清单见 research/deployment.md(commit c48fce5)。

要点:
- 镜像事实更正:ghcr.io/topoteretes/cognee 不存在;官方镜像为 Docker Hub 的 cognee/cognee(API)与 cognee/cognee-mcp,main 为滚动 tag
- 服务布局:唯一公网入口是反向代理(80/443,TLS 终止);postgres/cognee/api 不发布宿主端口;React SPA 多阶段构建为静态文件由 nginx 服务,/api、/mcp 反代到后端
- mcp 独立容器:远程部署只有 Streamable HTTP 一种形态;cognee 官方生产形态为后端 + 独立 mcp 容器(API 模式);推荐独立容器、TRANSPORT_MODE=http、端点 /mcp
- 持久化:cognee 数据在 DATA_ROOT_DIRECTORY / SYSTEM_ROOT_DIRECTORY 两目录,必须挂命名卷;官方 compose 的 postgres_data 卷声明了但没挂载,照抄会丢库
- 备份:pg_dump 每日逻辑备份;cognee 文件数据停服 tar/rsync;.env 单独归档 + 异地拷贝 + 每月恢复演练
- 安全:ENABLE_BACKEND_ACCESS_CONTROL=True 默认;FASTAPI_USERS_JWT_SECRET 默认 super_secret 必须改;.env 用  守卫
- 升级/回滚:固定镜像 tag、compose pull && up -d;cognee Alembic 迁移由 api 侧跑,mcp 以 --no-migration 启动

注:mcp 独立容器 vs 挂进 api 进程的选择,留待 11 规格书成稿时裁定。
