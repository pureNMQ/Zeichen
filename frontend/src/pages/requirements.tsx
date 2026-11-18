import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ParticipantAvatars } from '@/components/participant-avatars'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, LayoutGrid, List, Plus } from 'lucide-react'

import { Kanban } from '@/components/kanban'
import { WorkTrash } from '@/components/work-trash'
import { StatusSelect } from '@/components/status-select'
import { StatusFilterPopover } from '@/components/status-filter-popover'
import { FilterViewSwitcher, type ViewDef } from '@/components/filter-view-switcher'
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
import { MarkdownComposer } from '@/components/markdown-composer'
import { useProjectCompletion } from '@/lib/project-completion'
import { projectFileUpload } from '@/lib/project-files'
import { ErrorNotification } from '@/components/ui/notification'
import {
  api,
  ApiError,
  REQUIREMENT_STATUSES,
  withProject,
  type FilterCriteria,
  type FilterViewMode,
  type Page,
  type RequirementRow,
  type RequirementStatus,
} from '@/lib/api'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'
import { projectResourceHref } from '@/lib/project-links'

const TIME_WINDOWS = [
  { value: '', label: '不限' },
  { value: '3', label: '近 3 天' },
  { value: '7', label: '近 7 天' },
  { value: '30', label: '近 30 天' },
]

export async function moveRequirement(id: string, to: RequirementStatus, projectId?: string | null): Promise<void> {
  await api.post(withProject(`/requirements/${id}/status`, projectId), { status: to })
}

