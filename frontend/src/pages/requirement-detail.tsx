import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, EyeOff, Eye, FolderOpen, Plus, Trash2, UserPlus } from 'lucide-react'

import { ActivityStream } from '@/components/activity-stream'
import { AttachmentList } from '@/components/attachment-list'
import { CommentStream } from '@/components/comment-stream'
import { CreateTaskDialog } from '@/components/create-task-dialog'
import { Kanban } from '@/components/kanban'
import { TaskDetailDialog } from '@/components/task-detail-dialog'
import { TaskRefLink } from '@/components/task-ref-link'
import { StatusBadge } from '@/components/status-badge'
import { StatusSelect } from '@/components/status-select'
import { Badge } from '@/components/ui/badge'
import { UserAvatar } from '@/components/user-avatar'
import { Button } from '@/components/ui/button'
import { WatchButton } from '@/components/watch-button'
import { ErrorNotification } from '@/components/ui/notification'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  api,
  ApiError,
  REQUIREMENT_STATUSES,
  TASK_STATUSES,
  withProject,
  type ReferenceRow,
  type RequirementRow,
  type TaskRow,
  type WorkflowStatus,
} from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'
import { canSetTaskStatus } from '@/lib/task-perms'

function referenceHref(type: string, id: string, _module?: string | null) {
  if (type === 'requirement') return `/requirements/${id}`
  // task 引用走 TaskRefLink(任务无独立页面,ADR 0003)
  // REQ-59:glossary 并入 wiki,文档引用统一走 wiki 工作台(TERM-n 短码同样可达)
  if (type === 'document') return `/documents/wiki/${id}`
  return null
}

// 旧 UUID 标识(迁移前书签/引用)→ 引导提示(ADR 0002 §6:不做跳转)
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// 任务看板列(ADR 0003 四态):已取消列随「隐藏已取消」开关显隐
const TASK_BOARD_COLUMNS: WorkflowStatus[] = ['backlog', 'in_progress', 'done']
const TASK_BOARD_COLUMNS_ALL: WorkflowStatus[] = ['backlog', 'in_progress', 'done', 'cancelled']

interface TaskCardProps {
  task: TaskRow
  canEdit: boolean
  onOpen: (taskId: string) => void
  onStatus: (task: TaskRow, status: string) => void
  onClaim: (taskId: string) => void
  onDelete: (task: TaskRow) => void
}

