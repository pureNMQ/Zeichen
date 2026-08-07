import { useEffect, useState } from 'react'
import { Navigate, Outlet, Route, Routes, useNavigate } from 'react-router-dom'
import { ShieldAlert } from 'lucide-react'
import { AppShell } from '@/components/app-shell'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { DocumentNavigationProvider } from '@/lib/document-navigation'
import { CurrentProjectProvider } from '@/lib/current-project'
import { AgentsPage } from '@/pages/agents'
import { BootstrapPage } from '@/pages/bootstrap'
import { LoginPage } from '@/pages/login'
import { MembersPage } from '@/pages/members'
import { ProjectsPage } from '@/pages/projects'
import { ProjectLayout } from '@/pages/project/layout'
import { RequirementsPage } from '@/pages/requirements'
import { TasksPage } from '@/pages/tasks'
import { RequirementDetailPage } from '@/pages/requirement-detail'
import { SetPasswordPage } from '@/pages/set-password'
import { TaskDetailPage } from '@/pages/task-detail'
import { DocumentWorkbenchPage } from '@/pages/documents'
import { CodeReferencePage } from '@/pages/code-reference'
import { MemoryPage, MemorySessionsPage } from '@/pages/memory'

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

function RequireAdmin() {
  const { user } = useAuth()
  if (user?.workspace_role !== 'admin') {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-muted-foreground">
        <ShieldAlert className="h-10 w-10" />
        <p className="text-sm">该页面仅工作区管理员可访问</p>
      </div>
    )
  }
  return <Outlet />
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
        <Route path="requirements" element={<RequirementsPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="requirements/:id" element={<RequirementDetailPage />} />
        <Route path="tasks/:id" element={<TaskDetailPage />} />
        <Route path="documents/wiki" element={<DocumentWorkbenchPage module="wiki" />} />
        <Route path="documents/wiki/:id" element={<DocumentWorkbenchPage module="wiki" />} />
        <Route path="documents/glossary" element={<DocumentWorkbenchPage module="glossary" />} />
        <Route path="documents/glossary/directory/:id" element={<DocumentWorkbenchPage module="glossary" routeNodeKind="directory" />} />
        <Route path="documents/glossary/term/:id" element={<DocumentWorkbenchPage module="glossary" routeNodeKind="document" />} />
        <Route path="code-reference" element={<CodeReferencePage />} />
        <Route path="code-reference/:id" element={<CodeReferencePage />} />
        <Route path="memory" element={<MemoryPage />} />
        <Route path="memory/sessions" element={<MemorySessionsPage />} />
        <Route path="members" element={<MembersPage />} />
        <Route path="agents" element={<RequireAdmin />}>
          <Route index element={<AgentsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
