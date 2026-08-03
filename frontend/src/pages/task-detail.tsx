import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, UserPlus, UserX } from 'lucide-react'

import { ActivityStream } from '@/components/activity-stream'
import { CommentStream } from '@/components/comment-stream'
import { StatusBadge } from '@/components/status-badge'
import { StatusSelect } from '@/components/status-select'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { api, ApiError, TASK_STATUSES, type RequirementRow, type TaskRow } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'
import { canSetTaskStatus } from '@/lib/task-perms'

function Guide({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-muted-foreground">
      <FolderOpen className="h-10 w-10" />
      {children}
    </div>
  )
}

export function TaskDetailPage() {
  const { id = '' } = useParams()
  const { user } = useAuth()
  const qc = useQueryClient()
  const role = useProjectRole()
  const { currentProject, isLoading: cpLoading, selectProject } = useCurrentProject()
  const [error, setError] = useState<string | null>(null)

  const { data: task, isLoading, error: loadError } = useQuery({
    queryKey: ['task', id],
    queryFn: () => api.get<TaskRow>(`/tasks/${id}`),
  })
  const { data: requirements } = useQuery({
    queryKey: ['requirements', task?.project_id],
    queryFn: () =>
      api.get<{ items: RequirementRow[]; next_cursor: string | null }>(
        `/projects/${task?.project_id}/requirements?limit=100`,
      ),
    enabled: !!task,
  })

  const isAdmin = user?.workspace_role === 'admin'
  const isAssignee = task?.assignee_id === user?.id
  const isOwner = role === 'owner'
  const canManage = isAdmin || isOwner || isAssignee
  const canEditTask = role === 'editor' || role === 'owner'
  // 已指派仅本人/admin/owner;未指派任意编辑权者可改状态
  const canSetStatus = task ? canSetTaskStatus(task, user, role) : false

  async function act(path: string, body?: unknown) {
    setError(null)
    try {
      await api.post(path, body)
      await qc.invalidateQueries({ queryKey: ['task', id] })
      await qc.invalidateQueries({ queryKey: ['activity', 'task', id] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败')
    }
  }

  async function setStatus(status: string) {
    if (status === task?.status) return
    await act(`/tasks/${id}/status`, { status })
  }

  async function setRequirement(requirementId: string | null) {
    if (requirementId === (task?.requirement_id ?? null)) return
    setError(null)
    try {
      await api.patch(`/tasks/${id}`, { requirement_id: requirementId })
      await qc.invalidateQueries({ queryKey: ['task', id] })
      await qc.invalidateQueries({ queryKey: ['tasks', task?.project_id] })
      await qc.invalidateQueries({ queryKey: ['requirement-tasks', task?.requirement_id] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '关联失败')
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
  if (loadError || !task) return <p className="text-sm text-destructive">{(loadError as Error)?.message ?? '任务不存在'}</p>
  if (task.project_id !== currentProject.id) {
    return (
      <Guide>
        <p className="text-sm">该任务不属于当前项目「{currentProject.name}」</p>
        <Button onClick={() => selectProject(task.project_id)}>切换到该项目</Button>
      </Guide>
    )
  }

  const pending = ['backlog', 'in_progress', 'verifying'].includes(task.status)

  return (
    <div className="space-y-4">
      <Link to="/tasks" className="text-sm text-muted-foreground hover:text-primary">
        ← 返回看板
      </Link>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">{task.title}</h1>
            <StatusBadge status={task.status} />
          </div>
          {task.requirement_id && (
            <Link to={`/requirements/${task.requirement_id}`} className="text-xs text-muted-foreground hover:text-primary">
              所属需求:{task.requirement_id.slice(0, 8)}
            </Link>
          )}
          {task.description && <p className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{task.description}</p>}
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          {!task.assignee_id && pending && canEditTask && (
            <Button onClick={() => void act('/tasks/' + id + '/claim')}>
              <UserPlus className="mr-2 h-4 w-4" />
              认领
            </Button>
          )}
          <StatusSelect
            value={task.status}
            statuses={TASK_STATUSES}
            onSelect={(s) => void setStatus(s)}
            disabled={!canSetStatus}
          />
          {canSetStatus && (
            <Select
              value={task.requirement_id ?? 'none'}
              onValueChange={(v) => void setRequirement(v === 'none' ? null : v)}
            >
              <SelectTrigger size="sm" aria-label="关联需求" className="h-6 gap-1 px-1.5 text-xs">
                <SelectValue placeholder="关联需求" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">独立任务(不关联)</SelectItem>
                {(requirements?.items ?? []).map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {r.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {task.assignee_id && canManage && (
            <Button variant="outline" onClick={() => void act('/tasks/' + id + '/unassign')}>
              <UserX className="mr-2 h-4 w-4" />
              解除指派
            </Button>
          )}
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}

      <Card>
        <CardContent className="space-y-6 p-4">
          <CommentStream targetType="task" targetId={task.id} canEdit={pending} />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-4">
          <ActivityStream targetType="task" targetId={task.id} />
        </CardContent>
      </Card>
    </div>
  )
}
