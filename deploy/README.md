# deploy/ — 生产部署产物

单机 Docker Compose 全栈部署(规格书 §8),目标:单机服务器 / Ubuntu 22.04/24.04 LTS。

| 文件 | 说明 |
|---|---|
| `docker-compose.prod.yml` | 生产 compose override(叠在根 `docker-compose.yml` 上):去宿主端口、密钥守卫、资源上限 |
| `nginx.conf` | 生产 TLS nginx(TLS 终止、/api /mcp 反代、SSE 关缓冲、附件 25m、80→443) |
| `.env.prod.example` | 全变量清单(占位符;真实 `.env` 在服务器上填写,不入 git) |
| `backup.sh` | 每日备份:pg_dump + 附件卷 → 本地 + 异地对象存储 |
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

## v2 首次切换

用同一个已验证候选提交的脚本、镜像和恢复证据。先在远端隔离构建后做合成恢复演练。下列变量是实际路径和名称的示例。保留证据目录私有。

```bash
umask 077
root=/srv/zeichen
tools=/path/to/verified-candidate/source/deploy
result=/path/to/verified-candidate/result.json
rehearsal=/path/to/new/synthetic-rehearsal
python3 "$tools/rehearse_v2_cutover.py" --candidate "$result" --output "$rehearsal"
```

确认部署和恢复窗口后，按顺序关闭业务写入、生成同一窗口的备份并准备独立目标。旧 Compose 必须是当前 v1 固定镜像的私有已解析配置，可从 `.release/current.json` 的 `compose_file` 核对。目标网络须与实际 PostgreSQL 和 Zeichen 应用网络一致。

```bash
state=cutover-20261117
work="$root/.release/$state"
old_compose=/path/to/current-v1/compose.json
python3 "$tools/cutover_v2.py" --root "$root" --state "$state" freeze --legacy-compose "$old_compose"
python3 "$tools/prepare_v2_cutover.py" \
  --snapshot "$work/snapshot" --candidate "$result" --output "$work/prepared" \
  --postgres zeichen-postgres-1 --network zeichen_default --target zeichen_v2_20261117 \
  --snapshot-writes-frozen
```

`freeze` 同时关闭 TLS 业务路径和 HTTP 上直接代理的 API、MCP，先停止旧 API、MCP 和 Worker，再等待旧入口工作进程退出，最后备份原库及原卷。MochiSite、ACME 和未知域名处理保持原样。备份和准备失败的状态保存在私有 `status.json` 或 `prepared.json` 中。

在私有 `acceptance.json` 中记录如下格式。表中的每一项都应指向真实证据，`checks` 必须完整包含 `AC-01` 至 `AC-31`。SHA-256 分别取本次 `prepared.json` 和同一候选提交的 `rehearsal.json`。迁移例外经过核对并接受后才把 `migration_exceptions_reviewed` 写为 `true`。

```json
{
  "candidate_commit": "<本次完整 Git SHA>",
  "prepared_manifest_sha256": "<本次 prepared.json 的 SHA-256>",
  "migration_exceptions_reviewed": true,
  "checks": {
    "AC-01": {"passed": true, "evidence": "<实际报告或日志位置>"}
  },
  "restore_rehearsal": {
    "path": "/path/to/synthetic-rehearsal/rehearsal.json",
    "sha256": "<verified 同提交恢复演练的 SHA-256>"
  }
}
```

`stage`只启动固定镜像的 API、MCP 和前端，验证独立数据库、附件卷及一次性维护，继续禁止写入。公网只放行 TLS 上 `GET/HEAD /`、`/api/health` 和 `/.well-known/oauth-protected-resource/mcp`，以及原有 MochiSite 与 ACME。可核对 API 健康、MCP 元数据、前端指纹和 MochiSite；完整 MCP 握手和认证、业务写入使用隔离演练，生产验证只使用获准的专用测试身份。

```bash
python3 "$tools/cutover_v2.py" --root "$root" --state "$state" stage \
  --prepared "$work/prepared/prepared.json" --acceptance "$work/acceptance.json"
# 检查无凭据探测和 status.json 的 staged 状态后，显式开放写入
python3 "$tools/cutover_v2.py" --root "$root" --state "$state" open
```

生产健康检查通过后，使用候选内的 Compose 和 systemd 单元启用 v2 定时维护。旧 Worker 已在停写时停止。切换工具会提供此前通过一次性验证的 `maintenance.env`，以相同镜像、数据库、网络和文件卷作为定时任务输入。

```bash
sudo install -m 0600 "$work/maintenance.env" "$root/.release/v2-maintenance.env"
sudo install -m 0644 "$tools/docker-compose.maintenance.yml" "$root/deploy/docker-compose.maintenance.yml"
sudo install -m 0644 "$tools/systemd/zeichen-v2-maintenance.service" /etc/systemd/system/
sudo install -m 0644 "$tools/systemd/zeichen-v2-maintenance.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start zeichen-v2-maintenance.service
sudo systemctl enable --now zeichen-v2-maintenance.timer
```

开放前可执行 `python3 "$tools/cutover_v2.py" --root "$root" --state "$state" rollback`。它通过没被改写的旧库、原卷和旧镜像恢复 v1。进入 `opening` 即视为可能已有 v2 写入，自动回退会拒绝。此时如有故障，先保持停写并保全 v2 库和文件卷，再决定修复或如何处理增量。首次 v2 切换使用本节流程。旧 `-AllowMigration` 原位迁移流程不用于 v2。
