import { useEffect, useRef, useState } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ErrorNotification, useNotification } from '@/components/ui/notification'
import { api, type Page } from '@/lib/api'
import { useCurrentProject } from '@/lib/current-project'
import { projectFileApiPath, projectFileContentUrl, uploadFileToProject, type ProjectFileSummary } from '@/lib/project-files'
import { projectResourceHref } from '@/lib/project-links'

type UploadAttempt = { file: File; id: string }
type FileLimits = { max_file_bytes: number; project_quota_bytes: number }
type DeletedFile = ProjectFileSummary & {
  deleted_at: string
  deleted_by: string | null
}

const bytes = new Intl.NumberFormat('zh-CN')

function ProjectFileUpload({ projectId, path }: { projectId: string; path: string }) {
  const input = useRef<HTMLInputElement>(null)
  const transfer = useRef<AbortController | null>(null)
  const [pending, setPending] = useState<number | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [retry, setRetry] = useState<UploadAttempt | null>(null)
  const [uploaded, setUploaded] = useState<ProjectFileSummary | null>(null)
  const qc = useQueryClient()
  const limits = useQuery({
    queryKey: ['project-file-limits', projectId],
    queryFn: ({ signal }) => api.get<FileLimits>(`${path}/limits`, signal),
    retry: false,
  })

  useEffect(() => () => { transfer.current?.abort() }, [])

  async function upload(attempt: UploadAttempt) {
    if (transfer.current) return
    const controller = new AbortController()
    transfer.current = controller
    setPending(0)
    setFailure(null)
    setRetry(null)
    setUploaded(null)
    try {
      const file = await uploadFileToProject(projectId, attempt.file, attempt.id, controller.signal, setPending)
      if (!controller.signal.aborted) {
        setUploaded(file)
        void qc.invalidateQueries({ queryKey: ['project-files', projectId] })
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setFailure(error instanceof Error ? error.message : '文件上传失败，请重试。')
        setRetry(attempt)
      }
    } finally {
      transfer.current = null
      if (!controller.signal.aborted) setPending(null)
    }
  }

  return (
    <div className="space-y-2">
      <ErrorNotification message={failure ?? limits.error?.message} />
      <div className="flex flex-wrap items-center gap-2">
        <input type="file" ref={input} hidden autoComplete="off" aria-label="选择项目文件" disabled={pending !== null}
          onChange={(event) => {
            const file = event.currentTarget.files?.[0]
            event.currentTarget.value = ''
            if (file) void upload({ file, id: crypto.randomUUID() })
          }} />
        <Button type="button" size="sm" disabled={pending !== null} onClick={() => input.current?.click()}>上传文件</Button>
        {retry && <Button type="button" size="sm" variant="outline" onClick={() => void upload(retry)}>重试上传</Button>}
        {limits.data && <p className="text-xs text-muted-foreground">
          单文件上限 {bytes.format(limits.data.max_file_bytes)} 字节，项目配额 {bytes.format(limits.data.project_quota_bytes)} 字节
        </p>}
      </div>
      {pending !== null && <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <progress aria-label="项目文件上传进度" value={pending} max={100} />
        <span>{pending}%</span>
      </div>}
      {uploaded && <p role="status" className="text-sm">
        已上传 <Link to={uploaded.href} className="text-primary hover:underline">{uploaded.name}</Link>
      </p>}
    </div>
  )
}

function DeletedFileDetails({ projectId, fileId }: { projectId: string; fileId: string }) {
  const detail = useQuery({
    queryKey: ['project-file-trash', projectId, fileId],
    queryFn: async ({ signal }) => {
      const file = await api.get<DeletedFile>(`${projectFileApiPath(projectId, fileId)}/trash`, signal)
      if (file.project_id !== projectId || file.id !== fileId || !file.deleted_at) {
        throw new Error('无法读取此文件的回收站详情。')
      }
      return file
    },
    retry: false,
  })
  return (
    <div id={`deleted-file-${fileId}`} className="basis-full border-t pt-2">
      <ErrorNotification message={detail.error?.message} />
      {detail.isLoading && <p role="status" className="text-sm text-muted-foreground">加载文件详情…</p>}
      {detail.isError && (
        <Button type="button" size="sm" variant="outline" onClick={() => void detail.refetch()}>重试加载详情</Button>
      )}
      {detail.data && <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted-foreground">文件 ID</dt>
        <dd className="break-all">{detail.data.id}</dd>
        <dt className="text-muted-foreground">删除时间</dt>
        <dd><time dateTime={detail.data.deleted_at}>{new Date(detail.data.deleted_at).toLocaleString()}</time></dd>
        <dt className="text-muted-foreground">删除者</dt>
        <dd className="break-all">{detail.data.deleted_by ?? '未记录'}</dd>
      </dl>}
    </div>
  )
}

