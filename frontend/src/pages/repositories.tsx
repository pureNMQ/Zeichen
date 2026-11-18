import { useEffect, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, ExternalLink, Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification, useNotification } from '@/components/ui/notification'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { api, ApiError, type RepositoryRow, type RepositoryVcsType } from '@/lib/api'
import { useCurrentProject, useProjectRole } from '@/lib/current-project'

type RepositoryForm = {
  name: string
  vcs_type: RepositoryVcsType
  other_vcs_type: string
  url: string
  description: string
  default_branch: string
}

const EMPTY_FORM: RepositoryForm = {
  name: '', vcs_type: 'git', other_vcs_type: '', url: '', description: '', default_branch: '',
}

function formFrom(repository: RepositoryRow): RepositoryForm {
  return {
    name: repository.name,
    vcs_type: repository.vcs_type,
    other_vcs_type: repository.other_vcs_type ?? '',
    url: repository.url,
    description: repository.description ?? '',
    default_branch: repository.default_branch ?? '',
  }
}

function RepositoryDialog({
  projectId, repository, open, onOpenChange, onSaved,
}: {
  projectId: string
  repository: RepositoryRow | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}) {
  const [form, setForm] = useState<RepositoryForm>(repository ? formFrom(repository) : EMPTY_FORM)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (open) {
      setForm(repository ? formFrom(repository) : EMPTY_FORM)
      setError(null)
    }
  }, [open, repository])

  function set<K extends keyof RepositoryForm>(key: K, value: RepositoryForm[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    const body = {
      ...form,
      other_vcs_type: form.vcs_type === 'other' ? form.other_vcs_type : null,
      description: form.description || null,
      default_branch: form.default_branch || null,
    }
    try {
      if (repository) await api.patch(`/repositories/${repository.id}`, body)
      else await api.post(`/projects/${projectId}/repositories`, body)
      onOpenChange(false)
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存代码仓库失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{repository ? '编辑代码仓库' : '登记代码仓库'}</DialogTitle>
          <DialogDescription>仅保存仓库来源信息；不会连接、克隆或同步远端仓库。</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(event) => void submit(event)}>
          <div className="space-y-1.5">
            <Label htmlFor="repository-name">名称</Label>
            <Input id="repository-name" autoComplete="off" value={form.name} onChange={(event) => set('name', event.target.value)} maxLength={128} required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="repository-vcs-type">版本控制类型</Label>
            <Select value={form.vcs_type} onValueChange={(value) => set('vcs_type', value as RepositoryVcsType)}>
              <SelectTrigger id="repository-vcs-type"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="git">Git</SelectItem>
                <SelectItem value="svn">SVN</SelectItem>
                <SelectItem value="other">其他</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {form.vcs_type === 'other' && <div className="space-y-1.5">
            <Label htmlFor="repository-other-type">类型名称</Label>
            <Input id="repository-other-type" autoComplete="off" value={form.other_vcs_type} onChange={(event) => set('other_vcs_type', event.target.value)} maxLength={64} required />
          </div>}
          <div className="space-y-1.5">
            <Label htmlFor="repository-url">仓库地址</Label>
            <Input id="repository-url" autoComplete="url" value={form.url} onChange={(event) => set('url', event.target.value)} maxLength={2048} required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="repository-default-branch">默认分支（可选）</Label>
            <Input id="repository-default-branch" autoComplete="off" value={form.default_branch} onChange={(event) => set('default_branch', event.target.value)} maxLength={256} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="repository-description">用途备注（可选）</Label>
            <Textarea id="repository-description" autoComplete="off" value={form.description} onChange={(event) => set('description', event.target.value)} maxLength={1000} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
            <Button type="submit" disabled={submitting}>{submitting ? '保存中…' : '保存'}</Button>
          </DialogFooter>
        </form>
        <ErrorNotification message={error} />
      </DialogContent>
    </Dialog>
  )
}

function vcsLabel(repository: RepositoryRow) {
  return repository.vcs_type === 'other' ? `其他：${repository.other_vcs_type}` : repository.vcs_type.toUpperCase()
}

