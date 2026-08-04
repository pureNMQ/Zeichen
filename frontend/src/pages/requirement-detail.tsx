import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, Link2, Plus } from 'lucide-react'

import { ActivityStream } from '@/components/activity-stream'
import { CommentStream } from '@/components/comment-stream'
import { CreateTaskDialog } from '@/components/create-task-dialog'
import { StatusBadge } from '@/components/status-badge'
import { StatusSelect } from '@/components/status-select'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
  type ReferenceRow,
  type RequirementRow,
  type TaskRow,
} from '@/lib/api'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'

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
  const qc = useQueryClient()
  const role = useProjectRole()
  const { currentProject, isLoading: cpLoading, selectProject } = useCurrentProject()
  const canEdit = role === 'editor' || role === 'owner'
  const [actionError, setActionError] = useState<string | null>(null)
  const [linkOpen, setLinkOpen] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [linkError, setLinkError] = useState<string | null>(null)

  const { data: req, isLoading, error } = useQuery({
    queryKey: ['requirement', id],
    queryFn: () => api.get<RequirementRow>(`/requirements/${id}`),
  })
  const { data: tasks } = useQuery({
    queryKey: ['requirement-tasks', id],
    queryFn: () => api.get<{ items: TaskRow[] }>(`/projects/${req?.project_id}/tasks?requirement_id=${id}&limit=100`),
    enabled: !!req,
  })
  const { data: allTasks } = useQuery({
    queryKey: ['tasks', req?.project_id],
    queryFn: () => api.get<{ items: TaskRow[]; next_cursor: string | null }>(`/projects/${req?.project_id}/tasks?limit=100`),
    enabled: !!req,
  })
  const { data: refs } = useQuery({
    queryKey: ['refs', 'requirement', id],
    queryFn: () => api.get<{ items: ReferenceRow[] }>(`/targets/requirement/${id}/references?limit=50`),
    enabled: !!req,
  })

  async function act(path: string, body?: unknown) {
    setActionError(null)
    try {
      await api.post(path, body)
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

  async function linkTask(task: TaskRow) {
    setLinkError(null)
    try {
      await api.patch(`/tasks/${task.id}`, { requirement_id: req?.id })
      setLinkOpen(false)
      await qc.invalidateQueries({ queryKey: ['tasks', req?.project_id] })
      await qc.invalidateQueries({ queryKey: ['requirement-tasks', id] })
    } catch (err) {
      setLinkError(err instanceof ApiError ? err.message : '关联失败')
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
  if (error || !req) return <ErrorNotification message={(error as Error)?.message ?? '需求不存在'} />
  if (req.project_id !== currentProject.id) {
    return (
      <Guide>
        <p className="text-sm">该需求不属于当前项目「{currentProject.name}」</p>
        <Button onClick={() => selectProject(req.project_id)}>切换到该项目</Button>
      </Guide>
    )
  }

  return (
    <div className="space-y-4">
      <Link to="/requirements" className="text-sm text-muted-foreground hover:text-primary">
        ← 返回需求
      </Link>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">{req.title}</h1>
            <StatusBadge status={req.status} />
          </div>
          {req.description && <p className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{req.description}</p>}
        </div>
        <div className="flex shrink-0 gap-2">
          <StatusSelect
            value={req.status}
            statuses={REQUIREMENT_STATUSES}
            onSelect={(s) => void setStatus(s)}
            disabled={!canEdit}
          />
        </div>
      </div>
      <ErrorNotification message={actionError} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between gap-2">
            <CardTitle className="text-sm">关联任务</CardTitle>
            {canEdit && (
              <div className="flex gap-2">
                <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setLinkOpen(true)}>
                  <Link2 className="mr-1 h-3 w-3" />
                  关联任务
                </Button>
                <Button size="sm" className="h-7 text-xs" onClick={() => setCreateOpen(true)}>
                  <Plus className="mr-1 h-3 w-3" />
                  新建任务
                </Button>
              </div>
            )}
          </CardHeader>
          <CardContent className="space-y-2">
            {(tasks?.items ?? []).length === 0 && <p className="text-sm text-muted-foreground">暂无任务</p>}
            {tasks?.items.map((t) => (
              <Link key={t.id} to={`/tasks/${t.id}`} className="flex items-center justify-between rounded-md border p-2.5 text-sm hover:bg-muted/40">
                <span>{t.title}</span>
                <span className="flex items-center gap-2">
                  {t.assignee && <Badge variant="outline">{t.assignee}</Badge>}
                  <StatusBadge status={t.status} />
                </span>
              </Link>
            ))}
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
                  {r.from_type}:{r.from_id.slice(0, 8)} → {r.to_type}:{r.to_id.slice(0, 8)}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="space-y-6 p-4">
          <CommentStream targetType="requirement" targetId={req.id} canEdit={req.status !== 'cancelled'} />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-4">
          <ActivityStream targetType="requirement" targetId={req.id} />
        </CardContent>
      </Card>

      <Dialog open={linkOpen} onOpenChange={setLinkOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>关联任务</DialogTitle>
            <DialogDescription>选择当前项目中未挂需求的任务,挂到本需求下。</DialogDescription>
          </DialogHeader>
          <div className="max-h-72 space-y-2 overflow-y-auto">
            {(allTasks?.items ?? []).filter((t) => !t.requirement_id).length === 0 && (
              <p className="text-sm text-muted-foreground">暂无未关联需求的任务</p>
            )}
            {(allTasks?.items ?? [])
              .filter((t) => !t.requirement_id)
              .map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => void linkTask(t)}
                  className="flex w-full items-center justify-between rounded-md border p-2.5 text-left text-sm hover:bg-muted/40"
                >
                  <span>{t.title}</span>
                  <span className="flex items-center gap-2">
                    {t.assignee && <Badge variant="outline">{t.assignee}</Badge>}
                    <StatusBadge status={t.status} />
                  </span>
                </button>
              ))}
          </div>
          <ErrorNotification message={linkError} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setLinkOpen(false)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <CreateTaskDialog open={createOpen} onOpenChange={setCreateOpen} presetRequirementId={req.id} onCreated={() => qc.invalidateQueries({ queryKey: ['requirement-tasks', id] })} />
    </div>
  )
}
