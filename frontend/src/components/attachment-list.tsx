import { useRef, useState, type ChangeEvent } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Paperclip, Trash2, Upload } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, ApiError, withProject, type AttachmentRow, type Page } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorNotification, useNotification } from '@/components/ui/notification'
import { useProjectRole } from '@/lib/current-project'
import { associateProjectFile, fileAssociationQuery, projectFileApiPath, uploadAssociatedFile, type FileAssociationTarget,
  type ProjectFileSummary, type StagedProjectFile } from '@/lib/project-files'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

type RelatedFile = (ProjectFileSummary | { id: string; unavailable: true }) & { attached: boolean; referenced: boolean }

function FilePicker({ projectId, linked, onSelect, onUpload, onClose, restoreFocus }: {
  projectId: string; linked: Set<string>; onSelect: (id: string) => Promise<void>; onUpload: () => void; onClose: () => void
  restoreFocus: () => void
}) {
  const [query, setQuery] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const search = useInfiniteQuery({
    queryKey: ['project-files', projectId, 'picker', query.trim()],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ query: query.trim(), limit: '20' })
      if (pageParam) params.set('cursor', pageParam)
      return api.get<Page<ProjectFileSummary>>(`/v2/projects/${encodeURIComponent(projectId)}/files?${params}`, signal)
    },
    getNextPageParam: (page) => page.next_cursor,
  })
  const matches = search.data?.pages.flatMap((page) => page.items.filter((file) => file.project_id === projectId)) ?? []
  async function select(id: string) {
    setSaving(true)
    setError(null)
    try {
      await onSelect(id)
      onClose()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '添加文件失败，请重试。')
    } finally {
      setSaving(false)
    }
  }
  return <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
    <DialogContent aria-describedby={undefined} onCloseAutoFocus={(event) => {
      event.preventDefault()
      restoreFocus()
    }}>
      <DialogHeader><DialogTitle>添加文件</DialogTitle></DialogHeader>
      <Input autoComplete="off" aria-label="搜索项目文件" placeholder="搜索项目文件" maxLength={256} value={query}
        onChange={(event) => setQuery(event.target.value)} />
      <div className="max-h-64 overflow-y-auto">
        {search.isLoading && <p role="status">正在加载文件…</p>}
        {search.isSuccess && !matches.length && <p className="text-sm text-muted-foreground">没有匹配的项目文件</p>}
        {matches.map((file) => <button key={file.id} type="button" disabled={saving || linked.has(file.id)}
          onClick={() => void select(file.id)} className="w-full rounded-md px-2 py-2 text-left hover:bg-muted focus-visible:ring-2 disabled:opacity-60">
          <span className="block break-all font-medium">{file.name}</span>
          <span className="text-xs text-muted-foreground" title={file.id}>{formatSize(file.size)} · {file.id.slice(-8)}{linked.has(file.id) && ' · 已关联'}</span>
        </button>)}
        {search.hasNextPage && <Button type="button" variant="ghost" disabled={search.isFetching} onClick={() => void search.fetchNextPage()}>加载更多文件</Button>}
      </div>
      {(error || search.error) && <p role="alert">{error ?? search.error?.message}</p>}
      {search.isError && <Button variant="outline" onClick={() => void (search.isFetchNextPageError ? search.fetchNextPage() : search.refetch())}>重试加载</Button>}
      <Button type="button" variant="outline" disabled={saving} onClick={onUpload}><Upload aria-hidden="true" />从本机上传</Button>
    </DialogContent>
  </Dialog>
}

