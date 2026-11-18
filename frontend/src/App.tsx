import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AppShell } from '@/components/app-shell'
import { ErrorNotification } from '@/components/ui/notification'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { authReturnPath } from '@/lib/auth-return'
import { DocumentNavigationProvider } from '@/lib/document-navigation'
import { CurrentProjectProvider, useCurrentProject } from '@/lib/current-project'
import { projectResourceHref } from '@/lib/project-links'
import { BootstrapPage } from '@/pages/bootstrap'
import { LoginPage } from '@/pages/login'
import { MembersPage } from '@/pages/members'
import { ProjectsPage } from '@/pages/projects'
import { ProjectLayout } from '@/pages/project/layout'
import { CanonicalPersonRoute, CanonicalProjectRoute, CanonicalTaskRoute } from '@/pages/project/canonical-routes'
import { ProjectFileDetailPage } from '@/pages/project/file-detail'
import { ProjectFilesPage } from '@/pages/project/files'
import { ProjectWikiPage } from '@/pages/project/wiki'
import { WorkEditorPage } from '@/pages/project/work-editor'
import { RequirementsPage } from '@/pages/requirements'
import { RequirementDetailPage } from '@/pages/requirement-detail'
import { SetPasswordPage } from '@/pages/set-password'
import { RepositoriesPage } from '@/pages/repositories'
import { SearchPage } from '@/pages/search'
import { ProjectSearchPage } from '@/pages/project/search-v2'
import { ManualPage } from '@/pages/manual'

function LegacyWikiRedirect({ directory = false }: { directory?: boolean }) {
  const { id } = useParams()
  const code = directory ? undefined : id
  const { search, hash } = useLocation()
  const { projectId, isLoading } = useCurrentProject()
  const params = new URLSearchParams(search)
  const scope = params.get('project_id')
  const lookup = useQuery({
    queryKey: ['legacy-wiki-project', code],
    queryFn: ({ signal }) => api.get<{ project_id: string }>(`/documents/wiki/${encodeURIComponent(code!)}`, signal),
    enabled: Boolean(code && !scope),
    retry: false,
  })
  const targetProject = scope ?? (code ? lookup.data?.project_id : projectId)
  if (targetProject) {
    params.delete('project_id')
    const query = params.toString()
    return <Navigate to={`${projectResourceHref(targetProject, 'wiki', code)}${query ? `?${query}` : ''}${hash}`} replace />
  }
  if (lookup.isLoading || isLoading) return <p role="status" className="text-sm text-muted-foreground">加载 Wiki…</p>
  return <div className="space-y-2">
    <ErrorNotification message={lookup.error?.message} />
    <Link className="text-sm underline" to={projectId ? projectResourceHref(projectId, 'wiki') : '/projects'}>
      {projectId ? '打开当前项目的 Wiki' : '选择项目'}
    </Link>
  </div>
}

function LegacyRequirementRedirect() {
  const { id = '' } = useParams<{ id: string }>()
  const { search, hash } = useLocation()
  const params = new URLSearchParams(search)
  const scope = params.get('project_id')
  const path = `/requirements/${encodeURIComponent(id)}`
  const requirement = useQuery({
    queryKey: ['legacy-requirement-project', scope, id],
    queryFn: () => api.get<{ project_id: string }>(scope ? `${path}?project_id=${encodeURIComponent(scope)}` : path),
    enabled: !!id,
  })
  if (requirement.error) return <ErrorNotification message={requirement.error.message} />
  if (!requirement.data) return <p role="status" className="text-sm text-muted-foreground">加载中…</p>
  params.delete('project_id')
  const query = params.toString()
  const href = projectResourceHref(requirement.data.project_id, 'requirements', id)
  return <Navigate to={`${href}${query ? `?${query}` : ''}${hash}`} replace />
}

