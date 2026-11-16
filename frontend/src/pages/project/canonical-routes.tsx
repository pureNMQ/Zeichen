import { useQuery } from '@tanstack/react-query'
import { Navigate, Outlet, useLocation, useParams } from 'react-router-dom'

import type { CompletionCandidate } from '@/components/markdown-composer'
import { ErrorNotification } from '@/components/ui/notification'
import { api, withProject, type ProjectRow, type TaskRow } from '@/lib/api'
import { ProjectRouteProvider, useCurrentProject } from '@/lib/current-project'
import { projectResourceHref } from '@/lib/project-links'

export function CanonicalProjectRoute() {
  const { projectId = '' } = useParams()
  const { data: project, isLoading, error, isError } = useQuery({
    queryKey: ['route-project', projectId],
    queryFn: () => api.get<ProjectRow>(`/projects/${encodeURIComponent(projectId)}`),
    retry: false,
  })

  if (isLoading) return <p role="status" className="text-sm text-muted-foreground">加载项目…</p>
  if (isError || !project || project.id.toLowerCase() !== projectId.toLowerCase()) {
    return <ErrorNotification message={error instanceof Error ? error.message : '项目不存在或无访问权限'} />
  }
  return <ProjectRouteProvider key={project.id} project={project}><Outlet /></ProjectRouteProvider>
}

export function CanonicalTaskRoute() {
  const { id = '' } = useParams()
  const { hash } = useLocation()
  const { projectId } = useCurrentProject()
  const { data: task, error, isLoading, isError } = useQuery({
    queryKey: ['task', id, projectId],
    queryFn: () => api.get<TaskRow>(withProject(`/tasks/${encodeURIComponent(id)}`, projectId)),
    enabled: !!projectId,
    retry: false,
  })

  if (isLoading) return <p role="status" className="text-sm text-muted-foreground">加载任务…</p>
  if (isError || !projectId || !task?.requirement_id || task.project_id !== projectId || task.id !== id) {
    return <ErrorNotification message={error instanceof Error ? error.message : '任务不存在或无访问权限'} />
  }
  const path = projectResourceHref(projectId, 'requirements', task.requirement_id)
  return <Navigate replace to={`${path}?task=${encodeURIComponent(task.id)}${hash}`} />
}

export function CanonicalPersonRoute() {
  const { id = '' } = useParams()
  const { projectId } = useCurrentProject()
  const path = projectId ? projectResourceHref(projectId, 'people', id) : null
  const { data: person, error, isLoading, isError } = useQuery({
    queryKey: ['project-person', projectId, id],
    queryFn: () => api.get<CompletionCandidate>(path!),
    enabled: !!path,
    retry: false,
  })

  if (isLoading) return <p role="status" className="text-sm text-muted-foreground">加载人员…</p>
  if (isError || !person || person.href !== path) {
    return <ErrorNotification message={error instanceof Error ? error.message : '项目人员不存在或无访问权限'} />
  }
  return (
    <section className="space-y-2">
      <h1 className="text-xl font-semibold">{person.label}</h1>
      <p className="text-sm text-muted-foreground">
        {person.kind === 'agent' ? 'Agent' : '成员'}
        {person.detail && person.detail !== person.label && ` · ${person.detail}`}
      </p>
    </section>
  )
}
