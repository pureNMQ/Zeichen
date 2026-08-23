import { useCallback, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api, type NotificationRow } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

const ACTION_LABEL: Record<string, string> = {
  create: '创建',
  update: '更新',
  status: '变更状态',
  comment: '评论',
  assign: '指派',
  claim: '认领',
  unassign: '解除指派',
  delete: '删除',
  restore: '恢复',
  attachment: '上传附件',
  attachment_delete: '删除附件',
  attachment_restore: '恢复附件',
  reference: '添加引用',
  memory_remember: '写入记忆',
  memory_improve: '蒸馏记忆',
  memory_forget: '删除记忆',
}

const TARGET_LABEL: Record<string, string> = {
  requirement: '需求',
  task: '任务',
  document: '文档',
  project: '项目',
}

function targetHref(targetType: string, targetId: string): string {
  switch (targetType) {
    case 'requirement':
      return `/requirements/${targetId}`
    case 'task':
      return `/tasks/${targetId}`
    case 'document':
      return `/documents/wiki/${targetId}`
    default:
      return '/projects'
  }
}

export function NotificationBell() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)

  const { data: count = 0 } = useQuery({
    queryKey: ['notifications', 'unread-count'],
    queryFn: () => api.get<{ count: number }>('/notifications/unread-count').then((r) => r.count),
    refetchInterval: 30_000,
  })

  const { data, isLoading } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.get<{ items: NotificationRow[] }>('/notifications?limit=20'),
    enabled: open,
  })

  const openNotification = useCallback(
    async (n: NotificationRow) => {
      if (!n.read) {
        try {
          await api.post(`/notifications/${n.id}/read`)
          await queryClient.invalidateQueries({ queryKey: ['notifications', 'unread-count'] })
        } catch {
          // 已读失败不阻断跳转
        }
      }
      setOpen(false)
      navigate(targetHref(n.target_type, n.target_id))
    },
    [navigate, queryClient],
  )

  const markAllRead = useCallback(async () => {
    try {
      await api.post('/notifications/read-all')
      await queryClient.invalidateQueries({ queryKey: ['notifications', 'unread-count'] })
      await queryClient.invalidateQueries({ queryKey: ['notifications'] })
    } catch {
      // 已读失败保持现状
    }
  }, [queryClient])

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="通知" className="shrink-0">
          <span className="relative">
            <Bell className="h-4 w-4" />
            {count > 0 && (
              <span className="absolute -top-1.5 -right-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-destructive-foreground">
                {count > 99 ? '99+' : count}
              </span>
            )}
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-80">
        <DropdownMenuLabel className="flex items-center justify-between">
          <span>通知</span>
          {count > 0 && (
            <button
              type="button"
              className="text-xs text-primary hover:underline"
              onClick={() => void markAllRead()}
            >
              一键已读
            </button>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {isLoading ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">加载中…</div>
        ) : !data?.items || data.items.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">暂无通知</div>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            {data.items.map((n) => (
              <DropdownMenuItem
                key={n.id}
                className={cn('flex-col items-start gap-1 py-2', !n.read && 'bg-muted/50 font-medium')}
                onSelect={() => void openNotification(n)}
              >
                <span className="line-clamp-2 text-sm">
                  {TARGET_LABEL[n.target_type] ?? n.target_type}
                  {n.summary ? ` · ${n.summary}` : ''}
                </span>
                <span className="text-xs text-muted-foreground">
                  {ACTION_LABEL[n.action] ?? n.action}
                  {n.read ? '' : ' · 未读'}
                </span>
              </DropdownMenuItem>
            ))}
          </div>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
