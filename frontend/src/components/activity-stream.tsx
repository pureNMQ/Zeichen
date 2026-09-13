import { useQuery } from '@tanstack/react-query'

import { api, STATUS_LABEL, type ActivityRow } from '@/lib/api'
import { UserAvatar } from '@/components/user-avatar'

const ACTION_LABEL: Record<string, string> = {
  create: '创建',
  update: '更新',
  complete: '提交完成',
  accept: '验收通过',
  start: '开工',
  status: '变更状态',
  cancel: '取消',
  claim: '认领',
  assign: '指派',
  unassign: '解除指派',
  delete: '删除',
  restore: '恢复',
  comment: '评论',
  reference: '引用',
}

const TARGET_TYPE_LABEL: Record<string, string> = {
  requirement: '需求',
  task: '任务',
  document: '文档',
  repository: '代码仓库',
  project: '项目',
}

// 历史 summary 按英文枚举落库,展示层做兼容映射;新记录已是中文,原样通过。
function localizeSummary(summary: string): string {
  const statusChange = summary.match(/^([a-z_]+) → ([a-z_]+)$/)
  if (statusChange && STATUS_LABEL[statusChange[1] as keyof typeof STATUS_LABEL] && STATUS_LABEL[statusChange[2] as keyof typeof STATUS_LABEL]) {
    return `${STATUS_LABEL[statusChange[1] as keyof typeof STATUS_LABEL]} → ${STATUS_LABEL[statusChange[2] as keyof typeof STATUS_LABEL]}`
  }
  // 短码(ADR 0002):REQ-1 等直接展示;旧 UUID 文本(死文本)保留前 8 位省略显示
  const shortCode = summary.match(/^引用 ([a-z_]+):((?:REQ|TASK|DOC|TERM|DIR)-[1-9][0-9]*)$/)
  if (shortCode && TARGET_TYPE_LABEL[shortCode[1]]) {
    return `引用 ${TARGET_TYPE_LABEL[shortCode[1]]}:${shortCode[2]}`
  }
  const reference = summary.match(/^引用 ([a-z_]+):([0-9a-f-]{36})$/)
  if (reference && TARGET_TYPE_LABEL[reference[1]]) {
    return `引用 ${TARGET_TYPE_LABEL[reference[1]]}:${reference[2].slice(0, 8)}…`
  }
  return summary
}

export function ActivityStream({ targetType, targetId }: { targetType: string; targetId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['activity', targetType, targetId],
    queryFn: () => api.get<{ items: ActivityRow[] }>(`/targets/${targetType}/${targetId}/activity?limit=50`),
  })

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold">活动</h3>
      <div className="space-y-1.5">
        {isLoading && <p className="text-xs text-muted-foreground">加载中…</p>}
        {(data?.items ?? []).map((a) => (
          <div key={a.id} className="flex items-center gap-2 text-sm">
            <span className="inline-flex shrink-0 items-center gap-2 font-medium">
              <UserAvatar user={{ id: a.actor_id, username: a.actor, avatar: a.actor_avatar }} className="h-6 w-6" />
              {a.actor}
            </span>
            <span className="shrink-0 text-xs text-muted-foreground">{ACTION_LABEL[a.action] ?? a.action}</span>
            {a.summary && <span className="min-w-0 truncate text-xs text-muted-foreground">— {localizeSummary(a.summary)}</span>}
            <span className="ml-auto shrink-0 text-xs text-muted-foreground">
              {new Date(a.created_at).toLocaleString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