export function RelatedFiles({ projectId, targetKind, targetId, canEdit }: {
  projectId: string; targetKind: FileAssociationTarget; targetId: string; canEdit: boolean
}) {
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const addButton = useRef<HTMLButtonElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [retry, setRetry] = useState<StagedProjectFile | null>(null)
  const key = ['project-files', projectId, 'related', targetKind, targetId]
  const list = useInfiniteQuery({
    queryKey: key,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => {
      const params = fileAssociationQuery(targetKind, targetId)
      params.set('include_body', 'true')
      if (pageParam) params.set('cursor', pageParam)
      return api.get<Page<RelatedFile>>(`/v2/projects/${encodeURIComponent(projectId)}/files/associations?${params}`, signal)
    },
    getNextPageParam: (page) => page.next_cursor,
  })
  const files = list.data?.pages.flatMap((page) => page.items) ?? []

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['project-files', projectId] }),
      queryClient.invalidateQueries({ queryKey: ['project-file-usage', projectId] }),
    ])
  }

  async function upload(attempt: StagedProjectFile) {
    setPending(true)
    setError(null)
    setRetry(null)
    try {
      await uploadAssociatedFile(projectId, targetKind, targetId, attempt)
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '添加文件失败，请重试。')
      setRetry(attempt)
    } finally {
      setPending(false)
    }
  }

  async function unlink(id: string) {
    setError(null)
    try {
      await api.delete(`${projectFileApiPath(projectId, id)}/usage?${fileAssociationQuery(targetKind, targetId)}`)
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '移除关联失败，请重试。')
    }
  }

  const addFile = canEdit && <div className="flex items-center gap-2">
    <input ref={input} type="file" hidden autoComplete="off" aria-label="选择要添加的文件" disabled={pending}
      onChange={(event) => {
        const file = event.currentTarget.files?.[0]
        event.currentTarget.value = ''
        if (file) void upload({ file, requestId: crypto.randomUUID() })
      }} />
    <Button ref={addButton} type="button" variant="ghost" size="sm" disabled={pending} onClick={() => setPickerOpen(true)}>
      <Paperclip aria-hidden="true" />{pending ? '添加中…' : '添加文件'}
    </Button>
    {retry && <Button type="button" variant="outline" size="sm" disabled={pending} onClick={() => void upload(retry)}>重试添加</Button>}
  </div>

  return (
    <section aria-label="相关文件" className="space-y-2">
      <ErrorNotification message={error ?? list.error?.message} />
      {canEdit && pickerOpen && <FilePicker projectId={projectId} linked={new Set(files.filter((file) => file.attached).map((file) => file.id))}
        onSelect={async (id) => {
          await associateProjectFile(projectId, targetKind, targetId, id)
          await refresh()
        }}
        onClose={() => setPickerOpen(false)} restoreFocus={() => addButton.current?.focus()} onUpload={() => {
          input.current?.click()
          setPickerOpen(false)
        }} />}
      {list.isLoading && <p role="status" className="text-sm text-muted-foreground">正在加载相关文件…</p>}
      {files.length > 0 ? <>
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-medium">相关文件</h2>
          {addFile}
        </div>
        <ul className="divide-y rounded-lg border">
          {files.map((file) => (
            <li key={file.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
              <div className="min-w-0 flex-1">
                {'unavailable' in file ? <span className="text-muted-foreground">文件已删除</span> :
                  <Link to={file.href} className="block truncate font-medium hover:underline">{file.name}</Link>}
                <span className="text-xs text-muted-foreground">
                  {'unavailable' in file ? '' : formatSize(file.size) + ' · '}
                  {file.referenced ? (file.attached ? '正文引用 · 单独添加' : '正文引用') : '单独添加'}
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {!('unavailable' in file) && file.download_href &&
                  <a href={file.download_href} className="underline-offset-4 hover:underline">下载</a>}
                {canEdit && file.attached && !('unavailable' in file) &&
                  <Button type="button" variant="ghost" size="sm" onClick={() => void unlink(file.id)}>
                    移除关联
                  </Button>}
              </div>
            </li>
          ))}
        </ul>
      </> : addFile}
      {list.isError && !list.isFetchNextPageError && <Button type="button" variant="outline" size="sm"
        disabled={list.isFetching} onClick={() => void list.refetch()}>重试加载</Button>}
      {list.hasNextPage && <Button type="button" variant="outline" size="sm" disabled={list.isFetchingNextPage}
        onClick={() => void list.fetchNextPage()}>{list.isFetchingNextPage ? '加载中…' : list.isFetchNextPageError ? '重试加载更多' : '加载更多'}</Button>}
    </section>
  )
}

export function AttachmentList({ targetType, targetId, projectId, readOnly = false }: {
  targetType: string; targetId: string; projectId?: string; readOnly?: boolean
}) {
  const queryClient = useQueryClient()
  const role = useProjectRole()
  const { notify } = useNotification()
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const key = ['attachments', targetType, targetId, projectId]
  const path = withProject(`/targets/${targetType}/${targetId}/attachments`, projectId)

  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () =>
      api
        .get<{ items: AttachmentRow[] }>(path)
        .then((r) => r.items),
  })

  const canEdit = !readOnly && (role === 'editor' || role === 'owner')

  async function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setError(null)
    setUploading(true)
    try {
      await api.upload<AttachmentRow>(path, file)
      await queryClient.invalidateQueries({ queryKey: key })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '上传失败,请重试')
    } finally {
      setUploading(false)
    }
  }

  async function remove(id: string) {
    setError(null)
    try {
      await api.delete(`/attachments/${id}`)
      await queryClient.invalidateQueries({ queryKey: key })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败,请重试')
    }
  }

  async function download(id: string) {
    try {
      const resp = await fetch(`/api/attachments/${id}/download`, { credentials: 'include' })
      if (!resp.ok) throw new Error('下载失败')
      const blob = await resp.blob()
      const disposition = resp.headers.get('Content-Disposition') ?? ''
      const match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
      const name = match ? decodeURIComponent(match[1]) : `attachment-${id}`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = name
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      notify(err instanceof Error ? err.message : '下载失败')
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Paperclip className="h-4 w-4" />
          附件
          <span className="text-xs font-normal text-muted-foreground">
            {isLoading ? '' : `(${(data ?? []).length})`}
          </span>
        </CardTitle>
        {canEdit && (
          <>
            <input
              ref={inputRef}
              type="file"
              className="hidden"
              onChange={(e) => void onFileChange(e)}
              autoComplete="off"
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={uploading}
              onClick={() => inputRef.current?.click()}
            >
              <Upload className="mr-1 h-3.5 w-3.5" />
              {uploading ? '上传中…' : '上传'}
            </Button>
          </>
        )}
      </CardHeader>
      <CardContent className="space-y-2">
        <ErrorNotification message={error} />
        {!isLoading && (data ?? []).length === 0 && (
          <p className="py-3 text-center text-sm text-muted-foreground">暂无附件</p>
        )}
        {(data ?? []).map((a) => (
          <div
            key={a.id}
            className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
          >
            <div className="flex min-w-0 items-center gap-2">
              <Paperclip className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span className="truncate">{a.file_name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{formatSize(a.size)}</span>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button type="button" variant="ghost" size="icon-sm" onClick={() => void download(a.id)} aria-label={`下载 ${a.file_name}`}>
                <Download className="h-4 w-4" />
              </Button>
              {canEdit && (
                <Button type="button" variant="ghost" size="icon-sm" onClick={() => void remove(a.id)} aria-label={`删除 ${a.file_name}`}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
