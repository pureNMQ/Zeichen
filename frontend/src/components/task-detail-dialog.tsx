import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { UserPlus, UserX, X } from 'lucide-react'

import { ActivityStream } from '@/components/activity-stream'
import { StatusBadge } from '@/components/status-badge'
import { StatusSelect } from '@/components/status-select'
import { WatchButton } from '@/components/watch-button'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ErrorNotification } from '@/components/ui/notification'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { UserAvatar } from '@/components/user-avatar'
import {
  api,
  ApiError,
  TASK_STATUSES,
  type ProjectMemberRow,
  type RequirementRow,
  type TaskRow,
} from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useProjectRole } from '@/lib/current-project'
import { canSetTaskStatus } from '@/lib/task-perms'

// 任务详情弹窗(ADR 0003):任务收归需求后不再有独立详情页,由需求详情任务面板打开。
// 内容:标题/描述/状态流转/指派与解除/改指向需求/阻塞依赖维护/活动流;无评论区。

export function TaskDetailDialog({
  task,
  open,
  onOpenChange,
}: {
  task: TaskRow | null
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const role = useProjectRole()
  const [error, setError] = useState<string | null>(null)

  const projectId = task?.project_id

  const { data: fresh } = useQuery({
    queryKey: ['task', task?.id],
    queryFn: () => api.get<TaskRow>(`/tasks/${task?.id}`),
    enabled: open && !!task,
  })
  const t = fresh ?? task
  const { data: requirements } = useQuery({
    queryKey: ['requirements', projectId],
    queryFn: () =>
      api.get<{ items: RequirementRow[]; next_cursor: string | null }>(
        `/projects/${projectId}/requirements?limit=100`,
      ),
    enabled: open && !!projectId,
  })
  const { data: membersData } = useQuery({
    queryKey: ['project-members', projectId],
    queryFn: () => api.get<ProjectMemberRow[]>(`/projects/${projectId}/members`),
    enabled: open && !!projectId,
  })
  const { data: projectTasks } = useQuery({
    queryKey: ['tasks', projectId],
    queryFn: () =>
      api.get<{ items: TaskRow[] }>(`/projects/${projectId}/tasks?limit=100`),
    enabled: open && !!projectId,
  })

  const members = Array.isArray(membersData) ? membersData : []
  const isAdmin = user?.workspace_role === 'admin'
  const isAssignee = t?.assignee_id === user?.id
  const isOwner = role === 'owner'
  const canManage = isAdmin || isOwner || isAssignee
  const canEditTask = role === 'editor' || role === 'owner'
  const canStatus = t ? canSetTaskStatus(t, user, role) : false
  const pending = !!t && ['backlog', 'in_progress'].includes(t.status)

  async function refresh() {
    await qc.invalidateQueries({ queryKey: ['task', t?.id] })
    await qc.invalidateQueries({ queryKey: ['requirement-tasks', t?.requirement_id] })
    await qc.invalidateQueries({ queryKey: ['tasks', projectId] })
    await qc.invalidateQueries({ queryKey: ['activity', 'task', t?.id] })
  }

  async function act(path: string, body?: unknown) {
    if (!t) return
    setError(null)
    try {
      await api.post(path, body)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败')
    }
  }

  async function setStatus(status: string) {
    if (!t || status === t.status) return
    await act(`/tasks/${t.id}/status`, { status })
  }

  async function patch(body: unknown, failMessage: string) {
    if (!t) return
    setError(null)
    try {
      await api.patch(`/tasks/${t.id}`, body)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : failMessage)
    }
  }

  async function assign(assigneeId: string) {
    if (!t) return
    setError(null)
    try {
      await api.post(`/tasks/${t.id}/assign`, { assignee_id: assigneeId })
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '指派失败')
    }
  }

  if (!t) return null

  const blockers = t.blocked_by ?? []
  const candidateBlockers = (projectTasks?.items ?? []).filter(
    (x) => x.id !== t.id && !blockers.some((b) => b.id === x.id),
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 pr-8">
            <span className="truncate">{t.title}</span>
            <StatusBadge status={t.status} />
          </DialogTitle>
          <DialogDescription className="sr-only">任务详情</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {t.description && <p className="text-sm text-muted-foreground">{t.description}</p>}

          {t.blocked && (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge variant="destructive">受阻</Badge>
              <span className="text-muted-foreground">前置任务未全部完成</span>
              {blockers
                .filter((b) => !b.resolved)
                .map((b) => (
                  <span key={b.id} className="text-xs text-muted-foreground">
                    {b.title}
                  </span>
                ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <StatusSelect
              value={t.status}
              statuses={TASK_STATUSES}
              onSelect={(s) => void setStatus(s)}
              disabled={!canStatus}
            />
            <WatchButton targetType="task" targetId={t.id} />
            {t.assignee ? (
              <Badge variant="outline" className="gap-1.5">
                <UserAvatar
                  user={{ id: t.assignee_id ?? '', username: t.assignee, avatar: t.assignee_avatar }}
                  className="h-4 w-4 text-[9px]"
                />
                {t.assignee}
              </Badge>
            ) : (
              pending && canEditTask && (
                <Button variant="outline" size="sm" onClick={() => void act(`/tasks/${t.id}/claim`)}>
                  <UserPlus className="mr-1 h-3.5 w-3.5" />
                  认领
                </Button>
              )
            )}
            {canEditTask && (
              <Select onValueChange={(v) => void assign(v)}>
                <SelectTrigger aria-label="指派给" className="h-8">
                  <SelectValue placeholder="指派给…" />
                </SelectTrigger>
                <SelectContent>
                  {members.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.nickname || m.username}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {t.assignee_id && canManage && (
              <Button variant="outline" size="sm" onClick={() => void act(`/tasks/${t.id}/unassign`)}>
                <UserX className="mr-1 h-3.5 w-3.5" />
                解除指派
              </Button>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {canStatus && (
              <Select
                value={t.requirement_id ?? undefined}
                onValueChange={(v) => void patch({ requirement_id: v }, '改指向失败')}
              >
                <SelectTrigger aria-label="改指向需求" className="h-8 min-w-40">
                  <SelectValue placeholder="选择需求" />
                </SelectTrigger>
                <SelectContent>
                  {(requirements?.items ?? [])
                    .filter((r) => r.status !== 'pending')
                    .map((r) => (
                      <SelectItem key={r.id} value={r.id}>
                        {r.title}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">阻塞依赖(前置任务)</p>
            {blockers.length === 0 && <p className="text-xs text-muted-foreground">无前置任务</p>}
            {blockers.map((b) => (
              <div
                key={b.id}
                className="flex items-center justify-between gap-2 rounded-lg border px-2 py-1 text-xs"
              >
                <span className="truncate">
                  {b.title}
                  {b.resolved ? '（已完成）' : ''}
                </span>
                {canStatus && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`移除前置 ${b.title}`}
                    onClick={() =>
                      void patch(
                        { blocked_by: blockers.filter((x) => x.id !== b.id).map((x) => x.id) },
                        '移除前置失败',
                      )
                    }
                  >
                    <X className="h-3 w-3" />
                  </Button>
                )}
              </div>
            ))}
            {canStatus && candidateBlockers.length > 0 && (
              <Select
                value=""
                onValueChange={(v) =>
                  void patch(
                    { blocked_by: [...blockers.map((x) => x.id), v] },
                    '添加前置失败',
                  )
                }
              >
                <SelectTrigger aria-label="添加前置任务" className="h-8">
                  <SelectValue placeholder="添加前置任务…" />
                </SelectTrigger>
                <SelectContent>
                  {candidateBlockers.map((x) => (
                    <SelectItem key={x.id} value={x.id}>
                      {x.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <ErrorNotification message={error} />

          <div className="max-h-56 overflow-y-auto rounded-lg border p-2">
            <ActivityStream targetType="task" targetId={t.id} />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
