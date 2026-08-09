# deploy/ — 生产部署产物

单机 Docker Compose 全栈部署(规格书 §8),目标:单机服务器 / Ubuntu 22.04/24.04 LTS。

| 文件 | 说明 |
|---|---|
| `docker-compose.prod.yml` | 生产 compose override(叠在根 `docker-compose.yml` 上):去宿主端口、密钥守卫、cognee 安全变量、资源上限 |
| `nginx.conf` | 生产 TLS nginx(TLS 终止、/api /mcp 反代、SSE 关缓冲、附件 25m、80→443) |
| `.env.prod.example` | 全变量清单(占位符;真实 `.env` 在服务器上填写,不入 git) |
| `backup.sh` | 每日备份:pg_dump + cognee 卷 + 附件卷 → 本地 + 异地对象存储 |
| `restore.sh` | 覆盖式恢复(灾难恢复 / 每月演练) |
| `docs/first-deploy.md` | 首次部署步骤(装 Docker → 镜像加速 → 证书 → .env → up -d → 首用户) |
| `docs/ops.md` | 日常运维:巡检、升级/回滚、备份恢复演练、证书续期、危险命令 |

## 快速命令(仓库根目录)

```bash
# 启动(生产,需先建 .env)
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build

# 查看 / 日志 / 重启
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml logs -f api

# 备份 / 恢复
deploy/backup.sh
deploy/restore.sh --yes latest
```

要求:Docker Compose ≥ 2.24(`!override` 标签 + `deploy.resources.limits` 生效)。
证书放仓库根 `certs/fullchain.pem` + `certs/privkey.pem`(已 gitignore)。
