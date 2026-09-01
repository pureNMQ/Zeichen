# 贼船 Zeichen — 日常运维手册

> 所有命令默认在 `/srv/zeichen` 下执行;以下用 `zc` 表示:
> `docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml`
> 建议在服务器 `~/.bashrc` 加 `alias zc='docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml'`。

## 1. 日常巡检

```bash
zc ps                                   # 六服务状态(Exit/OOM 一目了然)
docker stats --no-stream                # 内存/CPU 实况(上限见 compose deploy.limits)
df -h /var/lib/docker /srv/zeichen      # 卷与备份磁盘占用
zc logs -f --tail=100 api               # 看某个服务日志(worker 见 memory improve 日志)
free -h                                 # swap 占用(异常高说明内存吃紧)
```

健康探针(可接外部监控):

```bash
curl -fsS https://<域名>/api/health
curl -fsS https://<域名>/.well-known/oauth-protected-resource/mcp
```

## 2. 升级 / 回滚

### 升级(代码或镜像)

```bash
# 0) 先备份(见 §3 backup.sh;升级前必须有当日全量备份)
cd /srv/zeichen && . ./.env && deploy/backup.sh
# 1) 拉新代码
git pull
# 2) 重建镜像并滚动升级(down 不删卷,数据安全)
zc up -d --build
# 3) 验证
zc ps; curl -fsS https://<域名>/api/health
```

要点(research/deployment.md §4):

- `.env` 改动只影响新容器:`zc up -d`(或 `zc restart <服务>`)即可,compose 定义
  改动才需要 `--force-recreate`。
- 基础镜像一律固定 tag(不追 `latest`/滚动 tag);cognee 走本项目
  `Dockerfile.cognee` 构建(内部固定 1.4.1-fastembed 版本线),升级即改 Dockerfile
  后 `zc up -d --build`。
- api 容器启动时自动跑 Alembic 迁移(mcp/worker 不迁移,只读共享库)。
- 升级后务必做一次真实 recall(验证记忆链路)+ 附件下载。

### 回滚

```bash
git checkout <上一版本 commit>          # 或恢复代码后
zc up -d --build
```

卷不动、数据不丢;前提是数据库 schema 向后兼容(回滚到旧代码前确认没有新迁移依赖)。

> **cognee 安全开关说明(REQ bc36ae8b)**:生产/环境覆盖层中的
> `ACCEPT_LOCAL_FILE_PATH` 刻意保持为 `"true"`——cognee 1.4.1 的会话蒸馏
> (improve→persist_sessions)会把自身生成的会话文本先落盘到 DATA_ROOT 再重新摄取,
> 该开关为 false 会阻断这条内部路径、蒸馏报 415 "Local files are not accepted"。
> Zeichen 从不向 cognee 传入客户端文件路径,且 cognee 不对宿主发布端口,故放行本地
> 文件只作用于 cognee 自身存储,不构成外部读文件面;其余加固
> (`REQUIRE_AUTHENTICATION`/`ALLOW_HTTP_REQUESTS=false`/`ALLOW_CYPHER_QUERY=false`)
> 保持不变。若未来升级 cognee 修复了该内部路径问题,可重新收紧此开关。

## 3. 备份 / 恢复

### 备份

每日自动:postgres 逻辑备份(`pg_dump | gzip`)+ cognee 数据卷 tar(短暂停服几秒)+
附件卷 tar → 本地 `/srv/zeichen/backups/` → 上传对象存储桶 `backup/<日期>/`。

- 本地保留 14 天(backup.sh 第一个参数可调),远端保留由桶生命周期规则控制(建议 30 天)。
- 手动跑一次:`cd /srv/zeichen && . ./.env && deploy/backup.sh`
- 检查:`ls -lh /srv/zeichen/backups/*/` 与对象存储控制台 `backup/` 前缀。

### 恢复(灾难恢复)

```bash
cd /srv/zeichen && . ./.env
deploy/restore.sh --yes latest    # 覆盖式恢复到最新备份(先确认!见脚本头部警告)
```

脚本流程:停 api/mcp/worker/web/cognee → 恢复 cognee 卷 → 附件卷 →
重建 postgres(dropdb + createdb + 导入)→ 重启并等 api 健康。

### 恢复演练(每月一次,research/deployment.md §2.2 checklist 第 5 条)

在**临时环境**演练,不动生产:

```bash
# 服务器或任意 Docker 主机
mkdir -p /tmp/zeichen-drill && cd /tmp/zeichen-drill
git clone https://github.com/pureNMQ/Zeichen.git .
cp deploy/.env.prod.example .env      # 填必填项(演练可用任意值)
mkdir -p certs && cp /srv/zeichen/certs/* certs/
# 用对象存储上最近的备份灌入(先下载三个文件到 drill/backups/ 对应子目录)
对象存储CLI download -r backup/<日期>/ ./backups/restore/    # 按脚本目录结构放好
# 独立 compose project 名(避免与生产卷/容器冲突):
docker compose -p zeichen-drill -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
BACKUP_ROOT=/tmp/zeichen-drill/backups \
  docker compose -p zeichen-drill -f docker-compose.yml -f deploy/docker-compose.prod.yml \
  exec -T api true   # 先确认环境起来
BACKUP_ROOT=/tmp/zeichen-drill/backups deploy/restore.sh --yes <日期>
# 验证:api 健康 + 登录 + 一次记忆 recall + 附件列表
```

> 演练通过的标准:恢复后的实例能登录、能看到恢复的数据、recall 有结果。
> 演练环境用完 `docker compose -p zeichen-drill down -v` 清理。

## 4. 证书续期

| 方式 | 续期动作 | 频率 |
|---|---|---|
| 云厂商免费证书 | 控制台 SSL 证书重新申请 → 下载 Nginx 格式 → 覆盖 `/srv/zeichen/certs/` 两个文件 → `docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml exec web nginx -s reload`(或 `zc restart web`) | 每年 |
| certbot | `sudo certbot renew`(standalone 方式需先 `zc stop web`;想免停机则改用 webroot 模式并把 `/.well-known/acme-challenge/` 挂载到 web 容器,见 deploy/nginx.conf 预留的 location) → 复制证书后 reload nginx | 每 60 天自动 |

建议在日历上标注免费证书到期前 2 周(证书过期后 HTTPS 立即报错,跳转 301 会把用户困在错误页)。

## 5. 危险命令红榜(写进交接,避免误操作)

| 命令 | 后果 |
|---|---|
| `zc down --volumes` | **删除全部数据卷**(pg/cognee/附件/模型缓存),不可恢复 |
| `rm -rf /srv/zeichen/backups` | 清空本地备份(未同步到异地的即丢失) |
| `zc stop cognee` 后忘记 start | cognee 停服期间记忆链路 502(backup.sh 已自动恢复) |
| 覆盖 `certs/privkey.pem` 前未备份 | 证书不匹配,HTTPS 全挂 |
| 在恢复演练环境执行 `zc up -d`(非 -p 独立项目名) | 误碰生产容器/卷 |

## 6. 容量与日常注意

- 磁盘:模型缓存(约 200MB)+ 备份(每日 ~百 MB 级,按数据量)+ 附件配额
  (单项目 2GB)。`df -h` 定期看;备份轮转自动清,关注对象存储计费即可。
- 内存:cognee 2G 上限是 ceiling;实测空闲量级远低于预算,4G 余量充足;突发用量由 2G swap 兜底。
- 软删物理清理:业务软删实体按规格书 §8.2 由定时任务清理(周期默认 90 天,
  该任务实现后挂 cron;当前版本为软删保留,可手动用 SQL 审计,勿手删)。
