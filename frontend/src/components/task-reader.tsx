import { MarkdownBacklinks } from '@/components/markdown-backlinks'
import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { WorkHistory } from '@/components/work-history'
import { VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, ChevronDown, Pencil, UserRound, UserPlus, UserX } from 'lucide-react'

import { ActivityStream } from '@/components/activity-stream'
import { RelatedFiles } from '@/components/attachment-list'
import { StatusSelect } from '@/components/status-select'
import { WatchButton } from '@/components/watch-button'
import { Button } from '@/components/ui/button'
import { ErrorNotification } from '@/components/ui/notification'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { UserAvatar } from '@/components/user-avatar'
import {
  api,
  ApiError,
  TASK_STATUSES,
  withProject,
  type UserIdentity,
  type TaskRow,
} from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useCurrentProject } from '@/lib/current-project'
import { canManageTask } from '@/lib/task-perms'

export function TaskReader({ task, onBack }: { task: TaskRow; onBack: () => void }) {
  const [params, setParams] = useSearchParams()
  const history = params.has('version') || params.get('taskTab') === 'history'
  function setHistory(open: boolean) {
    setParams(prev => {const next = new URLSearchParams(prev); next.delete('version')
      if (open) next.set('taskTab', 'history')
      else next.delete('taskTab')
      return next
    }, { replace:true })
  }
  const { user } = useAuth()
  const qc = useQueryClient()
  const { role, routeProjectId } = useCurrentProject()
  const [error, setError] = useState<string | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const actionPending = useRef(false)

  const projectId = task?.project_id

  const { data: fresh } = useQuery({
    queryKey: ['task', task?.id, projectId],
    queryFn: () => api.get<TaskRow>(withProject(`/tasks/${task?.id}`, projectId)),
    enabled: !!task,
  })
  const t = fresh?.id === task.id && fresh.project_id === task.project_id && fresh.requirement_id === task.requirement_id ? fresh : task

  const canEditTask = role === 'editor' || role === 'owner'
  const canManage = canManageTask(t, user, role)
  const pending = !!t && ['backlog', 'in_progress'].includes(t.status)
  const editableAssignee = pending && canManage
  const memberQuery = useQuery({
    queryKey: ['task-assignees', projectId],
    queryFn: () => api.get<(UserIdentity & { is_agent: boolean })[]>(`/projects/${projectId}/assignees`),
    enabled: editableAssignee && pickerOpen,
  })
  const members = Array.isArray(memberQuery.data) ? memberQuery.data : []
  const candidates = members.filter(m => m.id !== user?.id && m.id !== t.assignee_id)

  async function refresh() {
    await qc.invalidateQueries({ queryKey: ['task', t?.id] })
    await qc.invalidateQueries({ queryKey: ['requirement', t?.requirement_id] })
    await qc.invalidateQueries({ queryKey: ['requirements', projectId] })
    await qc.invalidateQueries({ queryKey: ['requirement-tasks', t?.requirement_id] })
    await qc.invalidateQueries({ queryKey: ['tasks', projectId] })
    await qc.invalidateQueries({ queryKey: ['activity', 'task', t?.id] })
    if (routeProjectId && t?.requirement_id) {
      void qc.invalidateQueries({ queryKey: ['requirement-timeline', routeProjectId, t.requirement_id] })
    }
  }

  async function act(path: string, body?: unknown) {
    if (actionPending.current) return
    actionPending.current = true
    setSaving(true)
    setError(null)
    try {
      await api.post(withProject(path, projectId), body)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败')
      if (err instanceof ApiError && err.status === 409) await refresh()
    } finally {
      actionPending.current = false
      setSaving(false)
    }
  }

  async function setStatus(status: string) {
    if (!t || status === t.status) return
    await act(`/tasks/${t.id}/status`, { status })
  }

  const assigneeLabel = t.assignee || '未指派'
  const assigneeIdentity = <>
    {t.assignee_id
      ? <UserAvatar user={{ id: t.assignee_id, username: assigneeLabel, avatar: t.assignee_avatar }} className="size-5" />
      : <UserRound className="size-4 text-muted-foreground" aria-hidden="true" />}
    <span className="truncate">{assigneeLabel}</span>
  </>

  if (!t) return null

  return (
    <section className="mx-auto max-w-5xl space-y-4">
      <Button variant="ghost" size="sm" onClick={onBack}><ArrowLeft aria-hidden="true" />返回所属需求 {t.requirement_id}</Button>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="min-w-0 break-words text-xl font-semibold"><span className="mr-2 text-sm font-mono text-muted-foreground">{t.id}</span>{t.title}</h1>
        {canEditTask && <Button asChild variant="ghost" size="icon">
          <Link title="编辑任务" aria-label="编辑任务" to={`/projects/${projectId}/requirements/${t.requirement_id}/tasks/${t.id}/edit`}><Pencil aria-hidden="true" /></Link>
        </Button>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <StatusSelect value={t.status} statuses={TASK_STATUSES} onSelect={s => void setStatus(s)} disabled={!canManage || saving} />
        {!routeProjectId && <WatchButton targetType="task" targetId={t.id} />}
        <div className="flex min-w-0 max-w-full items-center gap-1.5 text-sm">
          <span className="shrink-0 text-muted-foreground">负责人</span>
          {editableAssignee ? (
            <DropdownMenu open={pickerOpen} onOpenChange={setPickerOpen}>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="min-w-0" disabled={saving} aria-label={`负责人：${assigneeLabel}`}>
                  {assigneeIdentity}<ChevronDown aria-hidden="true" className="text-muted-foreground" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="min-w-48 max-w-[calc(100vw-2rem)]">
                {t.assignee_id && <DropdownMenuItem disabled>
                  {assigneeIdentity}<Check aria-label="当前负责人" className="ml-auto" />
                </DropdownMenuItem>}
                {user && t.assignee_id !== user.id && <DropdownMenuItem
                  onSelect={() => void (t.assignee_id
                    ? act(`/tasks/${t.id}/assign`, { assignee_id: user.id })
                    : act(`/tasks/${t.id}/claim`))}>
                  <UserPlus aria-hidden="true" />{t.assignee_id ? '指派给我' : '我来认领'}
                </DropdownMenuItem>}
                {candidates.length > 0 && <DropdownMenuLabel>指派给</DropdownMenuLabel>}
                {candidates.map(m => <DropdownMenuItem key={m.id} onSelect={() => void act(`/tasks/${t.id}/assign`, { assignee_id: m.id })}>
                  <UserAvatar user={m} className="size-5" /><span className="truncate">{m.nickname || m.username}</span>
                  {m.is_agent && <span className="ml-auto text-xs text-muted-foreground">Agent</span>}
                </DropdownMenuItem>)}
                {memberQuery.isLoading && <DropdownMenuItem disabled>加载成员中…</DropdownMenuItem>}
                {memberQuery.isError && <DropdownMenuItem onSelect={event => { event.preventDefault(); void memberQuery.refetch() }}>重新加载成员</DropdownMenuItem>}
                {t.assignee_id && <><DropdownMenuSeparator /><DropdownMenuItem onSelect={() => void act(`/tasks/${t.id}/unassign`)}>
                  <UserX aria-hidden="true" />解除指派
                </DropdownMenuItem></>}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : <span className="inline-flex min-w-0 items-center gap-1.5">{assigneeIdentity}</span>}
        </div>
      </div>

      <div className="flex gap-1 border-b pb-1">
        <Button variant={history ? 'ghost' : 'secondary'} size="sm" onClick={() => setHistory(false)}>正文</Button>
        <Button variant={history ? 'secondary' : 'ghost'} size="sm" onClick={() => setHistory(true)}>历史版本</Button>
      </div>
      {history ? <WorkHistory projectId={t.project_id} kind="tasks" item={t} canEdit={canEditTask} /> :
        <VditorMarkdownViewer markdown={t.description ?? ''} />}
          <ErrorNotification message={error || (pickerOpen ? memberQuery.error?.message : null)} />

          {!history && routeProjectId && <MarkdownBacklinks projectId={routeProjectId} kind="tasks" id={t.id} />}
          {!history && routeProjectId && <RelatedFiles key={`${routeProjectId}:${t.id}`} projectId={routeProjectId}
            targetKind="tasks" targetId={t.id} canEdit={canEditTask} />}
          {!routeProjectId && <div className="rounded-lg border p-2">
            <ActivityStream targetType="task" targetId={t.id} />
          </div>}
    </section>
  )
}
