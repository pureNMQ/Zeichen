import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, KeyRound, Plus, Trash2, UserRound } from 'lucide-react'
import { api, ApiError, type MemberCreateResponse, type MemberRow, type PasswordSetupLinkResponse, type Role } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

function AddMemberDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (v: boolean) => void; onCreated: (setupUrl: string) => void }) {
  const qc = useQueryClient()
  const [username, setUsername] = useState('')
  const [role, setRole] = useState<Role>('member')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const member = await api.post<MemberCreateResponse>('/members', { username: username.trim(), role })
      setUsername('')
      setRole('member')
      onOpenChange(false)
      onCreated(member.password_setup_url)
      await qc.invalidateQueries({ queryKey: ['members'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '添加失败,请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>添加成员</DialogTitle>
          <DialogDescription>成员首次登录时设置密码</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="member-username">登录账号</Label>
            <Input
              id="member-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
              maxLength={64}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label>角色</Label>
            <Select value={role} onValueChange={(v) => setRole(v as Role)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="member">成员</SelectItem>
                <SelectItem value="admin">管理员</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? '添加中…' : '添加'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function PasswordSetupLinkDialog({ setupUrl, onOpenChange }: { setupUrl: string | null; onOpenChange: (open: boolean) => void }) {
  const [copied, setCopied] = useState(false)

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(setupUrl ?? '')
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <Dialog open={setupUrl !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>复制设密链接</DialogTitle>
          <DialogDescription>请安全地发送给该成员。链接 24 小时内有效，只能使用一次；关闭后不会再次显示。</DialogDescription>
        </DialogHeader>
        <div className="flex gap-2">
          <Input value={setupUrl ?? ''} readOnly autoComplete="off" aria-label="设密链接" />
          <Button type="button" variant="outline" onClick={() => void copyLink()}>
            <Copy className="mr-2 h-4 w-4" />
            {copied ? '已复制' : '复制'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function RoleSelect({ member }: { member: MemberRow }) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const lockedReason = member.is_self
    ? '不能修改自己的角色'
    : member.is_bootstrap
      ? '首用户的角色已锁定'
      : null

  async function changeRole(role: Role) {
    setError(null)
    try {
      await api.patch(`/members/${member.id}`, { role })
      await qc.invalidateQueries({ queryKey: ['members'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '修改失败')
    }
  }

  return (
    <div className="space-y-2">
      <Select value={member.role} onValueChange={changeRole} disabled={error !== null || lockedReason !== null}>
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="member">成员</SelectItem>
          <SelectItem value="admin">管理员</SelectItem>
        </SelectContent>
      </Select>
      <ErrorNotification message={error} />
    </div>
  )
}

export function MembersPage() {
  const [addOpen, setAddOpen] = useState(false)
  const [setupUrl, setSetupUrl] = useState<string | null>(null)
  const {
    data: members,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['members'],
    queryFn: () => api.get<MemberRow[]>('/members'),
  })
  const qc = useQueryClient()
  const [removeError, setRemoveError] = useState<string | null>(null)

  async function remove(id: string, username: string) {
    if (!window.confirm(`移除成员 ${username}?其项目权限将一并清除`)) return
    setRemoveError(null)
    try {
      await api.delete(`/members/${id}`)
      await qc.invalidateQueries({ queryKey: ['members'] })
    } catch (err) {
      setRemoveError(err instanceof ApiError ? err.message : '移除失败')
    }
  }

  async function regenerateSetupLink(id: string) {
    setRemoveError(null)
    try {
      const response = await api.post<PasswordSetupLinkResponse>(`/members/${id}/password-setup-link`)
      setSetupUrl(response.password_setup_url)
    } catch (err) {
      setRemoveError(err instanceof ApiError ? err.message : '重新生成设密链接失败')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">成员管理</h1>
          <p className="text-sm text-muted-foreground">工作区成员(人类账号),管理员专属</p>
        </div>
        <Button onClick={() => setAddOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          添加成员
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
      <ErrorNotification message={error ? (error as Error).message : null} />
      <ErrorNotification message={removeError} />
      {!isLoading && members?.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
            <UserRound className="h-8 w-8" />
            <p className="text-sm">暂无成员</p>
          </CardContent>
        </Card>
      )}

      {members && members.length > 0 && (
        <section className="space-y-3" aria-labelledby="members-list-title">
          <div>
            <h2 id="members-list-title" className="text-base font-medium">成员列表</h2>
            <p className="text-sm text-muted-foreground">共 {members.length} 人</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {members.map((m) => {
              const isLocked = m.is_self || m.is_bootstrap
              const lockedMessage = m.is_self ? '不能操作自己的成员资格' : '首用户不能被操作'

              return (
                <Card key={m.id} data-testid="member-card" className="h-52 overflow-hidden">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <UserRound className="h-4 w-4 text-muted-foreground" />
                      {m.username}
                    </CardTitle>
                    <CardDescription>加入于 {new Date(m.created_at).toLocaleDateString()}</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-1.5">
                      <p className="text-xs font-medium text-muted-foreground">角色</p>
                      <RoleSelect member={m} />
                    </div>
                    <div className="flex items-center gap-2 border-t pt-3">
                      {!m.has_password && !isLocked ? (
                        <Button
                          variant="outline"
                          size="sm"
                          className="min-w-0 flex-1"
                          onClick={() => void regenerateSetupLink(m.id)}
                          title="重新生成设密链接"
                        >
                          <KeyRound className="h-4 w-4" />
                          设密链接
                          <span className="sr-only">重新生成 {m.username} 的设密链接</span>
                        </Button>
                      ) : (
                        <div className="flex-1" aria-hidden="true" />
                      )}
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => void remove(m.id, m.username)}
                        disabled={isLocked}
                        title={isLocked ? lockedMessage : `移除 ${m.username}`}
                        aria-label={`移除 ${m.username}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        </section>
      )}

      <AddMemberDialog open={addOpen} onOpenChange={setAddOpen} onCreated={setSetupUrl} />
      <PasswordSetupLinkDialog setupUrl={setupUrl} onOpenChange={(open) => { if (!open) setSetupUrl(null) }} />
    </div>
  )
}
