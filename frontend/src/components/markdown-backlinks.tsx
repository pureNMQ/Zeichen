import { useInfiniteQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { ErrorNotification } from '@/components/ui/notification'

type Page = { items: { href: string; id: string; title: string }[]; next_cursor: string | null }

export function MarkdownBacklinks({ projectId, kind, id }: {
  projectId: string; kind: 'requirements' | 'tasks' | 'wiki'; id: string
}) {
  const query = useInfiniteQuery({
    queryKey: ['markdown-backlinks', projectId, kind, id],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ target_kind: kind, target_id: id })
      if (pageParam) params.set('cursor', pageParam)
      return api.get<Page>(`/projects/${projectId}/markdown/backlinks?${params}`, signal)
    },
    getNextPageParam: page => page.next_cursor ?? undefined,
  })
  const rows = query.data?.pages.flatMap(page => page.items) ?? []
  return <>
    {!!rows.length && <section aria-label="引用此页" className="space-y-2">
      <h2 className="text-sm font-medium">引用此页</h2>
      <ul className="space-y-1 text-sm">{rows.map(row => <li key={row.href}>
        <Link className="hover:underline" to={row.href}><span className="mr-2 text-muted-foreground">{row.id}</span>{row.title}</Link>
      </li>)}</ul>
      {query.hasNextPage && <Button size="sm" variant="ghost" disabled={query.isFetchingNextPage}
        onClick={() => void query.fetchNextPage()}>显示更多引用</Button>}
    </section>}
    <ErrorNotification message={query.error?.message} />
  </>
}
