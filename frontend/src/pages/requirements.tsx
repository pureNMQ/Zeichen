import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, LayoutGrid, List, Plus } from 'lucide-react'

import { Kanban } from '@/components/kanban'
import { StatusBadge } from '@/components/status-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
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
import { Textarea } from '@/components/ui/textarea'
import { api, ApiError, REQUIREMENT_STATUSES, type RequirementRow, type RequirementStatus } from '@/lib/api'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'

const FILTERS: (RequirementStatus | 'all')[] = ['all', ...REQUIREMENT_STATUSES]

const STATUS_TEXT: Record<RequirementStatus, string> = {
  backlog: '待办',
  in_progress: '实现中',
  done: '已完成',
  cancelled: '已取消',
}

export async function moveRequirement(id: string, to: RequirementStatus): Promise<void> {
  await api.post(`/requirements/${id}/status`, { status: to })
}

function RequirementCard({ r, onDelete, canDelete }: { r: RequirementRow; onDelete: (r: RequirementRow) => void; canDelete: boolean }) {
  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <Link to={`/requirements/${r.id}`} className="block text-sm font-medium hover:text-primary">
          {r.title}
        </Link>
        <div className="flex items-center gap-2">
          <StatusBadge status={r.status} />
          <Badge variant="outline">{r.task_count} 任务</Badge>
        </div>
        {canDelete && (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs text-muted-foreground"
            onClick={() => onDelete(r)}
          >
            删除
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

function NoProjectGuide() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
        <FolderOpen className="h-8 w-8" />
        <p className="text-sm">暂无当前项目,请在侧边栏选择项目</p>
      </CardContent>
    </Card>
  )
}

export function RequirementsPage() {
  const { projectId, currentProject, isLoading: cpLoading } = useCurrentProject()
  const qc = useQueryClient()
  const role = useProjectRole()
  const canEdit = role === 'editor' || role === 'owner'
  const [view, setView] = useState<'list' | 'board'>('list')
  const [filter, setFilter] = useState<RequirementStatus | 'all'>('all')
  const [createOpen, setCreateOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<RequirementRow | null>(null)
  const [confirmCount, setConfirmCount] = useState('')

  const { data: page, isLoading, error } = useQuery({
    queryKey: ['requirements', projectId],
    queryFn: () =>
      api.get<{ items: RequirementRow[]; next_cursor: string | null }>(
        `/projects/${projectId}/requirements?limit=100`,
      ),
    enabled: !!projectId,
  })

  const items = (page?.items ?? []).filter((r) => filter === 'all' || r.status === filter)

  async function doMove(id: string, to: RequirementStatus) {
    try {
      await moveRequirement(id, to)
      await qc.invalidateQueries({ queryKey: ['requirements', projectId] })
    } catch (err) {
      alert(err instanceof ApiError ? err.message : '状态变更失败')
      await qc.invalidateQueries({ queryKey: ['requirements', projectId] })
    }
  }

  async function doDelete() {
    if (!deleteTarget) return
    try {
      await api.post(`/requirements/${deleteTarget.id}/delete`, {
        confirm_task_count: Number(confirmCount),
      })
      setDeleteTarget(null)
      setConfirmCount('')
      await qc.invalidateQueries({ queryKey: ['requirements', projectId] })
    } catch (err) {
      alert(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  if (cpLoading) return <p className="text-sm text-muted-foreground">加载中…</p>
  if (!currentProject) return <NoProjectGuide />

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">需求</h1>
          <p className="text-sm text-muted-foreground">
            当前项目:{currentProject.name}
            <span className="ml-1 text-xs">({role ?? '—'})</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex overflow-hidden rounded-md border">
            <Button variant={view === 'list' ? 'secondary' : 'ghost'} size="sm" className="rounded-none" onClick={() => setView('list')}>
              <List className="h-4 w-4" />
              列表
            </Button>
            <Button variant={view === 'board' ? 'secondary' : 'ghost'} size="sm" className="rounded-none" onClick={() => setView('board')}>
              <LayoutGrid className="h-4 w-4" />
              看板
            </Button>
          </div>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as RequirementStatus | 'all')}
            className="h-8 rounded-md border bg-transparent px-2 text-sm"
          >
            {FILTERS.map((f) => (
              <option key={f} value={f}>
                {f === 'all' ? '全部状态' : STATUS_TEXT[f]}
              </option>
            ))}
          </select>
          {canEdit && (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              新建需求
            </Button>
          )}
        </div>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
      {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}
      {!isLoading && items.length === 0 && (
        <p className="py-10 text-center text-sm text-muted-foreground">暂无需求</p>
      )}

      {view === 'board' ? (
        <Kanban
          items={items}
          canDrag={canEdit}
          onMove={(id, to) => void doMove(id, to as RequirementStatus)}
          columns={REQUIREMENT_STATUSES}
          renderCard={(r) => <RequirementCard r={r} onDelete={setDeleteTarget} canDelete={canEdit} />}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((r) => (
            <RequirementCard key={r.id} r={r} onDelete={setDeleteTarget} canDelete={canEdit} />
          ))}
        </div>
      )}

      <CreateRequirementDialog open={createOpen} onOpenChange={setCreateOpen} />

      <Dialog open={deleteTarget !== null} onOpenChange={(v) => !v && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除需求</DialogTitle>
            <DialogDescription>
              需求「{deleteTarget?.title}」下还有 {deleteTarget?.task_count ?? 0} 个任务,删除将一并软删。
              请输入任务数确认:
            </DialogDescription>
          </DialogHeader>
          <Input
            type="number"
            value={confirmCount}
            onChange={(e) => setConfirmCount(e.target.value)}
            placeholder={String(deleteTarget?.task_count ?? 0)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button variant="destructive" onClick={() => void doDelete()}>
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function CreateRequirementDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { projectId } = useCurrentProject()
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.post(`/projects/${projectId}/requirements`, { title: title.trim(), description: description.trim() || null })
      setTitle('')
      setDescription('')
      onOpenChange(false)
      await qc.invalidateQueries({ queryKey: ['requirements', projectId] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '创建失败,请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新建需求</DialogTitle>
          <DialogDescription>需求是项目内的可验收变更单元,可用任务承接拆解。</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="req-title">标题</Label>
            <Input id="req-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={256} required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="req-desc">描述</Label>
            <Textarea id="req-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? '创建中…' : '创建'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
