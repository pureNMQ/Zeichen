import { useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { api, ApiError, type ProjectMemberCandidate, type ProjectMemberRow, type ProjectRole, type ProjectRow } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { MemberAccountLabel } from '@/components/user-avatar'
import { RelatedFiles } from '@/components/attachment-list'
import { identityName } from '@/lib/user-identity'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

function AddMemberDialog({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const candidates = useQuery({
    queryKey: ['project-candidates', projectId],
    queryFn: () => api.get<ProjectMemberCandidate[]>(`/projects/${projectId}/member_candidates`),
    gcTime: 0,
  })
  const [userId, setUserId] = useState<string>('')
  const [role, setRole] = useState<ProjectRole>('viewer')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const selected = candidates.isSuccess ? candidates.data.find((person) => person.id === userId) : undefined

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!selected || submitting) return
    setError(null)
    setSubmitting(true)
    try {
      await api.post(`/projects/${projectId}/members`, { user_id: userId, role })
      onClose()
      await qc.invalidateQueries({ queryKey: ['project-members', projectId] })
      await qc.invalidateQueries({ queryKey: ['project-candidates', projectId] })
      await qc.invalidateQueries({ queryKey: ['projects'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '添加失败,请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open onOpenChange={(next) => { if (!next) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>添加项目成员</DialogTitle>
          <DialogDescription>选择要加入此项目的人类成员。附属 Agent 自动继承主人的项目权限。</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="project-member-candidate">工作区成员</Label>
            {candidates.isPending ? (
              <p role="status" className="text-sm text-muted-foreground">正在加载可添加的成员…</p>
            ) : candidates.isError ? (
              <div className="space-y-2">
                <p role="alert" className="text-sm text-destructive">候选成员加载失败</p>
                <Button type="button" variant="outline" size="sm" disabled={candidates.isFetching}
                  onClick={() => void candidates.refetch()}>重新加载成员</Button>
              </div>
            ) : candidates.data.length === 0 ? (
              <p role="status" className="text-sm text-muted-foreground">没有可添加的人类成员。</p>
            ) : (
              <Select value={userId || undefined} onValueChange={setUserId}>
                <SelectTrigger id="project-member-candidate" className="w-full">
                  <SelectValue placeholder="选择账号" />
                </SelectTrigger>
                <SelectContent>
                  {candidates.data.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {identityName(c)}
                      {c.workspace_role === 'admin' && '（工作区管理员）'}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="project-member-role">项目角色</Label>
            <Select value={role} disabled={!selected} onValueChange={(v) => setRole(v as ProjectRole)}>
              <SelectTrigger id="project-member-role" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="editor">editor</SelectItem>
                <SelectItem value="viewer">viewer</SelectItem>
              </SelectContent>
            </Select>
            {selected?.workspace_role === 'admin' && (
              <p className="text-sm text-muted-foreground">此角色登记在成员名册中。工作区管理员始终拥有项目管理权限。</p>
            )}
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting || !selected}>
              {submitting ? '添加中…' : '添加'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function MemberRoleSelect({ projectId, member }: { projectId: string; member: ProjectMemberRow }) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function changeRole(role: ProjectRole) {
    if (saving || role === member.role) return
    setError(null)
    setSaving(true)
    try {
      await api.patch(`/projects/${projectId}/members/${member.id}`, { role })
      await qc.invalidateQueries({ queryKey: ['project-members', projectId] })
      await qc.invalidateQueries({ queryKey: ['projects'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '修改失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Select value={member.role} onValueChange={changeRole} disabled={saving}>
        <SelectTrigger aria-label={`${identityName(member)} 的项目角色`} className="w-24">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="editor">editor</SelectItem>
          <SelectItem value="viewer">viewer</SelectItem>
        </SelectContent>
      </Select>
      <ErrorNotification message={error} />
    </div>
  )
}

function TransferOwnerDialog({
  projectId,
  owner,
  members,
  open,
  onOpenChange,
}: {
  projectId: string
  owner: ProjectMemberRow
  members: ProjectMemberRow[]
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const qc = useQueryClient()
  const [userId, setUserId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const targets = members.filter((member) => member.id !== owner.id && member.role !== 'owner')

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!userId || !password) return
    setError(null)
    setSubmitting(true)
    try {
      await api.post(`/projects/${projectId}/owner-transfer`, { user_id: userId, password })
      setUserId('')
      setPassword('')
      onOpenChange(false)
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['project-members', projectId] }),
        qc.invalidateQueries({ queryKey: ['project', projectId] }),
        qc.invalidateQueries({ queryKey: ['projects'] }),
      ])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Owner 转让失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v)
        if (!v) {
          setError(null)
          setPassword('')
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>转让 Owner</DialogTitle>
          <DialogDescription>
            请选择已加入项目的成员，并用当前密码确认。转让后，你在名册中的项目角色将变为 editor。
            {owner.workspace_role === 'admin' && '你仍可凭工作区管理员身份管理项目。'}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="owner-transfer-target">新 Owner</Label>
            {targets.length === 0 ? (
              <p className="text-sm text-muted-foreground">请先添加另一名项目成员。</p>
            ) : (
              <Select value={userId || undefined} onValueChange={setUserId}>
                <SelectTrigger id="owner-transfer-target" className="w-full">
                  <SelectValue placeholder="选择项目成员" />
                </SelectTrigger>
                <SelectContent>
                  {targets.map((target) => (
                    <SelectItem key={target.id} value={target.id}>
                      {identityName(target)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="owner-transfer-password">当前密码</Label>
            <Input
              id="owner-transfer-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" variant="destructive" disabled={submitting || !userId || !password}>
              {submitting ? '转让中…' : '确认转让 Owner'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function EditProjectDialog({ project, onClose }: { project: ProjectRow; onClose: () => void }) {
  const qc = useQueryClient()
  const [value, setValue] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const patch: { name?: string; description?: string } = {}
      if (value.trim() !== project.name) patch.name = value.trim()
      if (description.trim() !== (project.description ?? '')) patch.description = description.trim()
      await api.patch(`/projects/${project.id}`, patch)
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['project', project.id] }),
        qc.invalidateQueries({ queryKey: ['projects'] }),
      ])
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '项目信息保存失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open onOpenChange={(v) => { if (!v && !submitting) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>编辑项目信息</DialogTitle>
          <DialogDescription>名称和描述会显示在项目卡片上。</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="project-name">项目名</Label>
            <Input
              id="project-name"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoComplete="off"
              maxLength={128}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="project-description">项目描述</Label>
            <Textarea id="project-description" autoComplete="off" maxLength={1000} rows={4}
              value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={submitting} onClick={onClose}>取消</Button>
            <Button type="submit" disabled={submitting || !value.trim() || (value.trim() === project.name && description.trim() === (project.description ?? ''))}>
              {submitting ? '保存中…' : '保存'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function ProjectLayout() {
  const { projectId = '' } = useParams()
  const { user } = useAuth()
  const qc = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [transferOwner, setTransferOwner] = useState<ProjectMemberRow | null>(null)
  const [removeError, setRemoveError] = useState<string | null>(null)

  const { data: project, isLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get<ProjectRow>(`/projects/${projectId}`),
  })

  const canManageProject = project?.my_role === 'owner'

  const { data: members = [], isLoading: membersLoading, error: membersError } = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => api.get<ProjectMemberRow[]>(`/projects/${projectId}/members`),
    enabled: Boolean(project),
  })

  async function remove(member: ProjectMemberRow) {
    const impact = member.workspace_role === 'admin' ? '该成员仍可凭工作区管理员身份管理项目。' : '其项目授权将被解除。'
    if (!window.confirm(`将 ${identityName(member)} 移出项目名册？${impact}`)) return
    setRemoveError(null)
    try {
      await api.delete(`/projects/${projectId}/members/${member.id}`)
      await qc.invalidateQueries({ queryKey: ['project-members', projectId] })
      await qc.invalidateQueries({ queryKey: ['project-candidates', projectId] })
      await qc.invalidateQueries({ queryKey: ['projects'] })
    } catch (err) {
      setRemoveError(err instanceof ApiError ? err.message : '移除失败')
    }
  }

  if (isLoading) return <p className="text-sm text-muted-foreground">加载中…</p>
  if (!project) return <ErrorNotification message="项目不存在或无访问权限" />

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <div className="flex items-center gap-1">
          <h1 className="min-w-0 text-xl font-semibold [overflow-wrap:anywhere]">{project.name}</h1>
          {canManageProject && (
            <Button variant="ghost" size="icon" className="shrink-0" title="编辑项目信息" aria-label="编辑项目信息" onClick={() => setEditOpen(true)}>
              <Pencil className="h-4 w-4" />
            </Button>
          )}
        </div>
        {project.description && <p className="max-w-prose whitespace-pre-wrap text-sm leading-relaxed [overflow-wrap:anywhere]">{project.description}</p>}
        <p className="text-sm text-muted-foreground">创建于 {new Date(project.created_at).toLocaleDateString()}</p>
      </header>

      <Card>
          <CardHeader>
            <CardTitle className="text-base">项目成员</CardTitle>
            {!membersLoading && !membersError && <CardDescription>名册中共 {members.length} 人</CardDescription>}
          </CardHeader>
          <CardContent className="space-y-3">
            <ErrorNotification message={membersError ? (membersError as Error).message : null} />
            <ErrorNotification message={removeError} />
            {user?.workspace_role === 'admin' && !membersLoading && !membersError && !members.some((m) => m.is_current_user) && (
              <p className="text-sm text-muted-foreground">你以工作区管理员身份管理此项目。如需加入名册，可在“添加成员”中选择自己。</p>
            )}
            {membersLoading ? (
              <p className="text-sm text-muted-foreground">加载中…</p>
            ) : membersError ? null : members.length === 0 ? (
              <p className="text-sm text-muted-foreground">暂无成员</p>
            ) : (
              <ul aria-label="项目成员" className="divide-y">
                {members.map((m) => (
                  <li key={m.id} className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 py-2.5">
                    <div className="min-w-0 grow basis-full text-sm font-medium sm:basis-36">
                      <MemberAccountLabel user={m} isAgent={m.is_agent} />
                      {m.workspace_role === 'admin' && m.role !== 'owner' && (
                        <p className="mt-1 text-xs font-normal text-muted-foreground">工作区管理员 · 拥有项目管理权限</p>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {canManageProject && m.role === 'owner' ? (
                          <Select value="owner" disabled>
                            <SelectTrigger aria-label={`${identityName(m)} 的项目角色`} className="w-24">
                              <SelectValue>owner</SelectValue>
                            </SelectTrigger>
                          </Select>
                        ) : canManageProject ? <MemberRoleSelect projectId={projectId} member={m} /> : <Badge variant="outline">{m.role}</Badge>}
                        {canManageProject && (m.role === 'owner' ? (
                          m.is_current_user && (
                            <Button variant="outline" size="sm" onClick={() => setTransferOwner(m)}>
                              转让 Owner
                            </Button>
                          )
                        ) : (
                          <Button variant="ghost" size="sm" onClick={() => void remove(m)}>
                            <Trash2 className="h-4 w-4" />
                            <span aria-hidden="true">移除</span>
                            <span className="sr-only">移除 {m.username}</span>
                          </Button>
                        ))}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {canManageProject && (
              <Button onClick={() => setAddOpen(true)}>
                <Plus className="mr-2 h-4 w-4" />
                添加成员
              </Button>
            )}
          </CardContent>
        </Card>

      <RelatedFiles key={`files:${projectId}`} projectId={projectId} targetKind="project" targetId={projectId}
        canEdit={canManageProject || project.my_role === 'editor'} />
      {canManageProject && editOpen && <EditProjectDialog key={project.id} project={project} onClose={() => setEditOpen(false)} />}
      {canManageProject && addOpen && <AddMemberDialog key={projectId} projectId={projectId} onClose={() => setAddOpen(false)} />}
      {transferOwner && (
        <TransferOwnerDialog
          projectId={projectId}
          owner={transferOwner}
          members={members}
          open={true}
          onOpenChange={(open) => {
            if (!open) setTransferOwner(null)
          }}
        />
      )}
    </div>
  )
}
