import { useMemo, useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Loader2, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ErrorNotification } from '@/components/ui/notification'
import { api, type SearchDomain, type SearchItem } from '@/lib/api'
import { cn } from '@/lib/utils'

const DOMAIN_LABEL: Record<SearchItem['domain'], string> = {
  requirement: '需求',
  task: '任务',
  document: '文档',
  memory: '记忆',
}

const DOMAIN_TABS: { value: 'all' | SearchDomain; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'requirement', label: '需求' },
  { value: 'task', label: '任务' },
  { value: 'document', label: '文档' },
  { value: 'memory', label: '记忆' },
]

const STATUS_LABEL: Record<string, string> = {
  backlog: '待办',
  in_progress: '实现中',
  verifying: '验收中',
  done: '已完成',
  cancelled: '已取消',
}

type DomainFilter = 'all' | SearchDomain

function searchUrl(query: string, domain: DomainFilter, cursor?: string) {
  const params = new URLSearchParams({ q: query })
  if (domain !== 'all') params.set('domain', domain)
  if (cursor) params.set('cursor', cursor)
  return `/search?${params.toString()}`
}

function SearchResultCard({ item }: { item: SearchItem }) {
  return (
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
  )
}

function hrefOf(item: SearchItem): string {
  switch (item.domain) {
    case 'requirement':
      return `/requirements/${item.id}`
    case 'document':
      return `/documents/wiki/${item.id}`
    default:
      return '/projects'
  }
}

// 任务无独立页面(ADR 0003):跳所属需求详情页并定位任务弹窗
async function taskHrefOf(item: SearchItem): Promise<string> {
  try {
    const t = await api.get<{ requirement_id: string | null }>(`/tasks/${item.id}`)
    if (t.requirement_id) return `/requirements/${t.requirement_id}?task=${item.id}`
  } catch {
    // 任务不可见时回退项目页
  }
  return '/projects'
}

export function SearchPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const query = params.get('q') ?? ''
  const [domain, setDomain] = useState<DomainFilter>('all')

  const { data, isLoading, isError, error, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ['search', query, domain],
    queryFn: ({ pageParam }) =>
      api.get<{ items: SearchItem[]; next_cursor: string | null }>(searchUrl(query, domain, pageParam)),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: query.trim().length > 0,
  })

  const items = useMemo(() => data?.pages.flatMap((page) => page.items) ?? [], [data])
  const grouped = useMemo(() => {
    const groups: { domain: SearchItem['domain']; items: SearchItem[] }[] = []
    const order: SearchItem['domain'][] = ['requirement', 'task', 'document', 'memory']
    for (const group of order) {
      const groupItems = items.filter((item) => item.domain === group)
      if (groupItems.length > 0) groups.push({ domain: group, items: groupItems })
    }
    return groups
  }, [items])

  const errorMessage = isError && error instanceof Error ? error.message : null

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold">全局搜索</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {query.trim() ? <>关键词：{query}</> : '输入关键词跨项目搜索'}
        </p>
      </div>
      {query.trim() && (
        <div role="tablist" aria-label="结果域过滤" className="flex gap-1 border-b">
          {DOMAIN_TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              role="tab"
              aria-selected={domain === tab.value}
              onClick={() => setDomain(tab.value)}
              className={cn(
                'border-b-2 px-3 pb-2 pt-1 text-sm font-medium transition-colors',
                domain === tab.value
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}
      <ErrorNotification message={errorMessage} />
      {query.trim() && isLoading && (
        <div className="flex items-center justify-center gap-2 py-12 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" /> 搜索中…
        </div>
      )}
      {query.trim() && !isLoading && items.length === 0 && (
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
            {group.items.map((item) =>
              item.domain === 'task' ? (
                <button
                  key={`${item.domain}:${item.id}`}
                  type="button"
                  onClick={() => void taskHrefOf(item).then(navigate)}
                  className="block w-full text-left"
                >
                  <SearchResultCard item={item} />
                </button>
              ) : (
                <Link key={`${item.domain}:${item.id}`} to={hrefOf(item)} className="block">
                  <SearchResultCard item={item} />
                </Link>
              ),
            )}
          </div>
        </section>
      ))}
      {query.trim() && hasNextPage && (
        <div className="flex justify-center pt-2">
          <Button type="button" variant="outline" disabled={isFetchingNextPage} onClick={() => void fetchNextPage()}>
            {isFetchingNextPage && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
            {isFetchingNextPage ? '加载中…' : '加载更多'}
          </Button>
        </div>
      )}
    </div>
  )
}