export function RepositoriesPage() {
  const queryClient = useQueryClient()
  const { notify } = useNotification()
  const { currentProject, isLoading } = useCurrentProject()
  const role = useProjectRole()
  const canEdit = role === 'owner' || role === 'editor'
  const projectId = currentProject?.id
  const [editing, setEditing] = useState<RepositoryRow | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [showDeleted, setShowDeleted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { data: repositories = [], error: loadError, isLoading: repositoriesLoading, refetch } = useQuery({
    queryKey: ['repositories', projectId],
    queryFn: () => api.get<{ items: RepositoryRow[] }>(`/projects/${projectId}/repositories`).then((result) => result.items),
    enabled: Boolean(projectId),
  })
  const { data: deletedRepositories = [], error: deletedLoadError, isLoading: deletedLoading } = useQuery({
    queryKey: ['repositories', projectId, 'deleted'],
    queryFn: () => api.get<{ items: RepositoryRow[] }>(`/projects/${projectId}/repositories/deleted`).then((result) => result.items),
    enabled: Boolean(projectId) && canEdit && showDeleted,
  })

  const invalidate = () => void Promise.all([
    queryClient.invalidateQueries({ queryKey: ['repositories', projectId] }),
    queryClient.invalidateQueries({ queryKey: ['repositories', projectId, 'deleted'] }),
  ])

  async function remove(repository: RepositoryRow) {
    if (!window.confirm(`删除“${repository.name}”的登记记录？这不会影响实际仓库。`)) return
    setError(null)
    try {
      await api.post(`/repositories/${repository.id}/delete`)
      invalidate()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除代码仓库失败')
    }
  }

  async function restore(repository: RepositoryRow) {
    setError(null)
    try {
      await api.post(`/repositories/${repository.id}/restore`)
      invalidate()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '恢复代码仓库失败')
    }
  }

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url)
      notify('仓库地址已复制', 'success')
    } catch {
      notify('复制仓库地址失败')
    }
  }

  const pageError = error ?? (loadError instanceof ApiError ? loadError.message : deletedLoadError instanceof ApiError ? deletedLoadError.message : null)
  if (isLoading) return <p className="text-sm text-muted-foreground">加载中…</p>
  if (!currentProject) return <p className="text-sm text-muted-foreground">请先选择项目。</p>

  return <div className="mx-auto max-w-5xl space-y-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold">代码仓库</h1>
        <p className="mt-1 text-sm text-muted-foreground">登记项目关联的代码来源。</p>
      </div>
      {canEdit && <div className="flex gap-2">
        <Button variant="outline" onClick={() => setShowDeleted((value) => !value)}>{showDeleted ? '隐藏已删除' : '查看已删除'}</Button>
        <Button onClick={() => setCreateOpen(true)}><Plus className="mr-2 h-4 w-4" />登记仓库</Button>
      </div>}
    </div>
    {repositoriesLoading && <p role="status" className="text-sm text-muted-foreground">加载仓库…</p>}
    {loadError && <Button size="sm" variant="outline" onClick={() => void refetch()}>重试加载</Button>}
    {!repositoriesLoading && !loadError && !repositories.length && <p className="text-sm text-muted-foreground">暂无代码仓库</p>}
    {repositories.length > 0 && <ul aria-label="代码仓库" className="divide-y rounded-lg border">
      {repositories.map((repository) => (
        <li id={`repository-${repository.id}`} key={repository.id} className="flex flex-col gap-2 p-3 sm:flex-row sm:items-start sm:justify-between sm:p-4">
          <div className="min-w-0 space-y-1">
            <h2 className="wrap-anywhere text-sm font-medium">{repository.name}</h2>
            <p className="wrap-anywhere text-xs text-muted-foreground">
              {vcsLabel(repository)}{repository.default_branch && <> · 默认分支 <code>{repository.default_branch}</code></>}
            </p>
            <code className="block wrap-anywhere text-xs text-muted-foreground">{repository.url}</code>
            {repository.description && <p className="wrap-anywhere text-sm text-muted-foreground">{repository.description}</p>}
          </div>
          <div className="flex shrink-0 flex-wrap gap-1">
            <Button size="icon-sm" variant="ghost" aria-label={`复制 ${repository.name} 地址`} title="复制地址" onClick={() => void copy(repository.url)}><Copy /></Button>
            <Button size="icon-sm" variant="ghost" asChild>
              <a href={repository.url} target="_blank" rel="noreferrer" aria-label={`打开 ${repository.name}`} title="打开仓库"><ExternalLink /></a>
            </Button>
            {canEdit && <>
              <Button size="icon-sm" variant="ghost" aria-label={`编辑 ${repository.name}`} title="编辑" onClick={() => setEditing(repository)}><Pencil /></Button>
              <Button size="icon-sm" variant="ghost" aria-label={`删除 ${repository.name}`} title="删除登记" onClick={() => void remove(repository)}><Trash2 /></Button>
            </>}
          </div>
        </li>
      ))}
    </ul>}
    {showDeleted && canEdit && <section className="space-y-3">
      <h2 className="text-base font-semibold">已删除</h2>
      {deletedLoading && <p role="status" className="text-sm text-muted-foreground">加载已删除仓库…</p>}
      {!deletedLoading && !deletedLoadError && !deletedRepositories.length && <p className="text-sm text-muted-foreground">没有已删除记录。</p>}
      {deletedRepositories.length > 0 && <ul className="divide-y rounded-lg border">
        {deletedRepositories.map((repository) => <li key={repository.id} className="flex flex-wrap items-start justify-between gap-2 p-3">
          <div className="min-w-0 flex-1">
            <p className="wrap-anywhere text-sm font-medium">{repository.name}</p>
            <p className="wrap-anywhere text-xs text-muted-foreground">{vcsLabel(repository)} · {repository.url}</p>
          </div>
          <Button variant="outline" size="sm" onClick={() => void restore(repository)}><RotateCcw />恢复</Button>
        </li>)}
      </ul>}
    </section>}
    <RepositoryDialog projectId={currentProject.id} repository={null} open={createOpen} onOpenChange={setCreateOpen} onSaved={invalidate} />
    <RepositoryDialog projectId={currentProject.id} repository={editing} open={editing !== null} onOpenChange={(open) => !open && setEditing(null)} onSaved={invalidate} />
    <ErrorNotification message={pageError} />
  </div>
}
