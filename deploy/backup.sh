#!/usr/bin/env bash
# 贼船 Zeichen — 每日备份(research/deployment.md §2.2 checklist 落地)。
#
# 产出(默认本地目录,可用 BACKUP_ROOT 覆盖):
#   $BACKUP_ROOT/pg/<日期>.sql.gz              postgres 逻辑备份
#   $BACKUP_ROOT/cognee/<日期>.tar.gz          cognee 数据卷(data+system)
#   $BACKUP_ROOT/attachments/<日期>.tar.gz     附件卷
#   $BACKUP_ROOT/backup.log                    运行日志(cron 重定向到终端即可)
#
# 异地:装了 coscmd 且 ~/.cos.conf 存在时,自动上传当日三个文件到
#   COS_BUCKET / COS_REGION 指向的桶;远端保留由桶生命周期规则管理
#   (建议:prefix 按 backup/ 分,保留 30 天,见 deploy/docs/ops.md §3)。
#
# 用法:deploy/backup.sh [保留本地天数]   (默认 14 天)
# cron:0 3 * * * /srv/zeichen/deploy/backup.sh >> /srv/zeichen/backups/backup.log 2>&1
# 注意:日期用 UTC(容器时区),cron 为 UTC 凌晨 3 点即北京时间 11 点,避免本地备份高峰。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILES=(-f docker-compose.yml -f deploy/docker-compose.prod.yml)

BACKUP_ROOT="${BACKUP_ROOT:-/srv/zeichen/backups}"
KEEP_DAYS="${1:-14}"
DATE="$(date -u +%F)"

mkdir -p "$BACKUP_ROOT/pg" "$BACKUP_ROOT/cognee" "$BACKUP_ROOT/attachments"

log() { echo "[$(date -u '+%F %T')] $*"; }

cd "$PROJECT_ROOT"
COMPOSE=(docker compose "${COMPOSE_FILES[@]}")

# 1) postgres 逻辑备份(官方推荐,可跨版本恢复)
log "pg_dump 开始"
"${COMPOSE[@]}" exec -T postgres pg_dump -U zeichen -d zeichen \
    | gzip > "$BACKUP_ROOT/pg/$DATE.sql.gz"
test -s "$BACKUP_ROOT/pg/$DATE.sql.gz"
log "pg_dump 完成: $BACKUP_ROOT/pg/$DATE.sql.gz"

# 2) cognee 数据卷 tar(热拷贝图库有损坏风险,短暂停服几秒)
log "cognee 卷备份开始(短暂停服)"
"${COMPOSE[@]}" stop cognee > /dev/null
COGNEE_CID="$("${COMPOSE[@]}" ps -q cognee)"
if [ -z "$COGNEE_CID" ]; then
    log "错误:未找到 cognee 容器,跳过 cognee 卷备份"
    "${COMPOSE[@]}" start cognee > /dev/null
else
    docker run --rm --volumes-from "$COGNEE_CID" \
        -v "$BACKUP_ROOT/cognee:/backup" alpine \
        tar czf "/backup/cognee-$DATE.tar.gz" -C /app data system
    "${COMPOSE[@]}" start cognee > /dev/null
    test -s "$BACKUP_ROOT/cognee/cognee-$DATE.tar.gz"
    log "cognee 卷备份完成: $BACKUP_ROOT/cognee/cognee-$DATE.tar.gz"
fi

# 3) 附件卷 tar
log "附件卷备份开始"
API_CID="$("${COMPOSE[@]}" ps -q api)"
if [ -z "$API_CID" ]; then
    log "警告:未找到 api 容器,跳过附件卷备份"
else
    docker run --rm --volumes-from "$API_CID" \
        -v "$BACKUP_ROOT/attachments:/backup" alpine \
        tar czf "/backup/attachments-$DATE.tar.gz" -C /srv/zeichen/storage attachments
    test -s "$BACKUP_ROOT/attachments/attachments-$DATE.tar.gz"
    log "附件卷备份完成: $BACKUP_ROOT/attachments/attachments-$DATE.tar.gz"
fi

# 4) 本地轮转:清理 N 天前的旧文件
find "$BACKUP_ROOT/pg" -name '*.sql.gz' -mtime "+$KEEP_DAYS" -delete
find "$BACKUP_ROOT/cognee" -name '*.tar.gz' -mtime "+$KEEP_DAYS" -delete
find "$BACKUP_ROOT/attachments" -name '*.tar.gz' -mtime "+$KEEP_DAYS" -delete
log "本地轮转完成(保留 $KEEP_DAYS 天)"

# 5) 异地上传(coscmd 可用且已配置时)
if command -v coscmd > /dev/null 2>&1 && [ -f "$HOME/.cos.conf" ]; then
    : "${COS_BUCKET:?Set COS_BUCKET in environment or deploy/.env}"
    : "${COS_REGION:?Set COS_REGION in environment or deploy/.env}"
    REMOTE="backup/$DATE/"
    log "coscmd 上传到 cos://$COS_BUCKET/$REMOTE"
    coscmd upload -r -f "$BACKUP_ROOT/pg/$DATE.sql.gz" "$REMOTE"
    coscmd upload -r -f "$BACKUP_ROOT/cognee/cognee-$DATE.tar.gz" "$REMOTE"
    coscmd upload -r -f "$BACKUP_ROOT/attachments/attachments-$DATE.tar.gz" "$REMOTE"
    log "COS 上传完成"
else
    log "警告:未安装 coscmd 或 ~/.cos.conf 不存在,本次未做异地拷贝(见 docs/ops.md §3)"
fi

log "备份完成"