function RequirementCard({
  r,
  canEdit,
  onStatus,
  onDelete,
  canDelete,
  onReject,
}: {
  r: RequirementRow
  canEdit: boolean
  onStatus: (r: RequirementRow, s: string) => void
  onDelete: (r: RequirementRow) => void
  canDelete: boolean
  onReject?: (r: RequirementRow) => void
}) {
  const { routeProjectId } = useCurrentProject()
  const projectId = routeProjectId ?? r.project_id
  const href = projectId
    ? projectResourceHref(projectId, 'requirements', r.id)
    : `/requirements/${r.id}`
  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <Link to={href} className="block text-sm font-medium hover:text-primary">
          <span className="mr-1.5 rounded bg-muted px-1 py-0.5 font-mono text-[10px] text-muted-foreground">{r.id}</span>
          {r.title}
        </Link>
        <div className="flex items-center gap-2">
          <StatusSelect
            value={r.status}
            statuses={REQUIREMENT_STATUSES}
            onSelect={(s) => onStatus(r, s)}
            disabled={!canEdit}
          />
          <Badge variant="outline" title="已完成任务数/总任务数">
            {r.done_task_count ?? 0}/{r.task_count} 任务
          </Badge>
        </div>
        {r.blocked && <p className="text-xs text-muted-foreground">等待前置需求</p>}
        <ParticipantAvatars participants={r.participants} />
        {(canDelete || (canEdit && onReject && r.status === 'verifying')) && (
          <div className="flex items-center gap-1">
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
            {canEdit && onReject && r.status === 'verifying' && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-xs text-destructive"
                onClick={() => onReject(r)}
              >
                打回
              </Button>
            )}
          </div>
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

type BoardSettings = {
  statuses: string[]; days: string; keyword: string; view: FilterViewMode; activeView: string; mine: boolean
}
export function RequirementsPage() {
  const { projectId } = useCurrentProject()
  return <RequirementBoard key={projectId} />
}
function RequirementBoard() {
  const { projectId, currentProject, isLoading: cpLoading } = useCurrentProject()
  const qc = useQueryClient()
  const role = useProjectRole()
  const canEdit = role === 'editor' || role === 'owner'

  const cacheKey = ['requirement-board-settings', projectId]
  const initial = qc.getQueryData<BoardSettings>(cacheKey)
  const [statuses, setStatuses] = useState<string[]>(initial?.statuses ?? [])
  const [updatedWithinDays, setUpdatedWithinDays] = useState(initial?.days ?? '3')
  const [keywordInput, setKeywordInput] = useState(initial?.keyword ?? '')
  const [keyword, setKeyword] = useState(initial?.keyword ?? '')
  const [viewMode, setViewMode] = useState<FilterViewMode>(initial?.view ?? 'board')
  const [activeViewId, setActiveViewId] = useState(initial?.activeView ?? 'recent')
  const [mine, setMine] = useState(initial?.mine ?? false)
  const navigate = useNavigate()
  const board = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (projectId) qc.setQueryData(['requirement-board-settings', projectId], {
      statuses, days: updatedWithinDays, keyword, view: viewMode, activeView:activeViewId, mine,
    })
  }, [qc, projectId, statuses, updatedWithinDays, keyword, viewMode, activeViewId, mine])
  const [deleteTarget, setDeleteTarget] = useState<RequirementRow | null>(null)
  const [confirmCount, setConfirmCount] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const [rejectTarget, setRejectTarget] = useState<RequirementRow | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [rejectUploading, setRejectUploading] = useState(false)
  const rejectLookup = useProjectCompletion(rejectTarget?.project_id ?? null)
  const reasonTooLong = Array.from(rejectReason.trim()).length > 2000
  const [rejectError, setRejectError] = useState<string | null>(null)
  const [rejecting, setRejecting] = useState(false)
  const rejectAttempt = useRef<{ reason: string; id: string } | null>(null)

  const keywordTimer = useRef<number | null>(null)

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
    setMine(c.participated_by_me ?? false)
    setStatuses(c.statuses ?? [])
    setUpdatedWithinDays(c.updated_within_days != null ? String(c.updated_within_days) : '')
    const kw = c.keyword ?? ''
    setKeywordInput(kw)
    setKeyword(kw)
    setViewMode(def.view_mode)
    setActiveViewId(def.id)
  }

  const criteria: FilterCriteria = {
    view_mode: viewMode,
    ...(mine ? { participated_by_me: true } : {}),
    ...(statuses.length > 0 ? { statuses: [...statuses] } : {}),
    ...(updatedWithinDays !== '' ? { updated_within_days: Number(updatedWithinDays) } : {}),
    ...(keyword.trim() !== '' ? { keyword: keyword.trim() } : {}),
  }

  const {
    data: pageData,
    isLoading,
    error,
    refetch,
    isFetchNextPageError,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['requirements', projectId, { statuses, updatedWithinDays, keyword, mine }],
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams()
      if (mine) params.set('participated_by_me', 'true')
      for (const s of statuses) params.append('status', s)
      if (updatedWithinDays !== '') params.set('updated_within_days', updatedWithinDays)
      const kw = keyword.trim()
      if (kw !== '') params.set('keyword', kw)
      params.set('limit', '20')
      if (pageParam != null && pageParam !== '') params.set('cursor', String(pageParam))
      return api.get<Page<RequirementRow>>(
        `/projects/${projectId}/requirements?${params.toString()}`,
      )
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    enabled: !!projectId,
  })

  const items = (pageData?.pages ?? []).flatMap((p) => p.items)
  const boardItems = items

  useEffect(() => {
    const container = board.current?.closest('main')
    if (!container || !projectId || isLoading) return
    const key = ['requirement-board-scroll', projectId]
    const columns = board.current?.querySelector<HTMLElement>('[data-kanban-scroll]')
    const saved = qc.getQueryData<{top:number;left:number}>(key)
    if (saved) {
      container.scrollTop = saved.top
      if (columns) columns.scrollLeft = saved.left
    }
    const remember = () => qc.setQueryData(key, {top:container.scrollTop, left:columns?.scrollLeft ?? 0})
    container.addEventListener('scroll', remember)
    columns?.addEventListener('scroll', remember)
    return () => {
      container.removeEventListener('scroll', remember)
      columns?.removeEventListener('scroll', remember)
    }
  }, [isLoading, projectId, qc, viewMode])

  async function doMove(id: string, to: RequirementStatus) {
    setActionError(null)
    try {
      await moveRequirement(id, to, projectId)
      await qc.invalidateQueries({ queryKey: ['requirements', projectId] })
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '状态变更失败')
      await qc.invalidateQueries({ queryKey: ['requirements', projectId] })
    }
  }

  function onCardStatus(r: RequirementRow, s: string) {
    if (s === r.status) return
    void doMove(r.id, s as RequirementStatus)
  }

  async function doDelete() {
    if (!deleteTarget) return
    try {
      setActionError(null)
      await api.post(withProject(`/requirements/${deleteTarget.id}/delete`, projectId), {
        confirm_task_count: Number(confirmCount),
      })
      setDeleteTarget(null)
      setConfirmCount('')
      await qc.invalidateQueries({ queryKey: ['requirements', projectId] })
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  function openReject(r: RequirementRow) {
    rejectAttempt.current = null
    setRejectUploading(false)
    setRejectTarget(r)
    setRejectReason('')
    setRejectError(null)
  }

  async function doReject() {
    if (!rejectTarget || rejecting || rejectUploading) return
    const reason = rejectReason.trim()
    if (!reason || reasonTooLong) return
    setRejecting(true)
    setRejectError(null)
    try {
      const previous = rejectAttempt.current
      const requestId = previous?.reason === reason ? previous.id : crypto.randomUUID()
      rejectAttempt.current = { reason, id: requestId }
      const scope = rejectTarget.project_id
      await api.post(`/projects/${scope}/requirements/${rejectTarget.id}/reject`, { reason, request_id: requestId })
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['requirements', scope] }),
        qc.invalidateQueries({ queryKey: ['requirement', rejectTarget.id, scope] }),
        qc.invalidateQueries({ queryKey: ['requirement-timeline', scope, rejectTarget.id] }),
      ])
      setRejectTarget(null)
      setRejectReason('')
    } catch (err) {
      setRejectError(err instanceof ApiError ? err.message : '打回未确认，请重试')
    } finally {
      setRejecting(false)
    }
  }

  if (cpLoading) return <p className="text-sm text-muted-foreground">加载中…</p>
  if (!currentProject) return <NoProjectGuide />

  return (
    <div ref={board} className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">需求</h1>
          <p className="text-sm text-muted-foreground">
            当前项目:{currentProject.name}
          </p>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <FilterViewSwitcher
            projectId={projectId ?? ''}
            entityType="requirement"
            activeViewId={activeViewId}
            onSelectView={applyView}
            currentCriteria={criteria}
          />
          {canEdit && projectId && <WorkTrash key={projectId} projectId={projectId} />}
          {canEdit && (
            <Button onClick={() => navigate(`/projects/${projectId}/requirements/new`)}>
              <Plus className="mr-2 h-4 w-4" />
              新建需求
            </Button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant={mine ? 'default' : 'outline'} aria-pressed={mine} onClick={() => setMine(!mine)}>我参与的</Button>
        <StatusFilterPopover statuses={REQUIREMENT_STATUSES} value={statuses} onChange={setStatuses} />
        <select
          aria-label="时间窗口"
          autoComplete="off"
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
        <div className="w-48">
          <Label htmlFor="requirement-keyword" className="sr-only">
            关键词
          </Label>
          <Input
            id="requirement-keyword"
            value={keywordInput}
            onChange={(e) => handleKeywordChange(e.target.value)}
            autoComplete="off"
            placeholder="关键词"
          />
        </div>
        <div className="flex overflow-hidden rounded-md border">
          <Button
            variant={viewMode === 'list' ? 'secondary' : 'ghost'}
            size="sm"
            className="rounded-none"
            onClick={() => setViewMode('list')}
          >
            <List className="h-4 w-4" />
            列表
          </Button>
          <Button
            variant={viewMode === 'board' ? 'secondary' : 'ghost'}
            size="sm"
            className="rounded-none"
            onClick={() => setViewMode('board')}
          >
            <LayoutGrid className="h-4 w-4" />
            看板
          </Button>
        </div>
      </div>

      {isLoading && <p role="status" className="text-sm text-muted-foreground">加载需求…</p>}
      <ErrorNotification message={error ? (error as Error).message : null} />
      <ErrorNotification message={actionError} />
      {error && !isFetchNextPageError && <Button variant="outline" className="self-start" onClick={() => void refetch()}>重试加载</Button>}
      {!isLoading && !error && items.length === 0 && (
        <div className="flex flex-wrap items-center gap-2 py-4 text-sm text-muted-foreground">
          <p>{mine || statuses.length || updatedWithinDays || keyword.trim() ? '没有符合筛选条件的需求' : '暂无需求'}</p>
          {(mine || statuses.length > 0 || updatedWithinDays || keyword.trim()) && (
            <Button size="sm" variant="ghost" onClick={() => applyView({ id: 'all', name: '全部', criteria: {}, view_mode: viewMode })}>
              清除筛选
            </Button>
          )}
        </div>
      )}

      {items.length > 0 && (viewMode === 'board' ? (
        <Kanban
          className="flex-1"
          items={boardItems}
          canDrag={canEdit}
          onMove={(id, to) => doMove(id, to as RequirementStatus)}
          columns={REQUIREMENT_STATUSES}
          renderCard={(r) => (
            <RequirementCard
              r={r}
              canEdit={canEdit}
              onStatus={onCardStatus}
              onDelete={setDeleteTarget}
              canDelete={canEdit}
              onReject={openReject}
            />
          )}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((r) => (
            <RequirementCard
              key={r.id}
              r={r}
              canEdit={canEdit}
              onStatus={onCardStatus}
              onDelete={setDeleteTarget}
              canDelete={canEdit}
            />
          ))}
        </div>
      ))}

      {hasNextPage && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            onClick={() => void fetchNextPage()}
            disabled={isFetchingNextPage}
          >
            {isFetchingNextPage ? '加载中…' : isFetchNextPageError ? '重试下一页' : '加载更多'}
          </Button>
        </div>
      )}


      <Dialog open={rejectTarget !== null} onOpenChange={(v) => !v && !rejecting && setRejectTarget(null)}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>打回需求</DialogTitle>
            <DialogDescription>
              确认后，「{rejectTarget?.title}」将回到待办，打回理由会记入需求时间轴。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <div className="text-sm font-medium">打回理由</div>
            <MarkdownComposer id="reject-reason" label="打回理由" value={rejectReason}
              onChange={setRejectReason} lookup={rejectLookup} disabled={rejecting}
              upload={rejectTarget ? projectFileUpload(rejectTarget.project_id) : undefined} onUploadPending={setRejectUploading}
              className="[--writing-height:7rem]" />
            {reasonTooLong && <p role="alert" className="text-sm text-destructive">打回理由最多可保存 2000 个字符，含 Markdown 标记。</p>}
            {rejectError && <p className="text-sm text-destructive">{rejectError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" disabled={rejecting} onClick={() => setRejectTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={() => void doReject()}
              disabled={rejecting || rejectUploading || reasonTooLong || rejectReason.trim() === ''}
            >
              {rejecting ? '提交中…' : '确认打回'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
            autoComplete="off"
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
