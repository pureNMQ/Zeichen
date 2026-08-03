import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, List, LayoutGrid, Plus, Trash2, UserPlus } from 'lucide-react'

import { Kanban } from '@/components/kanban'
import { StatusSelect } from '@/components/status-select'
import { CreateTaskDialog } from '@/components/create-task-dialog'
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
import { api, ApiError, TASK_STATUSES, type TaskRow, type WorkflowStatus } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'
import { canSetTaskStatus } from '@/lib/task-perms'

export async function moveTask(id: string, to: WorkflowStatus): Promise<void> {
  await api.post(`/tasks/${id}/status`, { status: to })
}

export async function deleteTask(id: string): Promise<void> {
  await api.post(`/tasks/${id}/delete`)
}

function TaskCard({
  t,
  canEdit,
  canDelete,
  canSetStatus,
  onStatus,
  onClaim,
  onDelete,
}: {
  t: TaskRow
  canEdit: boolean
  canDelete: boolean
  canSetStatus: boolean
  onStatus: (t: TaskRow, s: string) => void
  onClaim: (t: TaskRow) => void
  onDelete: (t: TaskRow) => void
}) {
  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <Link to={`/tasks/${t.id}`} className="block text-sm font-medium hover:text-primary">
          {t.title}
        </Link>
        <div className="flex items-center gap-2">
          <StatusSelect
            value={t.status}
            statuses={TASK_STATUSES}
            onSelect={(s) => onStatus(t, s)}
            disabled={!canSetStatus}
          />
          {t.assignee && <Badge variant="outline">{t.assignee}</Badge>}
        </div>
        <div className="flex items-center gap-1">
          {canEdit && !t.assignee_id && t.status !== 'done' && t.status !== 'cancelled' && (
            <Button
              variant="outline"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={(e) => {
                e.preventDefault()
                onClaim(t)
              }}
            >
              <UserPlus className="mr-1 h-3 w-3" />
              认领
            </Button>
          )}
          {canDelete && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs text-muted-foreground hover:text-destructive"
              onClick={(e) => {
                e.preventDefault()
                onDelete(t)
              }}
            >
              <Trash2 className="mr-1 h-3 w-3" />
              删除
            </Button>
          )}
        </div>
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

export function TasksPage() {
  const { projectId, currentProject, isLoading: cpLoading } = useCurrentProject()
  const { user } = useAuth()
  const qc = useQueryClient()
  const role = useProjectRole()
  const canEdit = role === 'editor' || role === 'owner'
  const [view, setView] = useState<'board' | 'list'>('board')
  const [createOpen, setCreateOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<TaskRow | null>(null)

  const { data: page, isLoading, error } = useQuery({
    queryKey: ['tasks', projectId],
    queryFn: () => api.get<{ items: TaskRow[]; next_cursor: string | null }>(`/projects/${projectId}/tasks?limit=100`),
    enabled: !!projectId,
  })

  const tasks = page?.items ?? []

  async function doMove(id: string, to: WorkflowStatus) {
    try {
      await moveTask(id, to)
      await qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      await qc.invalidateQueries({ queryKey: ['requirements', projectId] })
    } catch (err) {
      alert(err instanceof ApiError ? err.message : '状态变更失败')
      await qc.invalidateQueries({ queryKey: ['tasks', projectId] })
    }
  }

  function onCardStatus(t: TaskRow, s: string) {
    if (s === t.status) return
    void doMove(t.id, s as WorkflowStatus)
  }

  async function claim(task: TaskRow) {
    try {
      await api.post(`/tasks/${task.id}/claim`)
      await qc.invalidateQueries({ queryKey: ['tasks', projectId] })
    } catch (err) {
      alert(err instanceof ApiError ? err.message : '认领失败')
    }
  }

  async function doDelete() {
    if (!deleteTarget) return
    try {
      await deleteTask(deleteTarget.id)
      setDeleteTarget(null)
      await qc.invalidateQueries({ queryKey: ['tasks', projectId] })
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
          <h1 className="text-xl font-semibold">任务</h1>
          <p className="text-sm text-muted-foreground">
            当前项目:{currentProject.name}
            <span className="ml-1 text-xs">({role ?? '—'})</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex overflow-hidden rounded-md border">
            <Button variant={view === 'board' ? 'secondary' : 'ghost'} size="sm" className="rounded-none" onClick={() => setView('board')}>
              <LayoutGrid className="h-4 w-4" />
              看板
            </Button>
            <Button variant={view === 'list' ? 'secondary' : 'ghost'} size="sm" className="rounded-none" onClick={() => setView('list')}>
              <List className="h-4 w-4" />
              列表
            </Button>
          </div>
          {canEdit && (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              新建任务
            </Button>
          )}
        </div>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
      {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}
      {!isLoading && tasks.length === 0 && (
        <p className="py-10 text-center text-sm text-muted-foreground">暂无任务</p>
      )}

      {view === 'board' ? (
        <Kanban
          items={tasks}
          canDrag={canEdit}
          onMove={(id, to) => void doMove(id, to)}
          renderCard={(t) => (
            <TaskCard
              t={t}
              canEdit={canEdit}
              canDelete={canEdit}
              canSetStatus={canSetTaskStatus(t, user, role)}
              onStatus={onCardStatus}
              onClaim={claim}
              onDelete={setDeleteTarget}
            />
          )}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {tasks.map((t) => (
            <TaskCard
              key={t.id}
              t={t}
              canEdit={canEdit}
              canDelete={canEdit}
              canSetStatus={canSetTaskStatus(t, user, role)}
              onStatus={onCardStatus}
              onClaim={claim}
              onDelete={setDeleteTarget}
            />
          ))}
        </div>
      )}

      <CreateTaskDialog open={createOpen} onOpenChange={setCreateOpen} />

      <Dialog open={deleteTarget !== null} onOpenChange={(v) => !v && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除任务</DialogTitle>
            <DialogDescription>
              确认删除任务「{deleteTarget?.title}」?删除为软删,可从恢复入口找回。
            </DialogDescription>
          </DialogHeader>
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
