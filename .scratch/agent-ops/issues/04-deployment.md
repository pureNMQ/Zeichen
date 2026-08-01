# 04 部署与运维方案

Status: open
Type: research
Blocked by:

## Question

调研并起草单机 Docker Compose 部署方案:
- 服务划分:web / api / mcp / cognee / postgres / 反向代理(TLS)的镜像与端口规划;mcp 是独立容器还是 api 进程内的另一个面
- 数据持久化与备份:postgres 卷、cognee 数据目录(Kuzu/LanceDB/SQLite)的备份策略
- 安全基线:公网入口、密钥管理(.env)、首用户引导
- 升级与回滚的简单路径

产出:compose 骨架草案与备选方案,写入 research/deployment 分支,链接回本 ticket。
