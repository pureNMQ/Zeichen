import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams, useNavigate, useLocation } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, EyeOff, Eye, FolderOpen, Pencil, Plus, Trash2, UserPlus } from 'lucide-react'
import { ParticipantAvatars } from '@/components/participant-avatars'

import { ActivityStream } from '@/components/activity-stream'
import { AttachmentList, RelatedFiles } from '@/components/attachment-list'
import { CommentStream } from '@/components/comment-stream'
import { WorkHistory } from '@/components/work-history'
import { VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { RequirementDependencies } from '@/components/requirement-dependencies'
import { Kanban } from '@/components/kanban'
import { RequirementTimeline } from '@/components/requirement-timeline'
import { TaskReader } from '@/components/task-reader'
import { MarkdownBacklinks } from '@/components/markdown-backlinks'
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
  type RequirementRow,
  type TaskRow,
  type WorkflowStatus,
} from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'
import { projectResourceHref } from '@/lib/project-links'
import { canManageTask } from '@/lib/task-perms'

// 旧 UUID 标识(迁移前书签/引用)→ 引导提示(ADR 0002 §6:不做跳转)
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// 任务看板列(ADR 0003 四态):已取消列随「隐藏已取消」开关显隐
const TASK_BOARD_COLUMNS: WorkflowStatus[] = ['backlog', 'in_progress', 'done']
const TASK_BOARD_COLUMNS_ALL: WorkflowStatus[] = ['backlog', 'in_progress', 'done', 'cancelled']

interface TaskCardProps {
  task: TaskRow
  canManage: boolean
  onOpen: (taskId: string) => void
  onStatus: (task: TaskRow, status: string) => void
  onClaim: (taskId: string) => void
  onDelete: (taskId: string) => void
}

