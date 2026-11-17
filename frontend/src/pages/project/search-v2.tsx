import { useState, type FormEvent } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ErrorNotification } from '@/components/ui/notification'
import { api, STATUS_LABEL } from '@/lib/api'
import { useCurrentProject } from '@/lib/current-project'

const labels = { requirement: '需求', timeline: '时间轴', wiki: 'Wiki', file: '文件' } as const
type Domain = keyof typeof labels
type Result = { id: string; project_id: string; title: string; href: string; snippet?: string | null; download_href?: string | null }
type Page = { items: Result[]; next_cursor: string | null }
type SearchResult = { domains: Partial<Record<Domain, Page>> }

const allDomains = Object.keys(labels) as Domain[]
const filters = [
  { name: 'requirement_status', label: '需求状态', options: STATUS_LABEL },
  { name: 'timeline_kind', label: '时间轴类型', options: { manual: '人工条目', system: '系统事件' } },
  { name: 'timeline_actor_id', label: '时间轴作者 ID' },
  { name: 'timeline_source_task', label: '来源任务编号' },
  { name: 'wiki_category', label: 'Wiki 分类' },
  { name: 'wiki_tag', label: 'Wiki 标签' },
  { name: 'file_media_type', label: '文件媒体类型' },
  { name: 'file_uploader_id', label: '文件上传者 ID' },
  { name: 'file_used_at', label: '文件使用位置链接' },
  { name: 'from_at', label: '开始时间（含）', type: 'datetime-local' },
  { name: 'to_at', label: '结束时间（不含）', type: 'datetime-local' },
] as const

function searchPath(project: string, scope: string, domain?: Domain, cursor?: string) {
  const params = new URLSearchParams(scope)
  params.set('limit', '20')
  if (domain) params.set('domain', domain)
  if (cursor) params.set('cursor', cursor)
  return `/v2/projects/${encodeURIComponent(project)}/search?${params}`
}

function localDateTime(value: string) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

function Results({ domain, projectId, scope, page, names }: {
  domain: Domain; projectId: string; scope: string; page: Page; names?: Map<string, string>
}) {
  const results = useInfiniteQuery({
    queryKey: ['project-search', projectId, scope, domain],
    initialPageParam: '',
    initialData: { pages: [page], pageParams: [''] },
    staleTime: 15_000,
    queryFn: async ({ pageParam }) => {
      const data = await api.get<SearchResult>(searchPath(projectId, scope, domain, pageParam))
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
        <article key={`${item.project_id}:${item.id}`} className="rounded-md border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <Link to={item.href} className="font-medium underline-offset-4 hover:underline">{item.title}</Link>
              {names && <p className="text-sm text-muted-foreground">{names.get(item.project_id) ?? item.project_id}</p>}
            </div>
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
  const otherProjects = projects.filter((project) => project.id !== projectId)
  const included = [...new Set(params.getAll('include_project'))].filter((id) => id !== projectId).sort()
  const filterValues = filters.flatMap(({ name }) => {
    const value = params.get(name)?.trim()
    return value ? [[name, value] as const] : []
  })
  const active = Boolean(query || filterValues.length)
  const request = new URLSearchParams(query ? { q: query } : {})
  for (const id of included) request.append('include_project', id)
  for (const [name, value] of filterValues) request.set(name, value)
  const scope = request.toString()
  const projectNames = included.length ? new Map(projects.map(({ id, name }) => [id, name])) : undefined
  const [filter, setFilter] = useState<Domain | 'all'>('all')
  const search = useQuery({
    queryKey: ['project-search', projectId, scope],
    queryFn: () => api.get<SearchResult>(searchPath(projectId, scope)),
    enabled: !!projectId && active,
  })
  const domains = filter === 'all' ? allDomains : [filter]
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const submitted = String(data.get('q') ?? '').trim()
    const next = new URLSearchParams(submitted ? { q: submitted } : {})
    for (const id of data.getAll('include_project')) next.append('include_project', String(id))
    for (const field of filters) {
      const value = String(data.get(field.name) ?? '').trim()
      if (value) next.set(field.name, 'type' in field ? new Date(value).toISOString() : value)
    }
    setFilter('all')
    setParams(next)
  }
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold">项目搜索</h1>
        {projectName && <p className="text-sm text-muted-foreground">{projectName}</p>}
      </div>
      <form key={`${projectId}:${scope}`} className="space-y-3" onSubmit={submit}>
        <div className="flex gap-2">
          <Input name="q" type="search" autoComplete="off" aria-label="搜索关键词" defaultValue={query} maxLength={256} />
          <Button type="submit">搜索</Button>
        </div>
        {otherProjects.length > 0 && <fieldset className="space-y-2 rounded-md border px-3 pb-3">
          <legend className="px-1 text-sm font-medium">同时搜索其他项目</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {otherProjects.map((project) => (
              <label key={project.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" autoComplete="off" name="include_project" value={project.id}
                  defaultChecked={included.includes(project.id)} />
                {project.name}
              </label>
            ))}
          </div>
        </fieldset>}
        <details open={filterValues.length > 0} className="rounded-md border p-3">
          <summary className="cursor-pointer text-sm font-medium">高级筛选</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {filters.map((field) => {
              const value = params.get(field.name) ?? ''
              return <label key={field.name} className="grid gap-1 text-sm">
                {field.label}
                {'options' in field
                  ? <select name={field.name} autoComplete="off" defaultValue={value}
                    className="h-9 rounded-md border bg-background px-3 text-sm">
                    <option value="">不限</option>
                    {Object.entries(field.options).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                  </select>
                  : <Input name={field.name} autoComplete="off" maxLength={256}
                    type={'type' in field ? field.type : 'text'} defaultValue={'type' in field ? localDateTime(value) : value} />}
              </label>
            })}
          </div>
        </details>
      </form>
      {active && <div className="flex flex-wrap gap-2" aria-label="搜索结果类型">
        <Button variant={filter === 'all' ? 'default' : 'outline'} size="sm" aria-pressed={filter === 'all'}
          onClick={() => setFilter('all')}>全部</Button>
        {allDomains.filter((domain) => !search.data || search.data.domains[domain]).map((domain) => (
          <Button key={domain} variant={filter === domain ? 'default' : 'outline'} size="sm"
            aria-pressed={filter === domain} onClick={() => setFilter(domain)}>{labels[domain]}</Button>
        ))}
      </div>}
      <ErrorNotification message={search.error?.message} />
      {search.isFetching && <p className="text-sm text-muted-foreground" role="status">搜索中…</p>}
      {search.isError && <Button variant="outline" onClick={() => void search.refetch()}>重试</Button>}
      {domains.map((domain) => {
        const page = search.data?.domains[domain]
        return page ? <Results key={`${projectId}:${scope}:${domain}`} domain={domain}
          projectId={projectId} scope={scope} page={page} names={projectNames} /> : null
      })}
    </div>
  )
}