function TaskCard({ task: t, canEdit, onOpen, onStatus, onClaim, onDelete }: TaskCardProps) {
  const { user } = useAuth()
  const role = useProjectRole()
  const canStatus = canSetTaskStatus(t, user, role)
  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <button
          type="button"
          className="block w-full text-left text-sm font-medium hover:text-primary"
          onClick={() => onOpen(t.id)}
          aria-label={`打开任务 ${t.title}`}
        >
          <span className="mr-1.5 rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-muted-foreground">{t.id}</span>
          {t.title}
        </button>
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusSelect
            value={t.status}
            statuses={TASK_STATUSES}
            onSelect={(s) => onStatus(t, s)}
            disabled={!canStatus}
          />
          {t.blocked && <Badge variant="destructive">受阻</Badge>}
          {t.assignee && (
            <Badge variant="outline" className="gap-1.5">
              <UserAvatar user={{ id: t.assignee_id, username: t.assignee, avatar: t.assignee_avatar }} className="h-4 w-4 text-[9px]" />
              {t.assignee}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {canEdit && !t.assignee_id && t.status !== 'done' && t.status !== 'cancelled' && (
            <Button
              variant="outline"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => onClaim(t.id)}
            >
              <UserPlus className="mr-1 h-3 w-3" />
              认领
            </Button>
          )}
          {canEdit && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs text-muted-foreground hover:text-destructive"
              onClick={() => onDelete(t)}
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

function Guide({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-muted-foreground">
      <FolderOpen className="h-10 w-10" />
      {children}
    </div>
  )
}

export function RequirementDetailPage() {
  const { id = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const qc = useQueryClient()
  const role = useProjectRole()
  const { currentProject, isLoading: cpLoading, selectProject } = useCurrentProject()
  const canEdit = role === 'editor' || role === 'owner'
  const [actionError, setActionError] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [showCancelled, setShowCancelled] = useState(false)
  const [dialogTaskId, setDialogTaskId] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<TaskRow | null>(null)

  const { data: req, isLoading, error } = useQuery({
    queryKey: ['requirement', id],
    // 全局短码解析;跨项目同码(400 invalid_request)时用当前项目重试消歧(REQ-55)
    queryFn: async () => {
      try {
        return await api.get<RequirementRow>(`/requirements/${id}`)
      } catch (err) {
        if (err instanceof ApiError && err.status === 400) {
          return await api.get<RequirementRow>(withProject(`/requirements/${id}`))
        }
        throw err
      }
    },
  })
  const { data: tasks } = useQuery({
    queryKey: ['requirement-tasks', id],
    queryFn: () => api.get<{ items: TaskRow[] }>(`/projects/${req?.project_id}/tasks?requirement_id=${id}&limit=100`),
    enabled: !!req,
  })
  const { data: refs } = useQuery({
    queryKey: ['refs', 'requirement', id],
    queryFn: () => api.get<{ items: ReferenceRow[] }>(withProject(`/targets/requirement/${id}/references?limit=50`, req?.project_id)),
    enabled: !!req,
  })

  // 通知/搜索跳转:/requirements/:rid?task=TID 定位任务弹窗
  const deepLinkTask = searchParams.get('task')
  useEffect(() => {
    if (deepLinkTask) setDialogTaskId(deepLinkTask)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkTask])

  function openTask(tid: string) {
    setDialogTaskId(tid)
    if (deepLinkTask !== tid) setSearchParams({ task: tid }, { replace: true })
  }

  function closeTaskDialog() {
    setDialogTaskId(null)
    if (deepLinkTask) setSearchParams({}, { replace: true })
  }

  async function act(path: string, body?: unknown) {
    setActionError(null)
    try {
      await api.post(withProject(path, req?.project_id), body)
      await qc.invalidateQueries({ queryKey: ['requirement', id] })
      await qc.invalidateQueries({ queryKey: ['activity', 'requirement', id] })
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '操作失败')
    }
  }

  async function setStatus(status: string) {
    if (status === req?.status) return
    await act(`/requirements/${id}/status`, { status })
  }

  async function claimPanelTask(taskId: string) {
    setActionError(null)
    try {
      await api.post(withProject(`/tasks/${taskId}/claim`, req?.project_id))
      await qc.invalidateQueries({ queryKey: ['requirement-tasks', id] })
      await qc.invalidateQueries({ queryKey: ['tasks', req?.project_id] })
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '认领失败')
    }
  }

  async function changeTaskStatus(t: TaskRow, status: string) {
    if (status === t.status) return
    setActionError(null)
    try {
      await api.post(withProject(`/tasks/${t.id}/status`, req?.project_id), { status })
      await qc.invalidateQueries({ queryKey: ['requirement-tasks', id] })
      await qc.invalidateQueries({ queryKey: ['tasks', req?.project_id] })
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '状态变更失败')
    }
  }

  async function doDeleteTask() {
    if (!deleteTarget) return
    setActionError(null)
    try {
      await api.post(withProject(`/tasks/${deleteTarget.id}/delete`, req?.project_id))
      setDeleteTarget(null)
      await qc.invalidateQueries({ queryKey: ['requirement-tasks', id] })
      await qc.invalidateQueries({ queryKey: ['requirements', req?.project_id] })
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  if (cpLoading || isLoading) return <p className="text-sm text-muted-foreground">加载中…</p>
  if (!currentProject) {
    return (
      <Guide>
        <p className="text-sm">暂无当前项目,请在侧边栏选择项目</p>
      </Guide>
    )
  }
  if (error || !req) {
    if (UUID_PATTERN.test(id)) {
      return (
        <Guide>
          <p className="text-sm">
            实体标识已全面改用短码(如 REQ-1)。该 UUID 链接已失效,请从需求列表重新进入。
          </p>
          <Button onClick={() => (window.location.href = '/requirements')}>前往需求列表</Button>
        </Guide>
      )
    }
    return <ErrorNotification message={(error as Error)?.message ?? '需求不存在'} />
  }
  if (req.project_id !== currentProject.id) {
    return (
      <Guide>
        <p className="text-sm">该需求不属于当前项目「{currentProject.name}」</p>
        <Button onClick={() => selectProject(req.project_id)}>切换到该项目</Button>
      </Guide>
    )
  }

  const isPending = req.status === 'pending'
  const allTasks = tasks?.items ?? []
  const visibleTasks = showCancelled ? allTasks : allTasks.filter((t) => t.status !== 'cancelled')
  const doneCount = allTasks.filter((t) => t.status === 'done').length
  const totalCount = allTasks.length
  const dialogTask = allTasks.find((t) => t.id === dialogTaskId) ?? null

  return (
    <div className="space-y-4">
      <Link to="/requirements" className="text-sm text-muted-foreground hover:text-primary">
        ← 返回需求
      </Link>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">
              <span className="mr-2 rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">{req.id}</span>
              {req.title}
            </h1>
            <StatusBadge status={req.status} />
          </div>
          {req.description && <p className="mt-2 text-sm text-muted-foreground">{req.description}</p>}
        </div>
        <div className="flex shrink-0 gap-2">
          <WatchButton targetType="requirement" targetId={req.id} />
          {canEdit && isPending && (
            <Button onClick={() => void setStatus('backlog')}>
              <Check className="mr-2 h-4 w-4" />
              确认需求
            </Button>
          )}
          <StatusSelect
            value={req.status}
            statuses={REQUIREMENT_STATUSES}
            onSelect={(s) => void setStatus(s)}
            disabled={!canEdit}
          />
        </div>
      </div>
      <ErrorNotification message={actionError} />

      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm">
            任务({totalCount})
            <span className="ml-2 font-normal text-muted-foreground">
              完成 {doneCount}/{totalCount}
            </span>
          </CardTitle>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => setShowCancelled((v) => !v)}
            >
              {showCancelled ? <Eye className="mr-1 h-3 w-3" /> : <EyeOff className="mr-1 h-3 w-3" />}
              {showCancelled ? '显示全部' : '隐藏已取消'}
            </Button>
            {canEdit && !isPending && (
              <Button size="sm" className="h-7 text-xs" onClick={() => setCreateOpen(true)}>
                <Plus className="mr-1 h-3 w-3" />
                新建任务
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {isPending && (
            <p className="text-sm text-muted-foreground">需求确认后才能创建任务。</p>
          )}
          {!isPending && visibleTasks.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {showCancelled ? '暂无任务' : '暂无任务(已取消默认隐藏)'}
            </p>
          )}
          {!isPending && visibleTasks.length > 0 && (
            <Kanban
              items={visibleTasks}
              canDrag={canEdit}
              columns={showCancelled ? TASK_BOARD_COLUMNS_ALL : TASK_BOARD_COLUMNS}
              onMove={(taskId, to) => {
                const target = allTasks.find((x) => x.id === taskId)
                if (target) void changeTaskStatus(target, to)
              }}
              renderCard={(t) => (
                <TaskCard
                  task={t}
                  canEdit={canEdit}
                  onOpen={openTask}
                  onStatus={(task, s) => void changeTaskStatus(task, s)}
                  onClaim={(taskId) => void claimPanelTask(taskId)}
                  onDelete={setDeleteTarget}
                />
              )}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">引用</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {(refs?.items ?? []).length === 0 && <p className="text-sm text-muted-foreground">暂无引用</p>}
          {refs?.items.map((r) => (
            <div key={r.id} className="flex items-center gap-2 rounded-md border p-2.5 text-sm">
              <Badge variant="outline">{r.type}</Badge>
              <span className="text-xs text-muted-foreground">
                {(() => { const href = referenceHref(r.from_type, r.from_id, r.from_module); if (href) return <Link to={href} className="hover:text-primary hover:underline">{r.from_title ?? r.from_id}</Link>; if (r.from_type === 'task') return <TaskRefLink taskId={r.from_id}>{r.from_title ?? r.from_id}</TaskRefLink>; return r.from_title ?? r.from_id })()}
                {' → '}
                {(() => { const href = referenceHref(r.to_type, r.to_id, r.to_module); if (href) return <Link to={href} className="hover:text-primary hover:underline">{r.to_title ?? r.to_id}</Link>; if (r.to_type === 'task') return <TaskRefLink taskId={r.to_id}>{r.to_title ?? r.to_id}</TaskRefLink>; return r.to_title ?? r.to_id })()}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-6 p-4">
          <CommentStream targetType="requirement" targetId={req.id} canEdit={req.status !== 'cancelled'} />
        </CardContent>
      </Card>
      <AttachmentList targetType="requirement" targetId={req.id} />
      <Card>
        <CardContent className="p-4">
          <ActivityStream targetType="requirement" targetId={req.id} />
        </CardContent>
      </Card>

      <TaskDetailDialog
        task={dialogTask}
        open={dialogTaskId !== null && dialogTask !== null}
        onOpenChange={(v) => !v && closeTaskDialog()}
      />

      <CreateTaskDialog open={createOpen} onOpenChange={setCreateOpen} presetRequirementId={req.id} onCreated={() => qc.invalidateQueries({ queryKey: ['requirement-tasks', id] })} />

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
            <Button variant="destructive" onClick={() => void doDeleteTask()}>
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
