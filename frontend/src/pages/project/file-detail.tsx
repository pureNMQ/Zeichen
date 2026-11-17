import { useState, type FormEvent } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ErrorNotification } from '@/components/ui/notification'
import { api, type Page } from '@/lib/api'
import { useCurrentProject } from '@/lib/current-project'
import { projectFileApiPath, projectFileContentUrl, type ProjectFileSummary } from '@/lib/project-files'
import { projectResourceHref } from '@/lib/project-links'

type Usage = { href: string; label: string; kind: 'project' | 'requirement' | 'task' | 'wiki'; current: boolean }
type FileAction = 'rename' | 'delete'

function useFileUsage(projectId: string, fileId: string, history: boolean) {
  const query = useInfiniteQuery({
    queryKey: ['project-file-usage', projectId, fileId, history],
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: '20', include_history: String(history) })
      if (pageParam) params.set('cursor', pageParam)
      return api.get<Page<Usage>>(`${projectFileApiPath(projectId, fileId)}/usage?${params}`, signal)
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    retry: false,
  })
  const prefix = `/projects/${encodeURIComponent(projectId)}`
  const items = query.data?.pages.flatMap((page) => page.items)
    .filter((item) => item.href === prefix || item.href.startsWith(`${prefix}/`)) ?? []
  return { ...query, items }
}

function UsageList({ usage, inDialog = false }: { usage: ReturnType<typeof useFileUsage>; inDialog?: boolean }) {
  return <div className="space-y-2">
    {inDialog ? usage.error && <p role="alert" className="text-sm text-destructive">{usage.error.message}</p>
      : <ErrorNotification message={usage.error?.message} />}
    {usage.isLoading && <p role="status" className="text-sm text-muted-foreground">加载使用位置…</p>}
    {usage.isError && !usage.isFetchNextPageError && (
      <Button size="sm" variant="outline" onClick={() => void usage.refetch()}>重试使用位置</Button>
    )}
    {usage.isSuccess && !usage.items.length && <p className="text-sm text-muted-foreground">暂无引用</p>}
    {usage.items.length > 0 && <ul className="space-y-1 text-sm">
      {usage.items.map((item) => (
        <li key={item.href}>
          <Link to={item.href} className="break-words text-primary hover:underline">{item.label}</Link>
          {!item.current && <span className="ms-2 text-xs text-muted-foreground">历史版本</span>}
        </li>
      ))}
    </ul>}
    {usage.hasNextPage && <Button size="sm" variant="outline" disabled={usage.isFetchingNextPage}
      onClick={() => void usage.fetchNextPage()}>
      {usage.isFetchingNextPage ? '加载中…' : usage.isFetchNextPageError ? '重试加载' : '加载更多引用'}
    </Button>}
  </div>
}

function FileUsage({ file }: { file: ProjectFileSummary }) {
  const [history, setHistory] = useState(false)
  const usage = useFileUsage(file.project_id, file.id, history)
  return <section className="space-y-2 rounded-lg border p-3" aria-label="使用位置">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-sm font-semibold">使用位置</h2>
      <Button type="button" size="sm" variant={history ? 'secondary' : 'outline'} aria-pressed={history}
        onClick={() => setHistory((value) => !value)}>包含历史版本</Button>
    </div>
    <UsageList usage={usage} />
  </section>
}

function RenameFileDialog({ file, onClose }: { file: ProjectFileSummary; onClose: () => void }) {
  const [name, setName] = useState(file.name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()
  async function rename(event: FormEvent) {
    event.preventDefault()
    if (busy || !name.trim() || name.trim() === file.name) return
    setBusy(true)
    setError(null)
    try {
      await api.patch(projectFileApiPath(file.project_id, file.id), { name: name.trim() })
      void qc.invalidateQueries({ queryKey: ['project-files', file.project_id] })
      void qc.invalidateQueries({ queryKey: ['project-file', file.project_id, file.id] })
      onClose()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '重命名失败，请重试。')
    } finally {
      setBusy(false)
    }
  }
  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose() }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>重命名文件</DialogTitle>
        <DialogDescription>编辑文件库中的显示名称。</DialogDescription>
      </DialogHeader>
      <form className="space-y-3" onSubmit={(event) => void rename(event)}>
        <Input autoComplete="off" aria-label="文件名称" value={name} required maxLength={255} disabled={busy}
          onChange={(event) => setName(event.currentTarget.value)} />
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" disabled={busy} onClick={onClose}>取消</Button>
          <Button type="submit" disabled={busy || !name.trim() || name.trim() === file.name}>{busy ? '保存中…' : '保存名称'}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
}

