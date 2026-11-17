import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Copy, KeyRound, Plus, ShieldAlert, Trash2, UserRound } from 'lucide-react'
import { api, ApiError, type MemberCreateResponse, type MemberRow, type MyAgentDetail, type PasswordSetupLinkResponse, type Role } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import { UserAvatar, UserIdentityLabel } from '@/components/user-avatar'
import { UserProfileDialog } from '@/components/user-profile-dialog'
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

function CreateAgentDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient()
  const [username, setUsername] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const inactive = useQuery({
    queryKey: ['my-agent', 'inactive'],
    queryFn: () => api.get<Pick<MyAgentDetail, 'id' | 'display_name' | 'username'>[]>('/my-agent/inactive'),
    enabled: open,
  })

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    await saveAgent(() => api.post('/my-agent', { username: username.trim() }))
  }

  async function saveAgent(action: () => Promise<unknown>) {
    setError(null)
    setSubmitting(true)
    try {
      await action()
      setUsername('')
      onOpenChange(false)
      await qc.invalidateQueries({ queryKey: ['members'] })
      await qc.invalidateQueries({ queryKey: ['my-agent'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>创建或重新启用 Agent</DialogTitle>
          <DialogDescription>每个成员只能创建一个附属 Agent;其权限与你完全一致,随你的角色即时生效。</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="agent-username">Agent 账号</Label>
            <Input
              id="agent-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
              maxLength={64}
              required
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? '创建中…' : '创建'}
            </Button>
          </DialogFooter>
        </form>
        {inactive.data && inactive.data.length > 0 && (
          <div className="space-y-2 border-t pt-3">
            <p className="text-sm font-medium">已停用的 Agent</p>
            <p className="text-xs text-muted-foreground">重新启用后需要签发新 key。</p>
            {inactive.data.map((agent) => (
              <div key={agent.id} className="flex items-center justify-between gap-2">
                <span className="truncate text-sm">{agent.display_name} · @{agent.username}</span>
                <Button type="button" size="sm" variant="outline" disabled={submitting}
                  onClick={() => void saveAgent(() => api.post(`/my-agent/inactive/${agent.id}/reactivate`))}>
                  重新启用
                </Button>
              </div>
            ))}
          </div>
        )}
        {inactive.isError && (
          <Button type="button" variant="outline" onClick={() => void inactive.refetch()}>
            已停用的 Agent 加载失败，重试
          </Button>
        )}
      </DialogContent>
    </Dialog>
  )
}

function TokenOnceBlock({ token, label }: { token: string; label: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(token)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-destructive">请立即复制,关闭后将不再显示:</p>
      <div className="flex gap-2">
        <Input value={token} readOnly autoComplete="off" aria-label={label} className="font-mono text-xs" />
        <Button type="button" variant="outline" onClick={() => void copy()}>
          <Copy className="mr-2 h-4 w-4" />
          {copied ? '已复制' : '复制'}
        </Button>
      </div>
    </div>
  )
}

function IssuedKeyDialog({ token, onClose }: { token: string; onClose: () => void }) {
  return (
    <Dialog open onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>API key 已签发</DialogTitle>
          <DialogDescription>明文 key 仅展示一次,请立即复制并妥善保存。</DialogDescription>
        </DialogHeader>
        <TokenOnceBlock token={token} label="新签发的 API key 明文" />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ManageAgentDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const [issuedToken, setIssuedToken] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [profileOpen, setProfileOpen] = useState(false)
  const [deleteConfirmFor, setDeleteConfirmFor] = useState<MyAgentDetail | null>(null)
  const { data: agent } = useQuery({
    queryKey: ['my-agent'],
    queryFn: () => api.get<{ agent: MyAgentDetail | null }>('/my-agent'),
    enabled: open,
  })

  async function run(action: () => Promise<void>) {
    setError(null)
    try {
      await action()
      await qc.invalidateQueries({ queryKey: ['my-agent'] })
      await qc.invalidateQueries({ queryKey: ['members'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败,请重试')
    }
  }

  async function deleteAgent() {
    setError(null)
    try {
      await api.delete('/my-agent')
      setDeleteConfirmFor(null)
      onOpenChange(false)
      await qc.invalidateQueries({ queryKey: ['my-agent'] })
      await qc.invalidateQueries({ queryKey: ['members'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '停用失败，请重试')
    }
  }

  const detail = agent?.agent ?? null

  return (
    <>
      <Dialog open={open} onOpenChange={(v) => { if (!v) { setIssuedToken(null); setError(null) } onOpenChange(v) }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>管理我的 Agent</DialogTitle>
            <DialogDescription>请在签发时保存明文 key，遗失后需要签发新 key。</DialogDescription>
          </DialogHeader>
          {detail && (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2 text-sm">
                  <UserAvatar user={detail} className="h-9 w-9" />
                  <div className="min-w-0">
                    <p className="truncate font-medium">{detail.display_name}</p>
                    <p className="text-xs text-muted-foreground">@{detail.username}</p>
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={() => setProfileOpen(true)}>
                  编辑资料
                </Button>
              </div>
            <div className="space-y-1.5">
              <Label htmlFor="agent-key-note">签发新 key(备注可选)</Label>
              <div className="flex gap-2">
                <Input id="agent-key-note" value={note} onChange={(e) => setNote(e.target.value)} autoComplete="off" maxLength={500} />
                <Button
                  type="button"
                  onClick={() =>
                    void run(async () => {
                      const created = await api.post<{ token: string }>('/my-agent/keys', { note: note.trim() || null })
                      setIssuedToken(created.token)
                      setNote('')
                    })
                  }
                >
                  签发
                </Button>
              </div>
            </div>
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">API key 列表({detail.active_keys} 个活跃)</p>
              {detail.keys.length === 0 && <p className="text-sm text-muted-foreground">尚未签发</p>}
              {detail.keys.map((k) => (
                <div key={k.id} className="flex items-center justify-between gap-2 rounded-md border p-2 text-sm">
                  <div className="min-w-0">
                    <p className="truncate">{k.note || '无备注'}</p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(k.created_at).toLocaleDateString()} · 活跃
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive"
                      onClick={() => void run(() => api.delete(`/my-agent/keys/${k.id}`))}
                    >
                      吊销
                    </Button>
                  </div>
                </div>
              ))}
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <div className="space-y-1.5 border-t pt-3">
              <p className="text-xs font-medium text-muted-foreground">停用附属 Agent</p>
              <p className="text-xs text-muted-foreground">
                停用后该 Agent 立即失去 MCP 访问，所有 API key 一并吊销，历史署名保留。
              </p>
              <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setDeleteConfirmFor(detail)}>
                <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                停用 Agent
              </Button>
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    {issuedToken && (
      <IssuedKeyDialog token={issuedToken} onClose={() => setIssuedToken(null)} />
    )}
    {detail && profileOpen && (
      <UserProfileDialog
        user={detail}
        open
        onOpenChange={(v) => { if (!v) setProfileOpen(false) }}
        onSaved={() => qc.invalidateQueries({ queryKey: ['my-agent'] })}
      />
    )}
    <Dialog open={deleteConfirmFor !== null} onOpenChange={(v) => { if (!v) setDeleteConfirmFor(null) }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>停用附属 Agent</DialogTitle>
          <DialogDescription>
            确认停用 {deleteConfirmFor ? `@${deleteConfirmFor.username}` : ''}？重新启用后需要签发新 key。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setDeleteConfirmFor(null)}>取消</Button>
          <Button variant="destructive" onClick={() => void deleteAgent()}>
            确认停用
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    </>
  )
}

function MemberAgentSection({ member }: { member: MemberRow }) {
  const isAdmin = member.role === 'admin'
  return (
    <div className="space-y-1.5 border-t pt-3">
      <p className="text-xs font-medium text-muted-foreground">附属 Agent</p>
      {member.agent ? (
        <div className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1.5 text-sm">
            <Bot className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="truncate">{member.agent.display_name}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{member.agent.active_keys} key</span>
          </span>
          {isAdmin && <EmergencyRevokeButton memberId={member.id} agentName={member.agent.display_name} />}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">未创建</p>
      )}
    </div>
  )
}

function EmergencyRevokeButton({ memberId, agentName }: { memberId: string; agentName: string }) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  async function revoke() {
    if (!window.confirm(`紧急吊销 ${agentName} 的全部 API key?该 Agent 将立即失去 MCP 访问。`)) return
    setError(null)
    try {
      await api.post(`/members/${memberId}/agent/revoke-keys`)
      await qc.invalidateQueries({ queryKey: ['members'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '吊销失败')
    }
  }

  return (
    <div className="flex items-center gap-1">
      <ErrorNotification message={error} />
      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-destructive" onClick={() => void revoke()}>
        <ShieldAlert className="h-3.5 w-3.5" />
        紧急吊销
      </Button>
    </div>
  )
}

export function MembersPage() {
  const { user } = useAuth()
  const isAdmin = user?.workspace_role === 'admin'
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
  const [profileFor, setProfileFor] = useState<MemberRow | null>(null)
  const [agentCreateOpen, setAgentCreateOpen] = useState(false)
  const [agentManageOpen, setAgentManageOpen] = useState(false)
  const [showInactive, setShowInactive] = useState(false)
  const [reactivating, setReactivating] = useState<string | null>(null)
  const inactive = useQuery({
    queryKey: ['members', 'inactive'],
    queryFn: () => api.get<Pick<MemberRow, 'id' | 'username' | 'display_name'>[]>('/members/inactive'),
    enabled: isAdmin && showInactive,
  })

  async function remove(id: string, username: string) {
    if (!window.confirm(`停用成员 ${username}？其项目权限会清除，附属 Agent 及其 Key 将停用。`)) return
    setRemoveError(null)
    try {
      await api.delete(`/members/${id}`)
      await qc.invalidateQueries({ queryKey: ['members'] })
    } catch (err) {
      setRemoveError(err instanceof ApiError ? err.message : '停用失败')
    }
  }

  async function reactivate(id: string) {
    setRemoveError(null)
    setReactivating(id)
    try {
      const member = await api.post<{ password_setup_url: string | null }>(`/members/inactive/${id}/reactivate`)
      setSetupUrl(member.password_setup_url)
      await qc.invalidateQueries({ queryKey: ['members'] })
    } catch (err) {
      setRemoveError(err instanceof ApiError ? err.message : '重新启用失败')
    } finally {
      setReactivating(null)
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
          <p className="text-sm text-muted-foreground">
            工作区成员(人类账号){isAdmin ? ', 管理员可管理成员' : ', 仅可查看'}
          </p>
        </div>
        {isAdmin && (
          <Button onClick={() => setAddOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            添加成员
          </Button>
        )}
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
      <ErrorNotification message={error ? (error as Error).message : null} />
      <ErrorNotification message={removeError} />
      <ErrorNotification message={inactive.error?.message} />
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
                <Card key={m.id} data-testid="member-card" className="overflow-hidden">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <UserIdentityLabel user={m} showUsername />
                    </CardTitle>
                    <CardDescription>加入于 {new Date(m.created_at).toLocaleDateString()}</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-1.5">
                      <p className="text-xs font-medium text-muted-foreground">角色</p>
                      {isAdmin ? <RoleSelect member={m} /> : <p className="text-sm">{m.role === 'admin' ? '管理员' : '成员'}</p>}
                    </div>
                    <MemberAgentSection member={m} />
                    {m.is_self && (
                      <div className="flex items-center gap-2">
                        {!m.agent ? (
                          <Button variant="outline" size="sm" onClick={() => setAgentCreateOpen(true)}>
                            <Bot className="mr-1.5 h-4 w-4" />
                            创建或重新启用 Agent
                          </Button>
                        ) : (
                          <Button variant="outline" size="sm" onClick={() => setAgentManageOpen(true)}>
                            <KeyRound className="mr-1.5 h-4 w-4" />
                            管理 Agent 与 key
                          </Button>
                        )}
                      </div>
                    )}
                    {isAdmin && (
                      <div className="flex items-center gap-2 border-t pt-3">
                        <Button variant="outline" size="sm" onClick={() => setProfileFor(m)}>
                          编辑资料
                        </Button>
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
                          title={isLocked ? lockedMessage : `停用 ${m.username}`}
                          aria-label={`停用 ${m.username}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    )}
                  </CardContent>
                </Card>
              )
            })}
          </div>
        </section>
      )}

      {isAdmin && (
        <>
          <Button variant="outline" aria-expanded={showInactive} onClick={() => setShowInactive(!showInactive)}>
            {showInactive ? '收起已停用成员' : '查看已停用成员'}
          </Button>
          {showInactive && (
            <section className="space-y-2" aria-label="已停用成员">
              <p className="text-sm text-muted-foreground">以普通成员身份重新启用，项目权限需要重新授予。</p>
              {inactive.isLoading && <p role="status">加载中…</p>}
              {inactive.isError && <Button variant="outline" onClick={() => void inactive.refetch()}>重试</Button>}
              {inactive.data?.length === 0 && <p className="text-sm text-muted-foreground">暂无已停用成员。</p>}
              {inactive.data?.map((member) => (
                <div key={member.id} className="flex items-center justify-between rounded-md border p-3">
                  <span className="text-sm">{member.display_name ?? member.username}</span>
                  <Button size="sm" variant="outline" disabled={reactivating !== null}
                    onClick={() => void reactivate(member.id)}>重新启用</Button>
                </div>
              ))}
            </section>
          )}
          <AddMemberDialog open={addOpen} onOpenChange={setAddOpen} onCreated={setSetupUrl} />
          <PasswordSetupLinkDialog setupUrl={setupUrl} onOpenChange={(open) => { if (!open) setSetupUrl(null) }} />
        </>
      )}
      <CreateAgentDialog open={agentCreateOpen} onOpenChange={setAgentCreateOpen} />
      <ManageAgentDialog open={agentManageOpen} onOpenChange={setAgentManageOpen} />
      {profileFor && (
        <UserProfileDialog
          user={profileFor}
          open
          onOpenChange={(open) => { if (!open) setProfileFor(null) }}
          onSaved={() => qc.invalidateQueries({ queryKey: ['members'] })}
        />
      )}
    </div>
  )
}
