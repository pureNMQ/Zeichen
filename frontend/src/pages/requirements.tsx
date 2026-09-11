import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, LayoutGrid, List, Plus } from 'lucide-react'

import { Kanban } from '@/components/kanban'
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
import { ErrorNotification } from '@/components/ui/notification'
import {
  api,
  ApiError,
  REQUIREMENT_STATUSES,
  type FilterCriteria,
  type FilterViewMode,
  type Page,
  type RequirementRow,
  type RequirementStatus,
} from '@/lib/api'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'
import { clearDraft, readDraft, writeDraft } from '@/lib/form-draft'

const TIME_WINDOWS = [
  { value: '', label: '不限' },
  { value: '3', label: '近 3 天' },
  { value: '7', label: '近 7 天' },
  { value: '30', label: '近 30 天' },
]

export async function moveRequirement(id: string, to: RequirementStatus): Promise<void> {
  await api.post(`/requirements/${id}/status`, { status: to })
}

function RequirementCard({
  r,
  canEdit,
  onStatus,
  onDelete,
  canDelete,
}: {
  r: RequirementRow
  canEdit: boolean
  onStatus: (r: RequirementRow, s: string) => void
  onDelete: (r: RequirementRow) => void
  canDelete: boolean
}) {
  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <Link to={`/requirements/${r.id}`} className="block text-sm font-medium hover:text-primary">
          {r.title}
        </Link>
        <div className="flex items-center gap-2">
          <StatusSelect
            value={r.status}
            statuses={REQUIREMENT_STATUSES}
            onSelect={(s) => onStatus(r, s)}
            disabled={!canEdit}
          />
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

  // 筛选条件(服务端下推)与视图状态
  const [statuses, setStatuses] = useState<string[]>([])
  const [updatedWithinDays, setUpdatedWithinDays] = useState('3')
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [viewMode, setViewMode] = useState<FilterViewMode>('board')
  const [activeViewId, setActiveViewId] = useState('recent')

  const [createOpen, setCreateOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<RequirementRow | null>(null)
  const [confirmCount, setConfirmCount] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

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
    ...(statuses.length > 0 ? { statuses: [...statuses] } : {}),
    ...(updatedWithinDays !== '' ? { updated_within_days: Number(updatedWithinDays) } : {}),
    ...(keyword.trim() !== '' ? { keyword: keyword.trim() } : {}),
  }

  const {
    data: pageData,
    isLoading,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['requirements', projectId, { statuses, updatedWithinDays, keyword }],
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams()
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

  async function doMove(id: string, to: RequirementStatus) {
    setActionError(null)
    try {
      await moveRequirement(id, to)
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
      await api.post(`/requirements/${deleteTarget.id}/delete`, {
        confirm_task_count: Number(confirmCount),
      })
      setDeleteTarget(null)
      setConfirmCount('')
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
          <h1 className="text-xl font-semibold">需求</h1>
          <p className="text-sm text-muted-foreground">
            当前项目:{currentProject.name}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <FilterViewSwitcher
            projectId={projectId ?? ''}
            entityType="requirement"
            activeViewId={activeViewId}
            onSelectView={applyView}
            currentCriteria={criteria}
          />
          {canEdit && (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              新建需求
            </Button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <StatusFilterPopover statuses={REQUIREMENT_STATUSES} value={statuses} onChange={setStatuses} />
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

      {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
      <ErrorNotification message={error ? (error as Error).message : null} />
      <ErrorNotification message={actionError} />
      {!isLoading && items.length === 0 && (
        <p className="py-10 text-center text-sm text-muted-foreground">暂无需求</p>
      )}

      {viewMode === 'board' ? (
        <Kanban
          className="flex-1"
          items={boardItems}
          canDrag={canEdit}
          onMove={(id, to) => void doMove(id, to as RequirementStatus)}
          columns={REQUIREMENT_STATUSES}
          renderCard={(r) => (
            <RequirementCard
              r={r}
              canEdit={canEdit}
              onStatus={onCardStatus}
              onDelete={setDeleteTarget}
              canDelete={canEdit}
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

function CreateRequirementDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { projectId } = useCurrentProject()
  const qc = useQueryClient()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const draftKey = projectId ? `zeichen.draft.requirement:${projectId}` : null

  useEffect(() => {
    if (!open) return
    setError(null)
    const draft = draftKey ? readDraft<{ title: string; description: string }>(draftKey) : null
    setTitle(draft?.title ?? '')
    setDescription(draft?.description ?? '')
  }, [open, draftKey])

  useEffect(() => {
    if (!open || !draftKey) return
    // 全空内容不持久化,并清掉既有草稿
    if (!title && !description) {
      clearDraft(draftKey)
      return
    }
    writeDraft(draftKey, { title, description })
  }, [open, draftKey, title, description])

  function clearFormDraft() {
    if (draftKey) clearDraft(draftKey)
    setTitle('')
    setDescription('')
    setError(null)
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.post(`/projects/${projectId}/requirements`, { title: title.trim(), description: description.trim() || null })
      if (draftKey) clearDraft(draftKey)
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
            <Input id="req-title" value={title} onChange={(e) => setTitle(e.target.value)} autoComplete="off" maxLength={256} required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="req-desc">描述</Label>
            <Input id="req-desc" value={description} onChange={(e) => setDescription(e.target.value)} autoComplete="off" maxLength={512} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={clearFormDraft}>
              清空草稿
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? '创建中…' : '创建'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
