import { useRef, useState, type ChangeEvent } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Paperclip, Trash2, Upload } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, ApiError, withProject, type AttachmentRow, type Page } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorNotification, useNotification } from '@/components/ui/notification'
import { useProjectRole } from '@/lib/current-project'
import { fileAssociationQuery, projectFileApiPath, uploadAssociatedFile, type FileTargetKind,
  type ProjectFileSummary, type StagedProjectFile } from '@/lib/project-files'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

type AssociatedFile = ProjectFileSummary | { id: string; unavailable: true }

export function ProjectAttachments({ projectId, targetKind, targetId, canEdit }: {
  projectId: string; targetKind: FileTargetKind; targetId: string; canEdit: boolean
}) {
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [retry, setRetry] = useState<StagedProjectFile | null>(null)
  const key = ['project-files', projectId, 'associations', targetKind, targetId]
  const list = useInfiniteQuery({
    queryKey: key,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => {
      const params = fileAssociationQuery(targetKind, targetId)
      if (pageParam) params.set('cursor', pageParam)
      return api.get<Page<AssociatedFile>>(`/v2/projects/${encodeURIComponent(projectId)}/files/associations?${params}`, signal)
    },
    getNextPageParam: (page) => page.next_cursor,
  })
  const files = list.data?.pages.flatMap((page) => page.items) ?? []

  async function upload(attempt: StagedProjectFile) {
    setPending(true)
    setError(null)
    setRetry(null)
    try {
      await uploadAssociatedFile(projectId, targetKind, targetId, attempt)
      await queryClient.invalidateQueries({ queryKey: ['project-files', projectId] })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '上传失败，请重试。')
      setRetry(attempt)
    } finally {
      setPending(false)
    }
  }

  async function unlink(id: string) {
    setError(null)
    try {
      await api.delete(`${projectFileApiPath(projectId, id)}/usage?${fileAssociationQuery(targetKind, targetId)}`)
      await queryClient.invalidateQueries({ queryKey: key })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '移除关联失败，请重试。')
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="flex items-center gap-2 text-sm"><Paperclip className="h-4 w-4" /> 附件</CardTitle>
        {canEdit && <div className="flex gap-2">
          <input ref={input} type="file" hidden autoComplete="off" aria-label="选择附件" disabled={pending}
            onChange={(event) => {
              const file = event.currentTarget.files?.[0]
              event.currentTarget.value = ''
              if (file) void upload({ file, requestId: crypto.randomUUID() })
            }} />
          <Button type="button" variant="outline" size="sm" disabled={pending} onClick={() => input.current?.click()}>
            {pending ? '上传中…' : '上传附件'}
          </Button>
          {retry && <Button type="button" variant="outline" size="sm" onClick={() => void upload(retry)}>重试上传</Button>}
        </div>}
      </CardHeader>
      <CardContent className="space-y-2">
        <ErrorNotification message={error ?? list.error?.message} />
        {list.isLoading && <p role="status" className="text-sm text-muted-foreground">正在加载附件…</p>}
        {!list.isLoading && !list.isError && files.length === 0 && (
          <p className="text-sm text-muted-foreground">暂无附件</p>
        )}
        {files.map((file) => (
          <div key={file.id} className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm">
            {'unavailable' in file ? <span className="text-muted-foreground">此附件已删除</span> : (
              <>
                <div className="flex min-w-0 items-center gap-2">
                  <Link to={file.href} className="truncate text-primary hover:underline">{file.name}</Link>
                  <span className="shrink-0 text-xs text-muted-foreground">{formatSize(file.size)}</span>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {file.download_href && <a href={file.download_href} className="underline-offset-4 hover:underline">下载</a>}
                  {canEdit && (
                    <Button type="button" variant="ghost" size="sm" onClick={() => void unlink(file.id)}>
                      移除关联
                    </Button>
                  )}
                </div>
              </>
            )}
          </div>
        ))}
        {list.hasNextPage && <Button type="button" variant="outline" size="sm" disabled={list.isFetchingNextPage}
          onClick={() => void list.fetchNextPage()}>{list.isFetchingNextPage ? '加载中…' : '加载更多'}</Button>}
      </CardContent>
    </Card>
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
