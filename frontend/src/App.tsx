import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { AppShell } from '@/components/app-shell'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { DocumentNavigationProvider } from '@/lib/document-navigation'
import { CurrentProjectProvider } from '@/lib/current-project'
import { BootstrapPage } from '@/pages/bootstrap'
import { LoginPage } from '@/pages/login'
import { MembersPage } from '@/pages/members'
import { ProjectsPage } from '@/pages/projects'
import { ProjectLayout } from '@/pages/project/layout'
import { CanonicalPersonRoute, CanonicalProjectRoute, CanonicalTaskRoute } from '@/pages/project/canonical-routes'
import { ProjectFileDetailPage } from '@/pages/project/file-detail'
import { ProjectWikiPage } from '@/pages/project/wiki'
import { RequirementsPage } from '@/pages/requirements'
import { RequirementDetailPage } from '@/pages/requirement-detail'
import { SetPasswordPage } from '@/pages/set-password'
import { DocumentWorkbenchPage } from '@/pages/documents'
import { RepositoriesPage } from '@/pages/repositories'
import { SearchPage } from '@/pages/search'
import { ManualPage } from '@/pages/manual'

/** REQ-59:旧词条 URL(TERM-n)重定向到 wiki 工作台同短码页面。 */
function WikiTermRedirect() {
  const { id } = useParams<{ id: string }>()
  return <Navigate to={`/documents/wiki/${id ?? ''}`} replace />
}

function BootstrapGate() {
  const navigate = useNavigate()
  const { loading } = useAuth()
  useEffect(() => {
    if (loading) return
    void (async () => {
      try {
        const { needs_bootstrap } = await api.get<{ needs_bootstrap: boolean }>('/auth/bootstrap')
        if (!needs_bootstrap) navigate('/login', { replace: true })
      } catch {
        navigate('/login', { replace: true })
      }
    })()
  }, [loading, navigate])

  if (loading) return null
  return <BootstrapPage />
}

function LoginGate() {
  const { user, loading } = useAuth()
  if (loading) return null
  if (user) return <Navigate to="/projects" replace />
  return <LoginPage />
}

function RequireAuth() {
  const { user, loading } = useAuth()
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
    return <Navigate to={bootstrap ? '/bootstrap' : '/login'} replace />
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
          <Route path="requirements/:id" element={<RequirementDetailPage />} />
          <Route path="tasks/:id" element={<CanonicalTaskRoute />} />
          <Route path="wiki" element={<ProjectWikiPage />} />
          <Route path="wiki/:id" element={<ProjectWikiPage />} />
          <Route path="people/:id" element={<CanonicalPersonRoute />} />
          <Route path="files/:id" element={<ProjectFileDetailPage />} />
        </Route>
        <Route path="requirements" element={<RequirementsPage />} />
        <Route path="requirements/:id" element={<RequirementDetailPage />} />
        <Route path="documents/wiki" element={<DocumentWorkbenchPage module="wiki" readOnly />} />
        <Route path="documents/wiki/:id" element={<DocumentWorkbenchPage module="wiki" readOnly />} />
        {/* REQ-59:glossary 并入 wiki,旧词条 URL 重定向保持不断链 */}
        <Route path="documents/glossary" element={<Navigate to="/documents/wiki" replace />} />
        <Route path="documents/glossary/directory/:id" element={<Navigate to="/documents/wiki" replace />} />
        <Route path="documents/glossary/term/:id" element={<WikiTermRedirect />} />
        <Route path="repositories" element={<RepositoriesPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="manual" element={<ManualPage />} />
        <Route path="members" element={<MembersPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
