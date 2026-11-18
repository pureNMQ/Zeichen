import { Link, Navigate, useLocation, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { ErrorNotification } from '@/components/ui/notification'
import { api, type ProjectRow } from '@/lib/api'
import { projectResourceHref } from '@/lib/project-links'

/** Old global bookmarks may predate project-scoped search. */
export function SearchPage() {
  const [params] = useSearchParams()
  const { hash } = useLocation()
  const explicitProject = params.get('project_id')
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<ProjectRow[]>('/projects'),
    enabled: !explicitProject,
  })
  const query = params.get('q') ?? ''
  function searchHref(projectId: string) {
    const next = new URLSearchParams()
    if (query) next.set('q', query)
    const domain = params.get('domain')
    if (domain === 'document') next.set('domain', 'wiki')
    if (domain === 'requirement') next.set('domain', domain)
    const search = next.toString()
    return projectResourceHref(projectId, 'search') + (search ? '?' + search : '') + hash
  }

  if (explicitProject) return <Navigate to={searchHref(explicitProject)} replace />
  if (projects.isLoading) return <p role="status">正在加载项目…</p>
  if (projects.isError) return <div className="space-y-3">
    <ErrorNotification message={projects.error.message} />
    <Button variant="outline" onClick={() => void projects.refetch()}>重新加载项目</Button>
  </div>
  if (projects.data?.length === 1) return <Navigate to={searchHref(projects.data[0].id)} replace />
  return (
    <section className="mx-auto max-w-xl space-y-4">
      <h1 className="text-xl font-semibold">选择要搜索的项目</h1>
      {query && <p className="break-words text-sm text-muted-foreground">搜索「{query}」</p>}
      {projects.data?.length ? (
        <ul className="divide-y rounded-md border">
          {projects.data.map((project) => <li key={project.id}>
            <Link className="block px-4 py-3 font-medium hover:underline" replace to={searchHref(project.id)}>
              {project.name}
            </Link>
          </li>)}
        </ul>
      ) : <p className="text-sm text-muted-foreground">暂无可搜索的项目。</p>}
    </section>
  )
}
