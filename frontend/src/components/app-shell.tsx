import { useState, type FormEvent } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { LogOut, KeyRound, Settings } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useCurrentProject } from '@/lib/current-project'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const TEAM_NAV = [
  { to: '/projects', label: '项目' },
  { to: '/members', label: '成员' },
  { to: '/agents', label: 'Agent', adminOnly: true },
]

const WORKSPACE_NAV = [
  { to: '/requirements', label: '需求' },
  { to: '/tasks', label: '任务' },
]

function NavGroup({ title, items, isAdmin }: { title: string; items: { to: string; label: string; adminOnly?: boolean }[]; isAdmin: boolean }) {
  return (
    <div className="space-y-1">
      <p className="px-3 pb-1.5 pt-4 text-[11px] font-semibold uppercase tracking-wider text-foreground/50">
        {title}
      </p>
      {items
        .filter((item) => !item.adminOnly || isAdmin)
        .map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `block rounded-md px-3 py-2 text-sm ${
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
    </div>
  )
}

function ProjectSwitcher() {
  const { projects, currentProject, selectProject, isLoading } = useCurrentProject()

  return (
    <div className="border-t p-2">
      <p className="px-1 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-foreground/50">当前项目</p>
      {isLoading ? (
        <p className="px-1 text-sm text-muted-foreground">加载中…</p>
      ) : projects.length === 0 ? (
        <p className="px-1 text-sm text-muted-foreground">暂无可见项目</p>
      ) : (
        <Select value={currentProject?.id} onValueChange={selectProject}>
          <SelectTrigger className="w-full">
            <SelectValue placeholder="选择项目" />
          </SelectTrigger>
          <SelectContent>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  )
}

function ChangePasswordDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { user } = useAuth()
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (newPassword !== confirm) {
      setError('两次输入的新密码不一致')
      return
    }
    setSubmitting(true)
    try {
      await api.post('/auth/change-password', {
        old_password: oldPassword,
        new_password: newPassword,
      })
      setOldPassword('')
      setNewPassword('')
      setConfirm('')
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '修改失败,请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>修改密码</DialogTitle>
          <DialogDescription>账号 {user?.username} · 修改后下次登录使用新密码</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="old-password">原密码</Label>
            <Input
              id="old-password"
              type="password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-password">新密码(至少 8 位)</Label>
            <Input
              id="new-password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="confirm-password">确认新密码</Label>
            <Input
              id="confirm-password"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? '保存中…' : '保存'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [pwdOpen, setPwdOpen] = useState(false)

  const isAdmin = user?.workspace_role === 'admin'

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-52 shrink-0 flex-col border-r bg-muted/30">
        <div className="px-4 py-4 text-base font-semibold">贼船 Zeichen</div>
        <nav className="flex-1 space-y-1 overflow-y-auto px-2">
          <NavGroup title="团队功能" items={TEAM_NAV} isAdmin={isAdmin} />
          <div className="mx-3 my-1 border-t" />
          <NavGroup title="工作区" items={WORKSPACE_NAV} isAdmin={isAdmin} />
        </nav>
        <ProjectSwitcher />
        <div className="border-t p-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="w-full justify-start gap-2 font-normal">
                <Settings className="h-4 w-4" />
                <span className="truncate">{user?.username}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-48">
              <DropdownMenuLabel>
                {user?.username}
                <span className="ml-1 text-xs text-muted-foreground">
                  {isAdmin ? '管理员' : '成员'}
                </span>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setPwdOpen(true)}>
                <KeyRound className="mr-2 h-4 w-4" />
                修改密码
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={async () => {
                  await logout()
                  navigate('/login', { replace: true })
                }}
              >
                <LogOut className="mr-2 h-4 w-4" />
                退出登录
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
      <ChangePasswordDialog open={pwdOpen} onOpenChange={setPwdOpen} />
    </div>
  )
}
