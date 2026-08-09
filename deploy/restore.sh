#!/usr/bin/env bash
# 贼船 Zeichen — 从备份恢复(灾难恢复 / 每月恢复演练)。
#
# 用法:deploy/restore.sh [--yes] <日期|latest>
#   --yes     跳过确认提示(演练/自动化用)
#   <日期>    2026-08-09;latest = $BACKUP_ROOT/pg 下最新的 sql.gz 对应的日期
#
# 流程:停 api/mcp/worker/web/cognee → 恢复 cognee 卷 → 恢复附件卷 →
#       重建 postgres(先 dropdb 再 createdb)→ 导入 pg 备份 → 全部重启。
#
# 注意:
#   * 本脚本是破坏性的——会把当前数据覆盖为 <日期> 的备份,确认无误再执行。
#   * 恢复演练建议在临时 clone + 新卷环境做(docs/ops.md §3 恢复演练步骤)。
#   * 依赖同一套 backup.sh 的产物目录结构。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILES=(-f docker-compose.yml -f deploy/docker-compose.prod.yml)
BACKUP_ROOT="${BACKUP_ROOT:-/srv/zeichen/backups}"

cd "$PROJECT_ROOT"
COMPOSE=(docker compose "${COMPOSE_FILES[@]}")

YES=0
if [ "${1:-}" = "--yes" ]; then YES=1; shift; fi
DATE_ARG="${1:-}"
if [ -z "$DATE_ARG" ]; then
    echo "用法: $0 [--yes] <日期|latest>" >&2
    exit 1
fi
if [ "$DATE_ARG" = "latest" ]; then
    LATEST_FILE="$(ls -1t "$BACKUP_ROOT/pg/"*.sql.gz 2>/dev/null | head -n1 || true)"
    if [ -z "$LATEST_FILE" ]; then
        echo "错误: $BACKUP_ROOT/pg 下没有备份文件" >&2
        exit 1
    fi
    DATE="$(basename "$LATEST_FILE" .sql.gz)"
else
    DATE="$DATE_ARG"
fi

PG_DUMP="$BACKUP_ROOT/pg/$DATE.sql.gz"
COGNEE_TAR="$BACKUP_ROOT/cognee/cognee-$DATE.tar.gz"
ATTACH_TAR="$BACKUP_ROOT/attachments/attachments-$DATE.tar.gz"
for f in "$PG_DUMP" "$COGNEE_TAR" "$ATTACH_TAR"; do
    [ -f "$f" ] || { echo "错误: 缺少备份文件 $f" >&2; exit 1; }
done

echo "将把当前数据恢复为 $DATE 的备份:"
echo "  $PG_DUMP"
echo "  $COGNEE_TAR"
echo "  $ATTACH_TAR"
if [ "$YES" -ne 1 ]; then
    read -r -p "确认覆盖当前数据?输入 yes 继续: " CONFIRM
    [ "$CONFIRM" = "yes" ] || { echo "已取消"; exit 1; }
fi

# 1) 停应用服务与 cognee(postgres 保持运行,pg 恢复要用)
"${COMPOSE[@]}" stop api mcp worker web cognee > /dev/null
echo "已停止 api/mcp/worker/web/cognee"

# 2) 恢复 cognee 卷(data + system)
COGNEE_CID="$("${COMPOSE[@]}" ps -q cognee)"
if [ -z "$COGNEE_CID" ]; then
    echo "错误: 未找到 cognee 容器(需先 up 过一次)" >&2
    exit 1
fi
docker run --rm --volumes-from "$COGNEE_CID" \
    -v "$BACKUP_ROOT/cognee:/backup" alpine \
    sh -c 'rm -rf /app/data/* /app/system/* && tar xzf /backup/cognee-'"$DATE"'.tar.gz -C /app'
echo "cognee 卷已恢复"

# 3) 恢复附件卷
API_CID="$("${COMPOSE[@]}" ps -q api)"
if [ -z "$API_CID" ]; then
    echo "错误: 未找到 api 容器" >&2
    exit 1
fi
docker run --rm --volumes-from "$API_CID" \
    -v "$BACKUP_ROOT/attachments:/backup" alpine \
    sh -c 'rm -rf /srv/zeichen/storage/attachments/* && tar xzf /backup/attachments-'"$DATE"'.tar.gz -C /srv/zeichen/storage'
echo "附件卷已恢复"

# 4) 重建 postgres 并导入
"${COMPOSE[@]}" exec -T postgres dropdb --if-exists -U zeichen zeichen
"${COMPOSE[@]}" exec -T postgres createdb -U zeichen zeichen
gunzip -c "$PG_DUMP" | "${COMPOSE[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 -U zeichen -d zeichen > /dev/null
echo "postgres 已恢复"

# 5) 全量重启,等待 api 健康
"${COMPOSE[@]}" start > /dev/null
echo "等待 api 健康检查..."
for i in $(seq 1 30); do
    if "${COMPOSE[@]}" exec -T api python -c \
        "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" > /dev/null 2>&1; then
        echo "恢复完成,api 健康"
        exit 0
    fi
    sleep 2
done
echo "错误: 恢复后 api 60 秒内未健康,请检查 docker compose ps / logs" >&2
exit 1
