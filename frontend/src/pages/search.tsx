import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { Loader2, Search } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ErrorNotification } from '@/components/ui/notification'
import { api, type SearchItem } from '@/lib/api'
import { cn } from '@/lib/utils'

const DOMAIN_LABEL: Record<SearchItem['domain'], string> = {
  requirement: '需求',
  task: '任务',
  document: '文档',
  memory: '记忆',
}

const STATUS_LABEL: Record<string, string> = {
  backlog: '待办',
  in_progress: '实现中',
  verifying: '验收中',
  done: '已完成',
  cancelled: '已取消',
}

function hrefOf(item: SearchItem): string {
  switch (item.domain) {
    case 'requirement':
      return `/requirements/${item.id}`
    case 'task':
      return `/tasks/${item.id}`
    case 'document':
      return `/documents/wiki/${item.id}`
    default:
      return '/projects'
  }
}

export function SearchPage() {
  const [params] = useSearchParams()
  const query = params.get('q') ?? ''

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['search', query],
    queryFn: () => api.get<{ items: SearchItem[] }>(`/search?q=${encodeURIComponent(query)}`),
    enabled: query.trim().length > 0,
  })

  const grouped = useMemo(() => {
    const groups: { domain: SearchItem['domain']; items: SearchItem[] }[] = []
    const order: SearchItem['domain'][] = ['requirement', 'task', 'document', 'memory']
    for (const domain of order) {
      const items = (data?.items ?? []).filter((item) => item.domain === domain)
      if (items.length > 0) groups.push({ domain, items })
    }
    return groups
  }, [data])

  const errorMessage = isError && error instanceof Error ? error.message : null

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold">全局搜索</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {query.trim() ? <>关键词：{query}</> : '输入关键词跨项目搜索'}
        </p>
      </div>
      <ErrorNotification message={errorMessage} />
      {query.trim() && isLoading && (
        <div className="flex items-center justify-center gap-2 py-12 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" /> 搜索中…
        </div>
      )}
      {query.trim() && !isLoading && grouped.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
            <Search className="h-8 w-8" />
            <p className="text-sm">没有找到与「{query}」相关的内容</p>
          </CardContent>
        </Card>
      )}
      {grouped.map((group) => (
        <section key={group.domain} className="space-y-2">
          <h2 className="text-sm font-semibold text-muted-foreground">
            {DOMAIN_LABEL[group.domain]}
            <span className="ml-1 text-xs">({group.items.length})</span>
          </h2>
          <div className="space-y-2">
            {group.items.map((item) => (
              <Link key={`${item.domain}:${item.id}`} to={hrefOf(item)} className="block">
                <Card className="transition-colors hover:bg-muted/50">
                  <CardContent className="space-y-1.5 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{item.title}</span>
                      {item.status && (
                        <Badge variant="secondary" className={cn('text-xs')}>
                          {STATUS_LABEL[item.status] ?? item.status}
                        </Badge>
                      )}
                      {item.doc_type && (
                        <Badge variant="outline" className="text-xs">
                          {item.doc_type === 'wiki' ? 'Wiki' : '词条'}
                        </Badge>
                      )}
                      {item.kind && (
                        <Badge variant="outline" className="text-xs">{item.kind}</Badge>
                      )}
                    </div>
                    {item.summary && (
                      <p className="line-clamp-2 text-sm text-muted-foreground">{item.summary}</p>
                    )}
                    <p className="text-xs text-muted-foreground/70">{item.project_name}</p>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
