import { useState } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ErrorNotification } from '@/components/ui/notification'
import { cn } from '@/lib/utils'

type Notice = {
  id: string
  source_kind: 'timeline' | 'wiki'
  source_path: string
  source_code: string
  visibility: 'shared' | 'owner_only'
  reply_user_id: string | null
  read_at: string | null
}

export function NotificationBell() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [opening, setOpening] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: count = 0 } = useQuery({
    queryKey: ['notifications-v2', 'unread-count'],
    queryFn: () => api.get<{ count: number }>('/v2/notifications/unread-count').then((r) => r.count ?? 0),
    refetchInterval: 30_000,
  })
  const feed = useInfiniteQuery({
    queryKey: ['notifications-v2', 'feed'],
    initialPageParam: '' as string,
    queryFn: ({ pageParam }) => api.get<{ items: Notice[]; next_cursor: string | null }>(
      `/v2/notifications?${new URLSearchParams({ limit: '20', ...(pageParam ? { cursor: pageParam } : {}) })}`,
    ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: open,
  })
  const items = feed.data?.pages.flatMap((page) => page.items ?? []) ?? []

  async function openNotification(item: Notice) {
    setError(null)
    setOpening(true)
    try {
      const current = await api.post<Notice>(`/v2/notifications/${item.id}/open`)
      if (!current.source_path?.startsWith('/projects/')) throw new Error('通知来源不可用')
      setOpen(false)
      navigate(current.source_path)
    } catch (err) {
      setError(err instanceof Error ? err.message : '打开通知失败，请重试')
    } finally {
      setOpening(false)
      await queryClient.invalidateQueries({ queryKey: ['notifications-v2'] })
    }
  }

  return (
    <>
      <ErrorNotification message={error ?? feed.error?.message} />
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
          <DropdownMenuLabel>通知</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {feed.isLoading && <p className="p-3 text-sm text-muted-foreground" role="status">加载中…</p>}
          {!feed.isLoading && !feed.isError && items.length === 0 && (
            <p className="p-3 text-sm text-muted-foreground">暂无通知</p>
          )}
          <div className="max-h-96 overflow-y-auto">
            {items.map((item) => (
              <DropdownMenuItem key={item.id} disabled={opening}
                className={cn('flex-col items-start gap-1 py-2', !item.read_at && 'bg-muted/50 font-medium')}
                onSelect={(event) => { event.preventDefault(); void openNotification(item) }}>
                <span>{item.reply_user_id ? '有人回复了你的记录' : '有人提及了你'} · {item.source_code}</span>
                <span className="text-xs text-muted-foreground">
                  {item.source_kind === 'wiki' ? 'Wiki' : '需求时间轴'}
                  {item.visibility === 'owner_only' ? ' · 仅主人可见' : ''}
                  {!item.read_at ? ' · 未读' : ''}
                </span>
              </DropdownMenuItem>
            ))}
          </div>
          {(feed.hasNextPage || feed.isError) && (
            <DropdownMenuItem disabled={feed.isFetching} onSelect={(event) => {
              event.preventDefault()
              void (feed.hasNextPage ? feed.fetchNextPage() : feed.refetch())
            }}>
              {feed.isError ? '重试' : '加载更多'}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  )
}