function DeleteFileDialog({ file, onClose }: { file: ProjectFileSummary; onClose: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const usage = useFileUsage(file.project_id, file.id, true)
  const qc = useQueryClient()
  const navigate = useNavigate()
  async function remove() {
    if (busy || !usage.isSuccess || usage.isFetching) return
    setBusy(true)
    setError(null)
    try {
      await api.delete(projectFileApiPath(file.project_id, file.id))
      qc.removeQueries({ queryKey: ['project-file', file.project_id, file.id] })
      void qc.invalidateQueries({ queryKey: ['project-files', file.project_id] })
      qc.removeQueries({ queryKey: ['project-file-usage', file.project_id, file.id] })
      navigate(projectResourceHref(file.project_id, 'files'), { replace: true })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '删除文件失败，请重试。')
    } finally {
      setBusy(false)
    }
  }
  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose() }}>
    <DialogContent className="max-h-[85dvh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>删除文件</DialogTitle>
        <DialogDescription>删除「{file.name}」后，下面的引用会失效。可从回收站恢复。</DialogDescription>
      </DialogHeader>
      <UsageList usage={usage} inDialog />
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <DialogFooter>
        <Button type="button" variant="outline" disabled={busy} onClick={onClose}>取消</Button>
        <Button type="button" variant="destructive" disabled={busy || !usage.isSuccess || usage.isFetching} onClick={() => void remove()}>
          {busy ? '删除中…' : '确认删除'}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}

function FilePreview({ file }: { file: ProjectFileSummary }) {
  if (!file.preview_href) return null
  const url = projectFileContentUrl(file.project_id, file.id, true)
  if (file.media_type.startsWith('image/')) {
    return <img src={url} alt={file.name} className="max-h-[65vh] max-w-full rounded-md object-contain" />
  }
  if (file.media_type.startsWith('video/')) return <video controls preload="metadata" src={url} className="max-h-[65vh] max-w-full rounded-md" />
  if (file.media_type.startsWith('audio/')) return <audio controls preload="metadata" src={url} className="max-w-full" />
  return <a href={url} target="_blank" rel="noopener noreferrer" className="text-sm text-primary hover:underline">打开预览</a>
}

export function ProjectFileDetailPage() {
  const { id = '' } = useParams()
  return <FileDetail key={id} id={id} />
}

function FileDetail({ id }: { id: string }) {
  const { projectId, role } = useCurrentProject()
  const [action, setAction] = useState<FileAction | null>(null)
  const { data: file, isLoading, error, isError } = useQuery({
    queryKey: ['project-file', projectId, id],
    queryFn: () => api.get<ProjectFileSummary>(projectFileApiPath(projectId!, id)),
    enabled: !!projectId,
    retry: false,
  })

  if (isLoading) return <p role="status" className="text-sm text-muted-foreground">加载文件…</p>
  if (isError || !file || file.project_id !== projectId || file.id !== id) {
    return <ErrorNotification message={error instanceof Error ? error.message : '文件不存在或无访问权限'} />
  }
  return (
    <section className="space-y-4">
      <header className="space-y-2">
        <Link to={projectResourceHref(file.project_id, 'files')} className="text-sm text-primary hover:underline">返回文件</Link>
        <div className="flex flex-wrap justify-between gap-2">
          <h1 className="break-all text-xl font-semibold">{file.name}</h1>
          {(role === 'owner' || role === 'editor') && <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => setAction('rename')}>重命名</Button>
            <Button size="sm" variant="outline" onClick={() => setAction('delete')}>删除</Button>
          </div>}
        </div>
        <p className="text-sm text-muted-foreground">
          {file.media_type} · {new Intl.NumberFormat('zh-CN').format(file.size)} 字节
        </p>
        <a href={projectFileContentUrl(file.project_id, file.id)} download className="text-sm font-medium text-primary hover:underline">下载文件</a>
      </header>
      <FilePreview file={file} />
      <FileUsage file={file} />
      {action === 'rename' && <RenameFileDialog file={file} onClose={() => setAction(null)} />}
      {action === 'delete' && <DeleteFileDialog file={file} onClose={() => setAction(null)} />}
    </section>
  )
}
