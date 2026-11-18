import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Ellipsis, Plus, FolderOpen, Trash2 } from 'lucide-react'
import { api, ApiError, type ProjectRow } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent } from '@/components/ui/card'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

function CreateProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.post('/projects', { name: name.trim(), description: description.trim() })
      setName('')
      setDescription('')
      onOpenChange(false)
      await qc.invalidateQueries({ queryKey: ['projects'] })
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
          <DialogTitle>新建项目</DialogTitle>
          <DialogDescription>项目成员授权将在项目详情页中配置</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="project-name">项目名称</Label>
            <Input
              id="project-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="off"
              maxLength={128}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-project-description">项目描述（选填）</Label>
            <Textarea id="new-project-description" value={description} onChange={(e) => setDescription(e.target.value)}
              autoComplete="off" maxLength={1000} rows={3} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting || !name.trim()}>
              {submitting ? '创建中…' : '创建'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

type ProjectTrashRow = { id: string; name: string; deleted_at: string; deleted_by: string | null }
type ProjectImpact = {
  affected: Record<'requirements' | 'tasks' | 'wiki' | 'attachments' | 'repositories', number>
}

function ProjectImpactSummary({ impact }: { impact: ProjectImpact }) {
  const { requirements, tasks, wiki, attachments, repositories } = impact.affected
  return (
    <p className="text-sm text-muted-foreground">
      {requirements} 个需求、{tasks} 个任务、{wiki} 篇 Wiki、{attachments} 个附件、{repositories} 条仓库登记
    </p>
  )
}

function ProjectRemovalDialog({ project, onClose }: { project: ProjectRow; onClose: () => void }) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const impact = useQuery({
    queryKey: ['project-delete-impact', project.id],
    queryFn: () => api.get<ProjectImpact>(`/projects/${project.id}/delete-impact`),
  })

  async function remove() {
    setPending(true)
    setError(null)
    try {
      await api.delete(`/projects/${project.id}`)
      await qc.invalidateQueries({ queryKey: ['projects'] })
      await qc.invalidateQueries({ queryKey: ['project-trash'] })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败，请重试')
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !pending) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>删除项目「{project.name}」</DialogTitle>
          <DialogDescription>项目和其中仍有效的内容将暂时隐藏，可从项目回收站恢复。</DialogDescription>
        </DialogHeader>
        {impact.isLoading && <p role="status">正在查询影响范围…</p>}
        {impact.data && <ProjectImpactSummary impact={impact.data} />}
        {impact.isError && <Button variant="outline" onClick={() => void impact.refetch()}>重新查询影响范围</Button>}
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={onClose}>取消</Button>
          <Button variant="destructive" disabled={pending || !impact.data} onClick={() => void remove()}>移入回收站</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ProjectTrash({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState<string | null>(null)
  const [selected, setSelected] = useState<ProjectTrashRow | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const page = useQuery({
    queryKey: ['project-trash', query, cursor],
    queryFn: () => {
      const params = new URLSearchParams({ q: query })
      if (cursor) params.set('cursor', cursor)
      return api.get<{ items: ProjectTrashRow[]; next_cursor: string | null }>(`/projects/trash?${params}`)
    },
  })
  const impact = useQuery({
    queryKey: ['project-trash', 'detail', selected?.id],
    queryFn: () => api.get<ProjectImpact>(`/projects/trash/${selected?.id}`),
    enabled: !!selected,
  })

  async function restore(project: ProjectTrashRow) {
    setPending(true)
    setError(null)
    try {
      await api.post(`/projects/trash/${project.id}/restore`)
      setSelected(null)
      setCursor(null)
      await qc.invalidateQueries({ queryKey: ['project-trash'] })
      await qc.invalidateQueries({ queryKey: ['projects'] })
    } catch (err) {
      setError(err instanceof Error ? err.message : '恢复失败，请重试')
    } finally {
      setPending(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !pending) onClose() }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>项目回收站</DialogTitle>
          <DialogDescription>可查看并恢复你有权限管理的已删除项目。</DialogDescription>
        </DialogHeader>
        <Input aria-label="筛选项目名称" placeholder="按名称筛选" autoComplete="off" maxLength={128}
          value={query} onChange={(event) => { setQuery(event.target.value); setCursor(null); setSelected(null) }} />
        {page.isLoading && <p role="status">加载中…</p>}
        {page.isError && <Button variant="outline" onClick={() => void page.refetch()}>重新加载回收站</Button>}
        {page.data?.items.length === 0 && <p className="text-sm text-muted-foreground">没有匹配的已删除项目。</p>}
        {page.data?.items.map((item) => (
          <div key={item.id} className="rounded-md border p-3">
            <div className="flex justify-between gap-2">
              <div>
                <p className="font-medium">{item.name}</p>
                <p className="text-xs text-muted-foreground">删除于 {new Date(item.deleted_at).toLocaleString()}</p>
              </div>
              <Button variant="outline" size="sm" disabled={pending} onClick={() => { setSelected(item); setError(null) }}>
                查看
              </Button>
            </div>
            {selected?.id === item.id && (
              <div className="mt-3 space-y-2">
                {impact.isLoading && <p role="status">正在查询影响范围…</p>}
                {impact.isError && <Button variant="outline" onClick={() => void impact.refetch()}>重新查询影响范围</Button>}
                {impact.data && <ProjectImpactSummary impact={impact.data} />}
                {error && <p className="text-sm text-destructive">{error}</p>}
                <Button size="sm" disabled={pending || !impact.data} onClick={() => void restore(item)}>恢复项目</Button>
              </div>
            )}
          </div>
        ))}
        <DialogFooter>
          {cursor && <Button variant="outline" onClick={() => { setCursor(null); setSelected(null) }}>返回首页</Button>}
          {page.data?.next_cursor && <Button variant="outline"
            onClick={() => { setCursor(page.data.next_cursor); setSelected(null) }}>下一页</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function ProjectsPage() {
  const { user } = useAuth()
  const [createOpen, setCreateOpen] = useState(false)
  const [trashOpen, setTrashOpen] = useState(false)
  const [deleteProject, setDeleteProject] = useState<ProjectRow | null>(null)
  const {
    data: projects,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<ProjectRow[]>('/projects'),
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">项目</h1>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setTrashOpen(true)}>
            <Trash2 className="mr-2 h-4 w-4" />项目回收站
          </Button>
          {user?.workspace_role === 'admin' && (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />新建项目
            </Button>
          )}
        </div>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
      <ErrorNotification message={error ? (error as Error).message : null} />
      {!isLoading && projects?.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-2 py-12 text-muted-foreground">
            <FolderOpen className="h-8 w-8" />
            <p className="text-sm">暂无项目</p>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,17rem),1fr))] gap-3">
        {projects?.map((p) => (
          <article key={p.id} className="relative flex min-w-0">
            <Link to={`/projects/${p.id}`} aria-label={p.name}
              className="group flex w-full flex-col gap-2 rounded-xl border bg-card p-5 text-card-foreground transition-colors hover:border-muted-foreground/50 focus-visible:ring-2 focus-visible:ring-ring">
              <h2 className="pr-8 text-base font-semibold [overflow-wrap:anywhere]">{p.name}</h2>
              {p.description && <p className="line-clamp-2 text-sm leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">{p.description}</p>}
              <div className="mt-auto flex items-center justify-between gap-3 pt-3 text-xs text-muted-foreground">
                <span className="[overflow-wrap:anywhere]">{p.member_count != null && `${p.member_count} 位成员`}{p.owner_name && ` · 负责人 ${p.owner_name}`}</span>
                <ChevronRight aria-hidden="true" className="size-4 shrink-0" />
              </div>
            </Link>
            {p.my_role === 'owner' && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="absolute right-2 top-2" aria-label={`${p.name}的更多操作`}><Ellipsis /></Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem variant="destructive" onSelect={() => setDeleteProject(p)}>
                    <Trash2 />删除项目
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </article>
        ))}
      </div>

      <CreateProjectDialog open={createOpen} onOpenChange={setCreateOpen} />
      {trashOpen && <ProjectTrash onClose={() => setTrashOpen(false)} />}
      {deleteProject && <ProjectRemovalDialog project={deleteProject} onClose={() => setDeleteProject(null)} />}
    </div>
  )
}