function FilesList({ projectId, canWrite, deleted }: { projectId: string; canWrite: boolean; deleted: boolean }) {
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [imagesOnly, setImagesOnly] = useState(false)
  const [selection, setSelection] = useState<{ projectId: string; fileId: string } | null>(null)
  const [restoring, setRestoring] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const { notify } = useNotification()
  const qc = useQueryClient()
  const base = projectResourceHref(projectId, 'files')
  const path = `/v2${base}`
  const list = useInfiniteQuery({
    queryKey: ['project-files', projectId, deleted, query, imagesOnly],
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ query, limit: '20' })
      if (deleted) params.set('state', 'deleted')
      if (imagesOnly) params.set('images_only', 'true')
      if (pageParam) params.set('cursor', pageParam)
      return api.get<Page<ProjectFileSummary>>(`${path}?${params}`, signal)
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    retry: false,
  })
  const files = list.data?.pages.flatMap((page) => page.items)
    .filter((file) => file.project_id === projectId && file.href === projectResourceHref(projectId, 'files', file.id)) ?? []
  const selectedId = deleted && selection?.projectId === projectId ? selection.fileId : null

  async function restore(file: ProjectFileSummary) {
    if (!canWrite || !deleted || restoring) return
    setRestoring(file.id)
    setActionError(null)
    try {
      await api.post(`${projectFileApiPath(projectId, file.id)}/restore`)
      setSelection((current) => current?.projectId === projectId && current.fileId === file.id ? null : current)
      qc.removeQueries({ queryKey: ['project-file-trash', projectId, file.id] })
      void qc.invalidateQueries({ queryKey: ['project-files', projectId] })
      void qc.invalidateQueries({ queryKey: ['project-file', projectId, file.id] })
      notify('文件已恢复。', 'success')
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '恢复文件失败，请重试。')
    } finally {
      setRestoring(null)
    }
  }

  return (
    <section className="mx-auto max-w-4xl space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <h1 className="text-xl font-semibold">{deleted ? '文件回收站' : '项目文件'}</h1>
        {canWrite && <Button asChild size="sm" variant="outline">
          <Link to={deleted ? base : `${base}?state=deleted`}>{deleted ? '返回文件' : '回收站'}</Link>
        </Button>}
      </header>
      {canWrite && !deleted && <ProjectFileUpload projectId={projectId} path={path} />}
      <form className="flex max-w-xl flex-wrap items-center gap-2" onSubmit={(event) => { event.preventDefault(); setQuery(input.trim()) }}>
        <Input aria-label="搜索文件名" autoComplete="off" className="min-w-36 flex-1"
          placeholder="搜索文件名" value={input} maxLength={255} onChange={(event) => setInput(event.currentTarget.value)} />
        <Button type="submit" size="sm" variant="outline">搜索</Button>
        <Button type="button" size="sm" variant={imagesOnly ? 'secondary' : 'outline'} aria-pressed={imagesOnly}
          onClick={() => setImagesOnly((value) => !value)}>只看图片</Button>
      </form>
      <ErrorNotification message={actionError ?? list.error?.message} />
      {list.isLoading && <p role="status" className="text-sm text-muted-foreground">加载文件…</p>}
      {!list.isLoading && !list.isError && files.length === 0 && (
        <p className="text-sm text-muted-foreground">{query || imagesOnly ? '没有符合条件的文件' : deleted ? '没有可恢复的文件' : '暂无项目文件'}</p>
      )}
      {list.isError && !list.isFetchNextPageError && (
        <Button type="button" size="sm" variant="outline" onClick={() => void list.refetch()}>重试加载</Button>
      )}
      {files.length > 0 && <ul className="divide-y rounded-lg border">
        {files.map((file) => (
          <li key={file.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
            <div className="min-w-0">
              {deleted ? <p className="break-all font-medium">{file.name}</p>
                : <Link to={file.href} className="break-all font-medium hover:underline">{file.name}</Link>}
              <p className="text-xs text-muted-foreground">{file.media_type} · {bytes.format(file.size)} 字节</p>
            </div>
            {deleted ? <div className="flex gap-2">
              <Button type="button" size="sm" variant="outline"
                aria-label={`查看 ${file.name} 详情`} aria-expanded={selectedId === file.id}
                aria-controls={selectedId === file.id ? `deleted-file-${file.id}` : undefined}
                onClick={() => setSelection(selectedId === file.id ? null : { projectId, fileId: file.id })}>
                {selectedId === file.id ? '收起详情' : '查看详情'}
              </Button>
              <Button type="button" size="sm" variant="outline" disabled={restoring !== null}
                aria-label={`恢复 ${file.name}`} onClick={() => void restore(file)}>{restoring === file.id ? '恢复中…' : '恢复'}</Button>
            </div>
              : <a href={projectFileContentUrl(projectId, file.id)} download className="shrink-0 text-sm text-primary hover:underline"
                aria-label={`下载 ${file.name}`}>下载</a>}
            {selectedId === file.id && <DeletedFileDetails projectId={projectId} fileId={file.id} />}
          </li>
        ))}
      </ul>}
      {list.hasNextPage && <Button type="button" size="sm" variant="outline" disabled={list.isFetchingNextPage}
        onClick={() => void list.fetchNextPage()}>
        {list.isFetchingNextPage ? '加载中…' : list.isFetchNextPageError ? '重试下一页' : '加载更多'}
      </Button>}
    </section>
  )
}

export function ProjectFilesPage() {
  const { routeProjectId, role } = useCurrentProject()
  const [params] = useSearchParams()
  if (!routeProjectId) return null
  const canWrite = role === 'owner' || role === 'editor'
  const deleted = params.get('state') === 'deleted'
  if (deleted && !canWrite) return <ErrorNotification message="没有权限访问文件回收站" />
  return <FilesList projectId={routeProjectId} canWrite={canWrite} deleted={deleted} />
}