function BootstrapGate() {
  const navigate = useNavigate()
  const { loading } = useAuth()
  const { search } = useLocation()
  useEffect(() => {
    if (loading) return
    void (async () => {
      try {
        const { needs_bootstrap } = await api.get<{ needs_bootstrap: boolean }>('/auth/bootstrap')
        if (!needs_bootstrap) navigate(`/login${search}`, { replace: true })
      } catch {
        navigate(`/login${search}`, { replace: true })
      }
    })()
  }, [loading, navigate, search])

  if (loading) return null
  return <BootstrapPage />
}

function LoginGate() {
  const { user, loading } = useAuth()
  const [params] = useSearchParams()
  if (loading) return null
  if (user) return <Navigate to={authReturnPath(params.get('from'))} replace />
  return <LoginPage />
}

function RequireAuth() {
  const { user, loading } = useAuth()
  const { pathname, search, hash } = useLocation()
  const [bootstrap, setBootstrap] = useState<boolean | null>(null)

  useEffect(() => {
    if (loading || user !== null) return
    let cancelled = false
    void api
      .get<{ needs_bootstrap: boolean }>('/auth/bootstrap')
      .then((b) => {
        if (!cancelled) setBootstrap(b.needs_bootstrap)
      })
      .catch(() => {
        if (!cancelled) setBootstrap(false)
      })
    return () => {
      cancelled = true
    }
  }, [loading, user])

  if (loading) return null
  if (!user) {
    if (bootstrap === null) return null
    const from = new URLSearchParams({ from: `${pathname}${search}${hash}` })
    return <Navigate to={`${bootstrap ? '/bootstrap' : '/login'}?${from}`} replace />
  }
  return (
    <CurrentProjectProvider>
      <DocumentNavigationProvider>
        <AppShell />
      </DocumentNavigationProvider>
    </CurrentProjectProvider>
  )
}

export function App() {
  return (
    <Routes>
      <Route path="/bootstrap" element={<BootstrapGate />} />
      <Route path="/login" element={<LoginGate />} />
      <Route path="/set-password" element={<SetPasswordPage />} />
      <Route path="/" element={<RequireAuth />}>
        <Route index element={<Navigate to="/projects" replace />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectLayout />} />
        <Route path="projects/:projectId" element={<CanonicalProjectRoute />}>
          <Route path="requirements" element={<RequirementsPage />} />
          <Route path="requirements/new" element={<WorkEditorPage kind="requirements" creating />} />
          <Route path="requirements/:id/edit" element={<WorkEditorPage kind="requirements" />} />
          <Route path="requirements/:id/tasks/new" element={<WorkEditorPage kind="tasks" creating />} />
          <Route path="requirements/:id/tasks/:taskId/edit" element={<WorkEditorPage kind="tasks" />} />
          <Route path="requirements/:id" element={<RequirementDetailPage />} />
          <Route path="tasks/:id" element={<CanonicalTaskRoute />} />
          <Route path="wiki/:id?" element={<ProjectWikiPage />} />
          <Route path="people/:id" element={<CanonicalPersonRoute />} />
          <Route path="files" element={<ProjectFilesPage />} />
          <Route path="files/:id" element={<ProjectFileDetailPage />} />
          <Route path="repositories" element={<RepositoriesPage />} />
          <Route path="search" element={<ProjectSearchPage />} />
        </Route>
        <Route path="requirements" element={<RequirementsPage />} />
        <Route path="requirements/:id" element={<LegacyRequirementRedirect />} />
        <Route path="documents/wiki/:id?" element={<LegacyWikiRedirect />} />
        <Route path="documents/glossary" element={<LegacyWikiRedirect directory />} />
        <Route path="documents/glossary/directory/:id" element={<LegacyWikiRedirect directory />} />
        <Route path="documents/glossary/term/:id" element={<LegacyWikiRedirect />} />
        <Route path="repositories" element={<RepositoriesPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="manual" element={<ManualPage />} />
        <Route path="members" element={<MembersPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
