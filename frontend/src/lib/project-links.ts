export type ProjectResource = 'requirements' | 'tasks' | 'wiki' | 'files' | 'people'

export function projectResourceHref(projectId: string, resource: ProjectResource, id?: string) {
  const base = `/projects/${encodeURIComponent(projectId)}/${resource}`
  return id ? `${base}/${encodeURIComponent(id)}` : base
}

export function projectReferenceHref(projectId: string, type: string, id: string) {
  switch (type) {
    case 'requirement': return projectResourceHref(projectId, 'requirements', id)
    case 'task': return projectResourceHref(projectId, 'tasks', id)
    case 'document': return projectResourceHref(projectId, 'wiki', id)
    default: return null
  }
}
