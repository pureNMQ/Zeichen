import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, List, LayoutGrid, Plus, Trash2, UserPlus } from 'lucide-react'

import { Kanban } from '@/components/kanban'
import { StatusSelect } from '@/components/status-select'
import { CreateTaskDialog } from '@/components/create-task-dialog'
import { StatusFilterPopover } from '@/components/status-filter-popover'
import { FilterViewSwitcher, type ViewDef } from '@/components/filter-view-switcher'
import { ErrorNotification } from '@/components/ui/notification'
import { Badge } from '@/components/ui/badge'
import { UserAvatar } from '@/components/user-avatar'
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
import {
  api,
  ApiError,
  TASK_STATUSES,
  type FilterCriteria,
  type FilterViewMode,
  type MemberRow,
  type Page,
  type TaskRow,
  type WorkflowStatus,
} from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'
import { canSetTaskStatus } from '@/lib/task-perms'

const TIME_WINDOWS = [
  { value: '', label: '不限' },
  { value: '3', label: '近 3 天' },
  { value: '7', label: '近 7 天' },
  { value: '30', label: '近 30 天' },
]

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
          {t.blocked && <Badge variant="destructive">受阻</Badge>}
          {t.assignee && (
            <Badge variant="outline" className="gap-1.5">
              <UserAvatar user={{ id: t.assignee_id, username: t.assignee, avatar: t.assignee_avatar }} className="h-4 w-4 text-[9px]" />
              {t.assignee}
            </Badge>
          )}
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

  // 筛选条件(服务端下推)与视图状态
  const [statuses, setStatuses] = useState<string[]>([])
  const [updatedWithinDays, setUpdatedWithinDays] = useState('3')
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [assigneeId, setAssigneeId] = useState('')
  const [viewMode, setViewMode] = useState<FilterViewMode>('board')
  const [activeViewId, setActiveViewId] = useState('recent')

  const [createOpen, setCreateOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<TaskRow | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const keywordTimer = useRef<number | null>(null)

  const { data: membersData } = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => api.get<MemberRow[]>(`/projects/${projectId}/members`),
    enabled: !!projectId,
  })
  const members = Array.isArray(membersData) ? membersData : []

  function handleKeywordChange(value: string) {
    setKeywordInput(value)
    if (keywordTimer.current !== null) window.clearTimeout(keywordTimer.current)
    keywordTimer.current = window.setTimeout(() => {
      keywordTimer.current = null
      setKeyword(value)
    }, 300)
  }

  function applyView(def: ViewDef) {
    if (keywordTimer.current !== null) {
      window.clearTimeout(keywordTimer.current)
      keywordTimer.current = null
    }
    const c = def.criteria ?? {}
    setStatuses(c.statuses ?? [])
    setUpdatedWithinDays(c.updated_within_days != null ? String(c.updated_within_days) : '')
    const kw = c.keyword ?? ''
    setKeywordInput(kw)
    setKeyword(kw)
    setAssigneeId(c.assignee_id ?? '')
    setViewMode(def.view_mode)
    setActiveViewId(def.id)
  }

  const criteria: FilterCriteria = {
    view_mode: viewMode,
    ...(statuses.length > 0 ? { statuses: [...statuses] } : {}),
    ...(updatedWithinDays !== '' ? { updated_within_days: Number(updatedWithinDays) } : {}),
    ...(keyword.trim() !== '' ? { keyword: keyword.trim() } : {}),
    ...(assigneeId !== '' ? { assignee_id: assigneeId } : {}),
  }

  const {
    data: pageData,
    isLoading,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['tasks', projectId, { statuses, updatedWithinDays, keyword, assigneeId }],
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams()
      for (const s of statuses) params.append('status', s)
      if (updatedWithinDays !== '') params.set('updated_within_days', updatedWithinDays)
      const kw = keyword.trim()
      if (kw !== '') params.set('keyword', kw)
      if (assigneeId !== '') params.set('assignee_id', assigneeId)
      params.set('limit', '20')
      if (pageParam != null && pageParam !== '') params.set('cursor', String(pageParam))
      return api.get<Page<TaskRow>>(`/projects/${projectId}/tasks?${params.toString()}`)
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: !!projectId,
  })

  const tasks = (pageData?.pages ?? []).flatMap((p) => p.items)

  async function doMove(id: string, to: WorkflowStatus) {
    setActionError(null)
    try {
      await moveTask(id, to)
      await qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      await qc.invalidateQueries({ queryKey: ['requirements', projectId] })
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '状态变更失败')
      await qc.invalidateQueries({ queryKey: ['tasks', projectId] })
    }
  }

  function onCardStatus(t: TaskRow, s: string) {
    if (s === t.status) return
    void doMove(t.id, s as WorkflowStatus)
  }

  async function claim(task: TaskRow) {
    setActionError(null)
    try {
      await api.post(`/tasks/${task.id}/claim`)
      await qc.invalidateQueries({ queryKey: ['tasks', projectId] })
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '认领失败')
    }
  }

  async function doDelete() {
    if (!deleteTarget) return
    setActionError(null)
    try {
      await deleteTask(deleteTarget.id)
      setDeleteTarget(null)
      await qc.invalidateQueries({ queryKey: ['tasks', projectId] })
      await qc.invalidateQueries({ queryKey: ['requirements', projectId] })
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  if (cpLoading) return <p className="text-sm text-muted-foreground">加载中…</p>
  if (!currentProject) return <NoProjectGuide />

  return (
    <div className="flex min-h-[calc(100dvh-3rem)] flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">任务</h1>
          <p className="text-sm text-muted-foreground">
            当前项目:{currentProject.name}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <FilterViewSwitcher
            projectId={projectId ?? ''}
            entityType="task"
            activeViewId={activeViewId}
            onSelectView={applyView}
            currentCriteria={criteria}
          />
          {canEdit && (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              新建任务
            </Button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <StatusFilterPopover statuses={TASK_STATUSES} value={statuses} onChange={setStatuses} />
        <select
          aria-label="时间窗口"
          value={updatedWithinDays}
          onChange={(e) => setUpdatedWithinDays(e.target.value)}
          className="h-8 rounded-md border bg-transparent px-2 text-sm"
        >
          {TIME_WINDOWS.map((w) => (
            <option key={w.value} value={w.value}>
              {w.label}
            </option>
          ))}
        </select>
        {Array.isArray(membersData) && (
          <select
            aria-label="负责人"
            value={assigneeId}
            onChange={(e) => setAssigneeId(e.target.value)}
            className="h-8 rounded-md border bg-transparent px-2 text-sm"
          >
            <option value="">全部负责人</option>
            {members.map((m) => (
              <option key={m.id} value={m.id}>
                {m.nickname || m.username}
              </option>
            ))}
          </select>
        )}
        <div className="w-48">
          <Label htmlFor="task-keyword" className="sr-only">
            关键词
          </Label>
          <Input
            id="task-keyword"
            value={keywordInput}
            onChange={(e) => handleKeywordChange(e.target.value)}
            autoComplete="off"
            placeholder="关键词"
          />
        </div>
        <div className="flex overflow-hidden rounded-md border">
          <Button
            variant={viewMode === 'board' ? 'secondary' : 'ghost'}
            size="sm"
            className="rounded-none"
            onClick={() => setViewMode('board')}
          >
            <LayoutGrid className="h-4 w-4" />
            看板
          </Button>
          <Button
            variant={viewMode === 'list' ? 'secondary' : 'ghost'}
            size="sm"
            className="rounded-none"
            onClick={() => setViewMode('list')}
          >
            <List className="h-4 w-4" />
            列表
          </Button>
        </div>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
      <ErrorNotification message={error ? (error as Error).message : null} />
      <ErrorNotification message={actionError} />
      {!isLoading && viewMode === 'list' && tasks.length === 0 && (
        <p className="py-10 text-center text-sm text-muted-foreground">暂无任务</p>
      )}

      {viewMode === 'board' ? (
        <Kanban
          className="flex-1"
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

      {hasNextPage && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            onClick={() => void fetchNextPage()}
            disabled={isFetchingNextPage}
          >
            {isFetchingNextPage ? '加载中…' : '加载更多'}
          </Button>
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
