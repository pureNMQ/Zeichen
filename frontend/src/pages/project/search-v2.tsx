import { useState, type FormEvent } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ErrorNotification } from '@/components/ui/notification'
import { api } from '@/lib/api'
import { useCurrentProject } from '@/lib/current-project'

const labels = { requirement: '需求', timeline: '时间轴', wiki: 'Wiki', file: '文件' } as const
type Domain = keyof typeof labels
type Result = { id: string; title: string; href: string; snippet?: string | null; download_href?: string | null }
type Page = { items: Result[]; next_cursor: string | null }
type SearchResult = { domains: Partial<Record<Domain, Page>> }

const allDomains = Object.keys(labels) as Domain[]

function searchPath(project: string, query: string, domain?: Domain, cursor?: string) {
  const params = new URLSearchParams({ q: query, limit: '20' })
  if (domain) params.set('domain', domain)
  if (cursor) params.set('cursor', cursor)
  return `/v2/projects/${encodeURIComponent(project)}/search?${params}`
}

function Results({ domain, projectId, query, page }: { domain: Domain; projectId: string; query: string; page: Page }) {
  const results = useInfiniteQuery({
    queryKey: ['project-search', projectId, query, domain],
    initialPageParam: '',
    initialData: { pages: [page], pageParams: [''] },
    staleTime: 15_000,
    queryFn: async ({ pageParam }) => {
      const data = await api.get<SearchResult>(searchPath(projectId, query, domain, pageParam))
      return data.domains[domain] ?? { items: [], next_cursor: null }
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = results.data.pages.flatMap((p) => p.items)
  return (
    <section className="space-y-2" aria-label={labels[domain]}>
      <h2 className="text-base font-semibold">{labels[domain]}</h2>
      <ErrorNotification message={results.error?.message} />
      {items.length === 0 && <p className="text-sm text-muted-foreground">没有匹配结果。</p>}
      {items.map((item) => (
        <article key={item.id} className="rounded-md border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Link to={item.href} className="font-medium underline-offset-4 hover:underline">{item.title}</Link>
            {item.download_href && <a href={item.download_href} className="text-sm underline">下载</a>}
          </div>
          {item.snippet && <p className="mt-1 text-sm text-muted-foreground">{item.snippet}</p>}
        </article>
      ))}
      {results.hasNextPage && <Button size="sm" variant="outline" disabled={results.isFetchingNextPage}
        onClick={() => void results.fetchNextPage()}>加载更多{labels[domain]}</Button>}
    </section>
  )
}

export function ProjectSearchPage() {
  const { projectId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const query = params.get('q')?.trim() ?? ''
  const { projects } = useCurrentProject()
  const projectName = projects.find((project) => project.id === projectId)?.name
  const [filter, setFilter] = useState<Domain | 'all'>('all')
  const search = useQuery({
    queryKey: ['project-search', projectId, query],
    queryFn: () => api.get<SearchResult>(searchPath(projectId, query)),
    enabled: !!projectId && !!query,
  })
  const domains = filter === 'all' ? allDomains : [filter]
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const submitted = String(new FormData(event.currentTarget).get('q') ?? '').trim()
    setParams(submitted ? { q: submitted } : {})
  }
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold">项目搜索</h1>
        {projectName && <p className="text-sm text-muted-foreground">{projectName}</p>}
      </div>
      <form className="flex gap-2" onSubmit={submit}>
        <Input key={query} name="q" type="search" autoComplete="off" aria-label="搜索关键词"
          defaultValue={query} maxLength={256} />
        <Button type="submit">搜索</Button>
      </form>
      {projects.length > 1 && <div className="flex flex-wrap gap-2 text-sm">
        {projects.filter((project) => project.id !== projectId).map((project) => (
          <Link key={project.id} className="underline" to={`/projects/${encodeURIComponent(project.id)}/search?q=${encodeURIComponent(query)}`}>
            在{project.name}中搜索
          </Link>
        ))}
      </div>}
      {query && <div className="flex flex-wrap gap-2" aria-label="搜索结果类型">
        <Button variant={filter === 'all' ? 'default' : 'outline'} size="sm" aria-pressed={filter === 'all'}
          onClick={() => setFilter('all')}>全部</Button>
        {allDomains.map((domain) => (
          <Button key={domain} variant={filter === domain ? 'default' : 'outline'} size="sm"
            aria-pressed={filter === domain} onClick={() => setFilter(domain)}>{labels[domain]}</Button>
        ))}
      </div>}
      <ErrorNotification message={search.error?.message} />
      {search.isFetching && <p className="text-sm text-muted-foreground" role="status">搜索中…</p>}
      {search.isError && <Button variant="outline" onClick={() => void search.refetch()}>重试</Button>}
      {domains.map((domain) => {
        const page = search.data?.domains[domain]
        return page ? <Results key={`${projectId}:${query}:${domain}`} domain={domain}
          projectId={projectId} query={query} page={page} /> : null
      })}
    </div>
  )
}
