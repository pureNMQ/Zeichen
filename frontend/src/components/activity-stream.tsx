import { useQuery } from '@tanstack/react-query'

import { api, type ActivityRow } from '@/lib/api'
import { UserAvatar } from '@/components/user-avatar'

const ACTION_LABEL: Record<string, string> = {
  create: '创建',
  update: '更新',
  complete: '提交完成',
  accept: '验收通过',
  start: '开工',
  cancel: '取消',
  claim: '认领',
  assign: '指派',
  unassign: '解除指派',
  delete: '删除',
  restore: '恢复',
  comment: '评论',
  reference: '引用',
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
            {a.summary && <span className="min-w-0 truncate text-xs text-muted-foreground">— {a.summary}</span>}
            <span className="ml-auto shrink-0 text-xs text-muted-foreground">
              {new Date(a.created_at).toLocaleString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
