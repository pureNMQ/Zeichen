# 贼船 Zeichen — 首次部署(腾讯云轻量 2C4G / Ubuntu 22.04/24.04 LTS)

目标:单机 Docker Compose 全栈(nginx → web/api/mcp/worker/cognee/postgres),
唯一公网入口 80/443(TLS),数据全部在命名卷,每日备份到 COS。
参考:docs/spec.md §8、research/deployment.md。

> 时长参考:服务器准备 ~30 分钟 + 首次构建拉镜像/模型 10~30 分钟(网络而定)。
> 前置(尽早并行):域名 + ICP 备案(1–2 周)+ 免费 SSL 证书(备案通过后才能签发使用)。

---

## 0. 云主机与网络准备

1. 轻量应用服务器:2C4G、Ubuntu 24.04 LTS(22.04 亦可),地域就近。
2. 安全组/防火墙:只放行 **22 / 80 / 443**(默认已含 22 与 80)。
3. 建议固定公网 IP 或绑定弹性 IP;域名解析 A 记录指向公网 IP。

## 1. 系统准备

```bash
# swap 2G 兜底(4G 内存下 docker 资源上限触发 OOM 前的缓冲)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo sysctl vm.swappiness=10

# 时区与基础包(可选但推荐)
sudo timedatectl set-timezone Asia/Shanghai
```

## 2. 安装 Docker(官方源)+ Compose 插件

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # 重新登录后生效,或用 sudo 执行 docker 命令
docker compose version          # 必须 >= 2.24(本部署用到 !override 与资源上限;v2.39 已确认可用)
```

## 3. 配置腾讯云内网镜像加速(可选但强烈推荐,Docker Hub 直连不稳定)

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "registry-mirrors": ["https://mirror.ccs.tencentyun.com"]
}
EOF
sudo systemctl restart docker
# 验证
docker info | grep -A2 "Registry Mirrors"
docker pull hello-world   # 应能成功拉取
```

> 注:该地址为腾讯云内网 Docker 镜像加速(仅腾讯云 CVM/轻量内网可达)。
> 若拉取仍失败,可直接换阿里云/网易公开加速地址(镜像地址以腾讯云当前文档为准,
> 控制台「容器镜像服务 → 镜像加速器」可查到最新地址)。

## 4. 部署代码

```bash
sudo mkdir -p /srv/zeichen && sudo chown $USER /srv/zeichen
cd /srv/zeichen
git clone https://github.com/pureNMQ/Zeichen.git .
# 或:本地打包上传(不含 .env/.venv/backend/.lbdb-extension):
#   git archive --format=tar.gz -o zeichen.tar.gz HEAD 上传后解压
```

## 5. TLS 证书(二选一)

证书放到 `/srv/zeichen/certs/`,文件名固定:

| 文件 | 内容 |
|---|---|
| `certs/fullchain.pem` | 证书链(含域名证书 + 中间证书) |
| `certs/privkey.pem` | 私钥 |

### 方式 A:腾讯云免费证书(推荐,备案通过后)

1. 控制台 → SSL 证书 → 申请免费证书(TrustAsia DV,单域名,有效期 1 年)。
2. 签发后下载 **Nginx** 格式,解压得到 `xxx_bundle.crt` 与 `xxx.key`:

```bash
mkdir -p /srv/zeichen/certs
cp <下载目录>/xxx_bundle.crt /srv/zeichen/certs/fullchain.pem
cp <下载目录>/xxx.key        /srv/zeichen/certs/privkey.pem
chmod 600 /srv/zeichen/certs/privkey.pem
```

### 方式 B:certbot(Let's Encrypt,自动续期,需 80 端口可被公网访问)

```bash
sudo apt-get install -y certbot
sudo certbot certonly --standalone -d zeichen.example.com
# 复制证书:
sudo cp /etc/letsencrypt/live/zeichen.example.com/fullchain.pem /srv/zeichen/certs/
sudo cp /etc/letsencrypt/live/zeichen.example.com/privkey.pem /srv/zeichen/certs/
sudo chmod 600 /srv/zeichen/certs/privkey.pem
```

> 两种方式都要求先有域名解析且公网 80/443 可达;备案未完成时证书签发验证可能失败。

## 6. 环境变量

```bash
cd /srv/zeichen
cp deploy/.env.prod.example .env
chmod 600 .env
# 逐项填写,生成随机值:
openssl rand -hex 32    # SESSION_SECRET
openssl rand -hex 24    # POSTGRES_PASSWORD
openssl rand -hex 32    # COGNEE_FASTAPI_USERS_JWT_SECRET
```

