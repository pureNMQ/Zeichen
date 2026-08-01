import { useEffect } from 'react'
import { Navigate, Outlet, Route, Routes, useNavigate } from 'react-router-dom'
import { ShieldAlert } from 'lucide-react'
import { AppShell } from '@/components/app-shell'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { AgentsPage } from '@/pages/agents'
import { BootstrapPage } from '@/pages/bootstrap'
import { LoginPage } from '@/pages/login'
import { MembersPage } from '@/pages/members'
import { ProjectsPage } from '@/pages/projects'
import { SetPasswordPage } from '@/pages/set-password'
import { StyleLabPage } from '@/stylelab'

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
  if (loading) return null
  if (!user) return <Navigate to="/login" replace />
  return <AppShell />
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
      <Route path="/style-lab" element={<StyleLabPage />} />
      <Route path="/" element={<RequireAuth />}>
        <Route index element={<Navigate to="/projects" replace />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="members" element={<RequireAdmin />}>
          <Route index element={<MembersPage />} />
        </Route>
        <Route path="agents" element={<RequireAdmin />}>
          <Route index element={<AgentsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
