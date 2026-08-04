import { useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Pencil, Plus, Trash2 } from 'lucide-react'
import { api, ApiError, type ProjectMemberRow, type ProjectRole } from '@/lib/api'
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
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

function AddMemberDialog({ projectId, open, onOpenChange }: { projectId: string; open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient()
  const { data: candidates = [] } = useQuery({
    queryKey: ['project-candidates', projectId],
    queryFn: () => api.get<ProjectMemberRow[]>(`/projects/${projectId}/member_candidates`),
    enabled: open,
  })
  const [userId, setUserId] = useState<string>('')
  const [role, setRole] = useState<ProjectRole>('viewer')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!userId) return
    setError(null)
    setSubmitting(true)
    try {
      await api.post(`/projects/${projectId}/members`, { user_id: userId, role })
      setUserId('')
      setRole('viewer')
      onOpenChange(false)
      await qc.invalidateQueries({ queryKey: ['project-members', projectId] })
      await qc.invalidateQueries({ queryKey: ['project-candidates', projectId] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '添加失败,请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v)
        if (!v) setError(null)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>添加项目成员</DialogTitle>
          <DialogDescription>可从工作区成员与 Agent 中选择，按项目授权 editor/viewer。Owner 请通过转让流程指定。</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label>人选</Label>
            {candidates.length === 0 ? (
              <p className="text-sm text-muted-foreground">没有可添加的人选(工作区成员与 Agent 均已加入)</p>
            ) : (
              <Select value={userId || undefined} onValueChange={setUserId}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="选择账号" />
                </SelectTrigger>
                <SelectContent>
                  {candidates.map((c) => (
                    <SelectItem key={c.id} value={c.id}>
                      {c.username}
                      {c.is_agent && ' (Agent)'}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          <div className="space-y-1.5">
            <Label>角色</Label>
            <Select value={role} onValueChange={(v) => setRole(v as ProjectRole)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="editor">editor</SelectItem>
                <SelectItem value="viewer">viewer</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting || !userId}>
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

  async function changeRole(role: ProjectRole) {
    setError(null)
    try {
      await api.patch(`/projects/${projectId}/members/${member.id}`, { role })
      await qc.invalidateQueries({ queryKey: ['project-members', projectId] })
      await qc.invalidateQueries({ queryKey: ['projects'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '修改失败')
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Select value={member.role} onValueChange={changeRole} disabled={error !== null}>
        <SelectTrigger className="w-28">
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
            转让后你将变为 editor。只能选择已加入项目的成员，并需要验证你的当前密码。
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
                      {target.username}{target.is_agent && ' (Agent)'}
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

function RenameProjectDialog({
  projectId,
  name,
  open,
  onOpenChange,
}: {
  projectId: string
  name: string
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const qc = useQueryClient()
  const [value, setValue] = useState(name)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.patch(`/projects/${projectId}`, { name: value.trim() })
      onOpenChange(false)
      await qc.invalidateQueries({ queryKey: ['project', projectId] })
      await qc.invalidateQueries({ queryKey: ['projects'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '重命名失败,请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v)
        if (!v) setError(null)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>重命名项目</DialogTitle>
          <DialogDescription>项目名在列表与侧边栏切换器同步更新</DialogDescription>
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
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting || value.trim() === ''}>
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
  const qc = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [renameOpen, setRenameOpen] = useState(false)
  const [transferOwner, setTransferOwner] = useState<ProjectMemberRow | null>(null)
  const [removeError, setRemoveError] = useState<string | null>(null)

  const { data: project, isLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get<{ id: string; name: string; created_at: string; my_role: string }>(`/projects/${projectId}`),
  })

  const isOwner = project?.my_role === 'owner'

  const { data: members = [], isLoading: membersLoading, error: membersError } = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => api.get<ProjectMemberRow[]>(`/projects/${projectId}/members`),
    enabled: Boolean(project),
  })

  async function remove(member: ProjectMemberRow) {
    if (!window.confirm(`将 ${member.username} 移出项目?其项目内授权将清除`)) return
    setRemoveError(null)
    try {
      await api.delete(`/projects/${projectId}/members/${member.id}`)
      await qc.invalidateQueries({ queryKey: ['project-members', projectId] })
      await qc.invalidateQueries({ queryKey: ['projects'] })
    } catch (err) {
      setRemoveError(err instanceof ApiError ? err.message : '移除失败')
    }
  }

  if (isLoading) return <p className="text-sm text-muted-foreground">加载中…</p>
  if (!project) return <ErrorNotification message="项目不存在或无访问权限" />

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">{project.name}</h1>
        {isOwner && (
          <Button variant="ghost" size="sm" onClick={() => setRenameOpen(true)}>
            <Pencil className="h-3.5 w-3.5" />
            <span className="sr-only">重命名</span>
          </Button>
        )}
        <Badge variant="outline">我的角色:{project.my_role}</Badge>
      </div>
      <p className="text-sm text-muted-foreground">创建于 {new Date(project.created_at).toLocaleDateString()}</p>

      <Card>
          <CardHeader>
            <CardTitle className="text-base">项目成员</CardTitle>
            <CardDescription>共 {members.length} 人 · 项目资源按成员角色授权(owner/editor/viewer)，Owner 仅可转让</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <ErrorNotification message={membersError ? (membersError as Error).message : null} />
            <ErrorNotification message={removeError} />
            {membersLoading ? (
              <p className="text-sm text-muted-foreground">加载中…</p>
            ) : members.length === 0 ? (
              <p className="text-sm text-muted-foreground">暂无成员</p>
            ) : (
              <Table>
                <TableHeader>
                    <TableRow>
                      <TableHead>账号</TableHead>
                      <TableHead>角色</TableHead>
                    {isOwner && <TableHead className="text-right">操作</TableHead>}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {members.map((m) => (
                    <TableRow key={m.id}>
                      <TableCell className="font-medium">
                        {m.username}
                        {m.is_agent && (
                          <span className="ml-1 inline-flex align-text-bottom" title="Agent">
                            <Bot className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
                            <span className="sr-only">Agent</span>
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        {isOwner && m.role === 'owner' ? (
                          <Select value="owner" disabled>
                            <SelectTrigger className="w-28">
                              <SelectValue>owner</SelectValue>
                            </SelectTrigger>
                          </Select>
                        ) : isOwner ? <MemberRoleSelect projectId={projectId} member={m} /> : <Badge variant="outline">{m.role}</Badge>}
                      </TableCell>
                      {isOwner && <TableCell className="text-right">
                        {m.role === 'owner' ? (
                          m.is_current_user && (
                            <Button variant="outline" size="sm" onClick={() => setTransferOwner(m)}>
                              转让 Owner
                            </Button>
                          )
                        ) : (
                          <Button variant="ghost" size="sm" onClick={() => void remove(m)}>
                            <Trash2 className="h-4 w-4" />
                            <span className="sr-only">移除 {m.username}</span>
                          </Button>
                        )}
                      </TableCell>}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {isOwner && (
              <Button onClick={() => setAddOpen(true)}>
                <Plus className="mr-2 h-4 w-4" />
                添加成员
              </Button>
            )}
          </CardContent>
        </Card>

      <RenameProjectDialog
        projectId={projectId}
        name={project.name}
        open={renameOpen}
        onOpenChange={setRenameOpen}
      />
      {isOwner && <AddMemberDialog projectId={projectId} open={addOpen} onOpenChange={setAddOpen} />}
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