function TaskCard({ task: t, canManage, onOpen, onStatus, onClaim, onDelete }: TaskCardProps) {
  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <button
          type="button"
          className="block w-full text-left text-sm font-medium hover:text-primary"
          onClick={() => onOpen(t.id)}
          id={`work-task-${t.id}`}
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
            disabled={!canManage}
          />
          {t.assignee && (
            <Badge variant="outline" className="gap-1.5">
              <UserAvatar user={{ id: t.assignee_id, username: t.assignee, avatar: t.assignee_avatar }} className="h-4 w-4 text-[9px]" />
              {t.assignee}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {canManage && !t.assignee_id && t.status !== 'done' && t.status !== 'cancelled' && (
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
          {canManage && (
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs text-muted-foreground hover:text-destructive"
              onClick={() => onDelete(t.id)}
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
  return <RequirementDetail key={id} id={id} />
}

function RequirementDetail({ id }: { id: string }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const qc = useQueryClient()
  const role = useProjectRole()
  const { user } = useAuth()
  const { currentProject, isLoading: cpLoading, routeProjectId, selectProject } = useCurrentProject()
  const canEdit = role === 'editor' || role === 'owner'
  const encodedId = encodeURIComponent(id)
  const requirementsHref = routeProjectId ? projectResourceHref(routeProjectId, 'requirements') : '/requirements'
  const [actionError, setActionError] = useState<string | null>(null)
  const navigate = useNavigate()
  const { hash } = useLocation()
  const [showCancelled, setShowCancelled] = useState(false)
  const [deleteTaskId, setDeleteTaskId] = useState<string | null>(null)

  const { data: req, isLoading, error } = useQuery({
    queryKey: ['requirement', id, routeProjectId],
    // 旧入口的全局短码解析;跨项目同码(400 invalid_request)时用当前项目重试消歧(REQ-55)
    queryFn: async () => {
      if (routeProjectId) {
        const requirement = await api.get<RequirementRow>(`${requirementsHref}/${encodedId}`)
        if (requirement.project_id !== routeProjectId) throw new ApiError(404, '需求不存在或无访问权限')
        return requirement
      }
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
  const { data: tasks, error: tasksError } = useQuery({
    queryKey: ['requirement-tasks', id, req?.project_id],
    queryFn: async ({ signal }) => {
      const items: TaskRow[] = []
      let cursor: string | null = null
      do {
        const result: { items: TaskRow[]; next_cursor?: string | null } = await api.get(`/projects/${req?.project_id}/tasks?requirement_id=${encodedId}&limit=100${cursor ? '&cursor=' + encodeURIComponent(cursor) : ''}`, signal)
        items.push(...result.items)
        cursor = result.next_cursor ?? null
      } while (cursor)
      return { items }
    },
    enabled: !!req,
  })
  const deleteTarget = tasks?.items.find(task => task.id === deleteTaskId && canManageTask(task, user, role))
  useEffect(() => {
    if (deleteTaskId && !deleteTarget) setDeleteTaskId(null)
  }, [deleteTaskId, deleteTarget])

  // 任务链接可能包含迁移前的短码和旧父需求，统一在当前项目解析。
  const deepLinkTask = searchParams.get('task')
  const { data: linkedTask, isError: linkedTaskError } = useQuery({
    queryKey: ['task', deepLinkTask, routeProjectId],
    queryFn: async () => {
      const task = await api.get<TaskRow>(withProject(`/tasks/${encodeURIComponent(deepLinkTask!)}`, routeProjectId))
      if (task.project_id !== routeProjectId) throw new ApiError(404, '任务不存在或无访问权限')
      return task
    },
    enabled: !!routeProjectId && !!deepLinkTask,
    retry: false,
  })
  useEffect(() => {
    if (routeProjectId && deepLinkTask && /^TASK-[1-9]\d*$/.test(deepLinkTask) && linkedTask?.requirement_id
      && (linkedTask.id !== deepLinkTask || linkedTask.requirement_id !== id)) {
      const next = new URLSearchParams(searchParams)
      next.set('task', linkedTask.id)
      navigate(projectResourceHref(routeProjectId, 'requirements', linkedTask.requirement_id) + '?' + next.toString(), { replace: true })
    }
  }, [routeProjectId, deepLinkTask, linkedTask, id, navigate, searchParams])
  const activeTab = (searchParams.has('entry') || hash.startsWith('#timeline-')) ? 'timeline' : searchParams.has('version') && !deepLinkTask ? 'history' : searchParams.get('tab') ?? 'tasks'
  const focusTask = searchParams.get('focus')
  useEffect(() => {
    if (activeTab === 'tasks' && focusTask && tasks) document.getElementById(`work-task-${focusTask}`)?.focus()
  }, [activeTab, focusTask, tasks])
  function setTab(tab: string) {
    const params = new URLSearchParams(searchParams)
    for (const key of ['task','entry','timelineVersion','focus','version','taskTab']) params.delete(key)
    params.set('tab', tab)
    navigate({ search: params.toString(), hash: '' }, { replace: !deepLinkTask })
  }
  function openTask(tid: string) {
    const params = new URLSearchParams(searchParams)
    params.set('task', tid)
    setSearchParams(params)
  }
  function invalidateTimeline() {
    if (routeProjectId) void qc.invalidateQueries({ queryKey: ['requirement-timeline', routeProjectId, id] })
  }

  async function act(path: string, body?: unknown) {
    setActionError(null)
    try {
      await api.post(withProject(path, req?.project_id), body)
      await qc.invalidateQueries({ queryKey: ['requirement', id] })
      await qc.invalidateQueries({ queryKey: ['activity', 'requirement', id] })
      invalidateTimeline()
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
      await qc.invalidateQueries({ queryKey: ['requirement', id] })
      await qc.invalidateQueries({ queryKey: ['requirements', req?.project_id] })
      invalidateTimeline()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '认领失败')
    }
  }

  async function changeTaskStatus(t: TaskRow, status: string) {
    if (!canManageTask(t, user, role) || status === t.status) return
    setActionError(null)
    try {
      await api.post(withProject(`/tasks/${t.id}/status`, req?.project_id), { status })
      await qc.invalidateQueries({ queryKey: ['requirement-tasks', id] })
      await qc.invalidateQueries({ queryKey: ['tasks', req?.project_id] })
      await qc.invalidateQueries({ queryKey: ['requirement', id] })
      await qc.invalidateQueries({ queryKey: ['requirements', req?.project_id] })
      invalidateTimeline()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '状态变更失败')
    }
  }

  async function doDeleteTask() {
    if (!deleteTarget) return
    setActionError(null)
    try {
      await api.post(withProject(`/tasks/${deleteTarget.id}/delete`, req?.project_id))
      setDeleteTaskId(null)
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
  const selectedTask = (linkedTask?.requirement_id === req.id ? linkedTask : null)
    ?? allTasks.find(t => t.id === deepLinkTask)
  const taskLinkUnavailable = routeProjectId && deepLinkTask && !selectedTask
    && (linkedTaskError || (linkedTask && linkedTask.requirement_id !== req.id))

  if (deepLinkTask && selectedTask) return <TaskReader key={selectedTask.id} task={selectedTask} onBack={() => setTab('tasks')} />
  const detailHref = projectResourceHref(req.project_id, 'requirements', req.id)
  return (
    <div className="min-w-0 space-y-4">
      <Button asChild variant="ghost" size="sm">
        <Link to={requirementsHref}><ArrowLeft aria-hidden="true" />返回需求</Link>
      </Button>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold">
              <span className="mr-2 rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">{req.id}</span>
              {req.title}
            </h1>
            {canEdit && <Button asChild variant="ghost" size="icon">
              <Link to={detailHref + '/edit'} title="编辑需求" aria-label="编辑需求"><Pencil aria-hidden="true" /></Link>
            </Button>}
          </div>
          <ParticipantAvatars participants={req.participants} />
        </div>
        <div className="flex shrink-0 gap-2">
          {!routeProjectId && <WatchButton targetType="requirement" targetId={req.id} />}
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
      <ErrorNotification message={taskLinkUnavailable ? '任务不存在或不属于此需求' : null} />

      <RequirementDependencies item={req} canEdit={canEdit} />
      <nav aria-label="需求内容" className="flex flex-wrap gap-1 border-b pb-1">
        {Object.entries({body:'正文',tasks:'任务',timeline:'时间线',history:'历史版本'}).map(([key,label]) =>
          <Button key={key} size="sm" variant={activeTab === key ? 'secondary' : 'ghost'} aria-current={activeTab === key ? 'page' : undefined} onClick={() => setTab(key)}>{label}</Button>)}
      </nav>
      <ErrorNotification message={tasksError?.message} />
      {activeTab === 'tasks' && <Card>
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
              {showCancelled ? '隐藏已取消' : '显示已取消'}
            </Button>
            {canEdit && (
              <Button size="sm" className="h-7 text-xs" onClick={() => navigate(detailHref + '/tasks/new')}>
                <Plus className="mr-1 h-3 w-3" />
                新建任务
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
            <Kanban
              items={visibleTasks}
              canDrag={canEdit}
              canDragItem={t => canManageTask(t, user, role)}
              columns={showCancelled ? TASK_BOARD_COLUMNS_ALL : TASK_BOARD_COLUMNS}
              onMove={async (taskId, to) => {
                const target = allTasks.find((x) => x.id === taskId)
                if (target) await changeTaskStatus(target, to)
              }}
              renderCard={(t) => (
                <TaskCard
                  task={t}
                  canManage={canManageTask(t, user, role)}
                  onOpen={openTask}
                  onStatus={(task, s) => void changeTaskStatus(task, s)}
                  onClaim={(taskId) => void claimPanelTask(taskId)}
                  onDelete={setDeleteTaskId}
                />
              )}
            />
        </CardContent>
      </Card>}

      {activeTab === 'body' && <>
        <VditorMarkdownViewer markdown={req.description ?? ''} />
        {routeProjectId && <MarkdownBacklinks projectId={routeProjectId} kind="requirements" id={req.id} />}
      {routeProjectId
        ? <RelatedFiles key={req.id} projectId={routeProjectId} targetKind="requirements" targetId={req.id} canEdit={canEdit} />
        : <AttachmentList targetType="requirement" targetId={req.id} />}
      </>}
      {activeTab === 'history' && <WorkHistory item={req} projectId={req.project_id} kind="requirements" canEdit={canEdit} />}
      {activeTab === 'timeline' && (routeProjectId
        ? <RequirementTimeline key={`${routeProjectId}:${req.id}`} projectId={routeProjectId} requirementId={req.id}
            tasks={tasks?.items} participants={req.participants} canWrite={canEdit} canModerate={role === 'owner'} />
        : <><CommentStream targetType="requirement" targetId={req.id} canEdit={canEdit} /><ActivityStream targetType="requirement" targetId={req.id} /></>)}

      <Dialog open={!!deleteTarget} onOpenChange={(v) => !v && setDeleteTaskId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除任务</DialogTitle>
            <DialogDescription>
              确认删除任务「{deleteTarget?.title}」?删除为软删,可从恢复入口找回。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTaskId(null)}>
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
