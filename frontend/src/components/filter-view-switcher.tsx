import { useEffect, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { MoreHorizontal, Save } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import {
  api,
  ApiError,
  type FilterCriteria,
  type FilterViewMode,
  type FilterViewRow,
} from '@/lib/api'

export interface ViewDef {
  id: string
  name: string
  criteria: FilterCriteria
  view_mode: FilterViewMode
}

/** 内置视图:全部 = 无条件列表;近期活跃 = 近 3 天看板(不落库) */
const ALL_VIEW: ViewDef = { id: 'all', name: '全部', criteria: {}, view_mode: 'list' }
const RECENT_VIEW: ViewDef = {
  id: 'recent',
  name: '近期活跃',
  criteria: { updated_within_days: 3 },
  view_mode: 'board',
}

interface FilterViewSwitcherProps {
  projectId: string
  entityType: 'requirement' | 'task'
  activeViewId: string
  onSelectView: (def: ViewDef) => void
  currentCriteria: FilterCriteria
}

export function FilterViewSwitcher({
  projectId,
  entityType,
  activeViewId,
  onSelectView,
  currentCriteria,
}: FilterViewSwitcherProps) {
  const qc = useQueryClient()
  const [saveOpen, setSaveOpen] = useState(false)
  const [editView, setEditView] = useState<FilterViewRow | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<FilterViewRow | null>(null)
  const [name, setName] = useState('')
  const [opError, setOpError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const { data, error: viewsError } = useQuery({
    queryKey: ['filter-views', projectId, entityType],
    queryFn: () =>
      api.get<{ items: FilterViewRow[] }>(
        `/projects/${projectId}/filter-views?entity_type=${entityType}`,
      ),
    enabled: !!projectId,
  })

  const views = data?.items ?? []

  useEffect(() => {
    if (saveOpen) {
      setName('')
      setOpError(null)
    }
  }, [saveOpen])

  useEffect(() => {
    if (editView) {
      setName(editView.name)
      setOpError(null)
    }
  }, [editView])

  function invalidateViews() {
    void qc.invalidateQueries({ queryKey: ['filter-views', projectId, entityType] })
  }

  async function doSave(e: FormEvent) {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    setSubmitting(true)
    setOpError(null)
    try {
      if (editView) {
        await api.patch(`/filter-views/${editView.id}`, { name: trimmed })
        setEditView(null)
      } else {
        await api.post(`/projects/${projectId}/filter-views`, {
          entity_type: entityType,
          name: trimmed,
          criteria: currentCriteria,
        })
        setSaveOpen(false)
      }
      invalidateViews()
    } catch (err) {
      setOpError(err instanceof ApiError ? err.message : '视图保存失败')
    } finally {
      setSubmitting(false)
    }
  }

  async function doDelete() {
    if (!deleteTarget) return
    setOpError(null)
    try {
      await api.delete(`/filter-views/${deleteTarget.id}`)
      if (activeViewId === deleteTarget.id) onSelectView(ALL_VIEW)
      setDeleteTarget(null)
      invalidateViews()
    } catch (err) {
      setOpError(err instanceof ApiError ? err.message : '视图删除失败')
    }
  }

  const viewById = new Map(views.map((v) => [v.id, v]))
  const defs: ViewDef[] = [
    ALL_VIEW,
    RECENT_VIEW,
    ...views.map((v) => ({
      id: v.id,
      name: v.name,
      criteria: v.criteria ?? {},
      view_mode: (v.criteria?.view_mode ?? 'list') as FilterViewMode,
    })),
  ]

  return (
    <>
      <div className="flex items-center gap-1.5">
        <div className="flex overflow-hidden rounded-md border">
          {defs.map((def) => {
            const isActive = activeViewId === def.id
            const isCustom = def.id !== 'all' && def.id !== 'recent'
            return (
              <div key={def.id} className="flex items-center">
                <Button
                  variant={isActive ? 'secondary' : 'ghost'}
                  size="sm"
                  className="rounded-none"
                  onClick={() => onSelectView(def)}
                >
                  {def.name}
                </Button>
                {isCustom && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant={isActive ? 'secondary' : 'ghost'}
                        size="sm"
                        className="rounded-none px-1.5"
                        aria-label="视图操作"
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        onSelect={() => setEditView(viewById.get(def.id) ?? null)}
                      >
                        修改
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        variant="destructive"
                        onSelect={() => setDeleteTarget(viewById.get(def.id) ?? null)}
                      >
                        删除
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </div>
            )
          })}
        </div>
        <Button variant="outline" size="sm" onClick={() => setSaveOpen(true)}>
          <Save className="h-3.5 w-3.5" />
          另存为
        </Button>
      </div>

      <ErrorNotification message={viewsError ? (viewsError as Error).message : null} />
      <ErrorNotification message={opError} />

      <Dialog
        open={saveOpen || editView !== null}
        onOpenChange={(v) => {
          if (!v) {
            setSaveOpen(false)
            setEditView(null)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editView ? '修改视图' : '另存为视图'}</DialogTitle>
            <DialogDescription>
              {editView ? '修改个人视图的名称。' : '将当前筛选条件与展示模式保存为个人视图。'}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={(e) => void doSave(e)} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="view-name">名称</Label>
              <Input
                id="view-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="off"
                maxLength={50}
                required
              />
            </div>
            <DialogFooter>
              <Button type="submit" disabled={submitting}>
                {submitting ? '保存中…' : '保存'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(v) => {
          if (!v) setDeleteTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除视图</DialogTitle>
            <DialogDescription>
              确认删除该视图「{deleteTarget?.name}」?删除后不可恢复。
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
    </>
  )
}