必填变量清单(缺失时 `up` 直接报错):`DEEPSEEK_API_KEY`、`SESSION_SECRET`、
`POSTGRES_PASSWORD`、`WEB_BASE_URL`、`MCP_ALLOWED_HOSTS`(含 `<域名>:443`)、
`MCP_ISSUER_URL`、`MCP_RESOURCE_SERVER_URL`、`COGNEE_FASTAPI_USERS_JWT_SECRET`、
`COGNEE_CORS_ALLOWED_ORIGINS`。

## 7. 首次启动

```bash
cd /srv/zeichen
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml ps   # 六个服务
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml logs -f cognee   # 首次:嵌入模型下载
```

要点:

- api 容器会自动跑 `alembic upgrade head` 建表;cognee 首次写入记忆时下载
  embedding 模型(sentence-transformers/all-MiniLM-L6-v2,~90MB,已持久化到卷)。
- 之后统一别名:`alias zc='docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml'`。

## 8. 首用户引导与验收

1. 浏览器打开 `https://<域名>` → 首次访问进入 bootstrap 页,创建管理员账号
   (后端 `POST /api/auth/bootstrap`;未创建任何用户前该页只允许建首个账号)。
2. 建一个项目;建 agent 并签发 API key(项目设置/成员管理里)。
3. 验收清单:

```bash
# api 健康
curl -fsS https://<域名>/api/health
# MCP 元数据端点(RFC 9728,应看到配置的公开 URL)
curl -fsS https://<域名>/.well-known/oauth-protected-resource/mcp | python3 -m json.tool
# 手动证书场景检查证书链
echo | openssl s_client -connect <域名>:443 -servername <域名> 2>/dev/null | openssl x509 -noout -subject -dates
```

4. 用任意 MCP 客户端(如 opencode/Codex)配置:`url=https://<域名>/mcp`,
   `Authorization: Bearer <agent key>`,应能 initialize 并列出工具。
5. 上传一个 >1MB 的附件(验证 nginx `client_max_body_size`),再上传 20MB 边界值。

## 9. 配置备份(异地 COS)

1. 腾讯云控制台开通 COS 存储桶(如 `zeichen-backup-125xxxxxx`,地域就近),
   建议开生命周期规则:prefix `backup/` 保留 30 天。
2. 服务器上装 coscmd(官方 COS CLI):

```bash
pip3 install coscmd
coscmd config -a <SecretId> -s <SecretKey> -b zeichen-backup-125xxxxxx -r ap-guangzhou
# SecretId/SecretKey:访问管理 CAM → API 密钥(最小权限:只授权该桶)
```

3. 定时任务(UTC 凌晨 3 点 = 北京 11 点,避开备份高峰):

```bash
chmod +x /srv/zeichen/deploy/backup.sh /srv/zeichen/deploy/restore.sh
sudo mkdir -p /srv/zeichen/backups
# 已省略:将 COS_BUCKET / COS_REGION 追加到 /srv/zeichen/.env(backup.sh 读宿主环境或 .env 均可)
(crontab -l 2>/dev/null; echo '0 3 * * * cd /srv/zeichen && . ./.env && deploy/backup.sh >> /srv/zeichen/backups/backup.log 2>&1') | crontab -
```

> backup.sh 的 `. ./.env` 只为取 COS_BUCKET/COS_REGION,其余变量不读取。
> 首次手动跑一次:`cd /srv/zeichen && . ./.env && deploy/backup.sh`,检查
> `/srv/zeichen/backups/` 三个文件与 COS 桶内 `backup/<日期>/`。

## 10. 上线前 checklist(对照 research/deployment.md §2.2 / §3.3)

- [ ] 安全组仅 22/80/443;SSH 建议改为密钥登录并禁用密码
- [ ] `.env` 权限 600、不入 git;密钥全部是随机长串
- [ ] `docker compose config` 无警告;`zc ps` 六服务 running/healthy
- [ ] HTTPS 证书链正常、80 强制跳转 443
- [ ] MCP 元数据端点返回域名地址;MCP 客户端带 Bearer 可连
- [ ] 每日备份 cron 已跑通一次,coscmd 已上传,桶生命周期已配
- [ ] 已做过一次恢复演练(见 docs/ops.md §3)

之后的一切运维:deploy/docs/ops.md。
