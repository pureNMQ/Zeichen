import { MarkdownBacklinks } from '@/components/markdown-backlinks'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ListTree, MoreHorizontal } from 'lucide-react'
import { Link, useBlocker, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { MarkdownComposer } from '@/components/markdown-composer'
import { VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { RelatedFiles } from '@/components/attachment-list'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import { Textarea } from '@/components/ui/textarea'
import { ApiError, api } from '@/lib/api'
import { useCurrentProject } from '@/lib/current-project'
import { useProjectCompletion } from '@/lib/project-completion'
import { projectFileUpload } from '@/lib/project-files'
import { projectResourceHref } from '@/lib/project-links'
import type { WikiDocument, WikiReceipt, WikiScope } from '@/lib/project-wiki'
import { cn } from '@/lib/utils'
import { WikiDirectory } from '@/pages/project/wiki-directory'
import { WikiLifecycle, WikiTrash, type WikiAction } from '@/pages/project/wiki-lifecycle'

function WikiEditor({ projectId, url, document, parentId }: WikiScope & {
  document?: WikiDocument
  parentId: string | null
}) {
  const [initial] = useState(() => ({
    version: document?.version,
    title: document?.title ?? '',
    summary: document?.summary ?? '',
    category: document?.category ?? '',
    tags: document?.tags.join(', ') ?? '',
    body: document?.body ?? '',
  }))
  const [draft, setDraft] = useState(() => ({ ...initial }))
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const createAttempt = useRef<{ key: string; requestId: string } | null>(null)
  const saved = useRef(false)
  const navigation = useNavigate()
  const qc = useQueryClient()
  const lookup = useProjectCompletion(projectId)
  const indexHref = projectResourceHref(projectId, 'wiki')
  const cancelHref = document ? projectResourceHref(projectId, 'wiki', document.id) : indexHref
  const dirty = draft.title !== initial.title || draft.summary !== initial.summary || draft.category !== initial.category
    || draft.tags !== initial.tags || draft.body !== initial.body
  const blocker = useBlocker(({ currentLocation, nextLocation, historyAction }) => !saved.current && dirty && (
    historyAction === 'POP' || currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search
  ))

  useEffect(() => {
    if (!dirty) return
    function beforeUnload(event: BeforeUnloadEvent) {
      if (saved.current) return
      event.preventDefault()
      event.returnValue = true
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => {
      window.removeEventListener('beforeunload', beforeUnload)
    }
  }, [dirty])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (busy || uploading || !draft.title.trim()) return
    const fields = {
      title: draft.title.trim(),
      summary: draft.summary.trim() || null,
      category: draft.category.trim() || null,
      tags: [...new Set(draft.tags.split(/[,，\n]/u).map((tag) => tag.trim()).filter(Boolean))],
      body: draft.body,
    }
    setBusy(true)
    setError(null)
    try {
      let receipt: WikiReceipt
      if (document) {
        const patch = {
          ...(draft.title !== initial.title && { title: fields.title }),
          ...(draft.summary !== initial.summary && { summary: fields.summary }),
          ...(draft.category !== initial.category && { category: fields.category }),
          ...(draft.tags !== initial.tags && { tags: fields.tags }),
          ...(draft.body !== initial.body && { body: fields.body }),
        }
        receipt = await api.patch<WikiReceipt>(`${url}/${encodeURIComponent(document.id)}`, {
          expected_version: initial.version, patch,
        })
      } else {
        const payload = { ...fields, parent_id: parentId }
        const key = JSON.stringify(payload)
        const attempt = createAttempt.current?.key === key ? createAttempt.current : { key, requestId: crypto.randomUUID() }
        createAttempt.current = attempt
        receipt = await api.post<WikiReceipt>(url, { ...payload, request_id: attempt.requestId })
      }
      if (receipt.project_id !== projectId || (document && receipt.id !== document.id)) {
        throw new Error('返回的 Wiki 与正在编辑的页面不一致。')
      }
      saved.current = true
      void qc.invalidateQueries({ queryKey: ['wiki-v2', projectId] })
      navigation(projectResourceHref(projectId, 'wiki', receipt.id), { replace: true })
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 409 && document
        ? `${failure.message}。草稿已保留。`
        : failure instanceof Error ? failure.message : '保存 Wiki 失败，请重试。')
    } finally {
      setBusy(false)
    }
  }

  function change(field: 'title' | 'summary' | 'category' | 'tags' | 'body', value: string) {
    setDraft((current) => ({ ...current, [field]: value }))
  }

  return (
    <form className="mx-auto max-w-4xl space-y-4" onSubmit={(event) => void save(event)}>
      <ErrorNotification message={error} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">{document ? '编辑 Wiki' : '新建 Wiki'}</h1>
        <div className="flex gap-1">
          {document && error && <a href={cancelHref} target="_blank" rel="noopener noreferrer" className="self-center px-2 text-sm hover:underline">查看当前版本</a>}
          <Button type="button" size="sm" variant="outline" disabled={busy || uploading}
            onClick={() => navigation(cancelHref)}>取消</Button>
          <Button type="submit" size="sm" disabled={busy || uploading || !draft.title.trim() || (!!document && !dirty)}>
            {busy ? '保存中…' : '保存'}
          </Button>
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="wiki-v2-title">标题</Label>
        <Input id="wiki-v2-title" autoComplete="off" required maxLength={256} disabled={busy}
          value={draft.title} onChange={(event) => change('title', event.currentTarget.value)} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="wiki-v2-category">分类</Label>
          <Input id="wiki-v2-category" autoComplete="off" disabled={busy}
            value={draft.category} onChange={(event) => change('category', event.currentTarget.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="wiki-v2-tags">标签</Label>
          <Input id="wiki-v2-tags" autoComplete="off" disabled={busy} placeholder="用逗号分隔"
            value={draft.tags} onChange={(event) => change('tags', event.currentTarget.value)} />
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="wiki-v2-summary">摘要</Label>
        <Textarea id="wiki-v2-summary" autoComplete="off" disabled={busy}
          value={draft.summary} onChange={(event) => change('summary', event.currentTarget.value)} />
      </div>
      <MarkdownComposer className="[--writing-height:18rem]" value={draft.body} onChange={(body) => change('body', body)} lookup={lookup} disabled={busy}
        upload={projectFileUpload(projectId)} onUploadPending={setUploading} />
      <Dialog open={blocker.state === 'blocked'} onOpenChange={(open) => { if (!open) blocker.reset?.() }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>保留草稿？</DialogTitle>
            <DialogDescription>离开此页会放弃尚未保存的更改。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => blocker.reset?.()}>继续编辑</Button>
            <Button type="button" variant="destructive" disabled={busy || uploading} onClick={() => blocker.proceed?.()}>放弃修改</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </form>
  )
}

function WikiReader({ projectId, url, canWrite, id, editing }: WikiScope & { id: string; editing: boolean }) {
  const [action, setAction] = useState<WikiAction | null>(null)
  const location = useLocation()
  const heading = useRef<HTMLHeadingElement>(null)
  const [params, setParams] = useSearchParams()
  const rawVersion = params.get('version') ?? ''
  const version = /^[1-9][0-9]{0,9}$/u.test(rawVersion) && Number(rawVersion) <= 2_147_483_647
    ? Number(rawVersion) : undefined
  const visibleAction = version ? 'history' : action
  const detail = useQuery({
    queryKey: ['wiki-v2', projectId, 'detail', id],
    queryFn: ({ signal }) => api.get<WikiDocument>(`${url}/${encodeURIComponent(id)}`, signal),
    retry: false,
  })
  const document = detail.data?.project_id === projectId && detail.data.id === id ? detail.data : null
  const documentId = document?.id
  const base = projectResourceHref(projectId, 'wiki')
  useEffect(() => {
    if (documentId && !editing && location.state?.focusWikiHeading && window.matchMedia?.('(width < 48rem)').matches) {
      heading.current?.focus({ preventScroll: true })
    }
  }, [documentId, editing, location.key, location.state])

  if (detail.isLoading) return <p role="status" className="text-sm text-muted-foreground">加载 Wiki…</p>
  if (detail.isError || !document) {
    return <>
      <div className="flex items-center gap-3">
        <Link to={base} className="text-sm text-primary hover:underline">返回 Wiki</Link>
        {detail.isError && <Button variant="outline" size="sm" onClick={() => void detail.refetch()} disabled={detail.isFetching}>重试加载</Button>}
      </div>
      <ErrorNotification message={detail.error?.message ?? 'Wiki 不存在或无访问权限'} />
    </>
  }
  if (editing && canWrite) {
    return <WikiEditor key={id} projectId={projectId} url={url} canWrite={canWrite} document={document} parentId={document.parent_id} />
  }
  return (
    <article className="mx-auto max-w-4xl space-y-5">
      <header className="space-y-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h1 ref={heading} tabIndex={-1} className="min-w-0 wrap-anywhere text-2xl font-semibold focus:outline-none">{document.title}</h1>
          <div className="flex shrink-0 gap-2">
            {canWrite ? <>
              <Button asChild size="sm"><Link to="?mode=edit">编辑</Link></Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="icon-sm" aria-label="更多 Wiki 操作"><MoreHorizontal /></Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => setAction('history')}>版本历史</DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <Link to={`${base}?mode=new&container_id=${encodeURIComponent(document.id)}`}>新建子 Wiki</Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setAction('move')}>移动</DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem variant="destructive" onSelect={() => setAction('delete')}>删除</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </> : <Button size="sm" variant="outline" onClick={() => setAction('history')}>版本历史</Button>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2 text-sm text-muted-foreground">
          <span>{document.id} · 版本 {document.version}</span>
          {document.parent_id && <Link to={projectResourceHref(projectId, 'wiki', document.parent_id)}
            className="hover:underline">上级 {document.parent_id}</Link>}
          {document.category && <span>{document.category}</span>}
          {document.tags.map((tag) => <span key={tag} className="rounded bg-muted px-1.5">{tag}</span>)}
        </div>
        {document.summary && <p className="whitespace-pre-wrap text-sm text-muted-foreground">{document.summary}</p>}
      </header>
      <VditorMarkdownViewer markdown={document.body} />
      <MarkdownBacklinks projectId={projectId} kind="wiki" id={document.id} />
      <RelatedFiles key={`${projectId}:${document.id}`} projectId={projectId} targetKind="wiki" targetId={document.id} canEdit={canWrite} />
      {visibleAction && <WikiLifecycle key={version ?? visibleAction} action={visibleAction} projectId={projectId} url={url}
        canWrite={canWrite} document={document} initialVersion={version} onClose={() => {
          setAction(null)
          if (version) setParams((current) => {
            const next = new URLSearchParams(current)
            next.delete('version')
            return next
          }, { replace: true })
        }} />}
    </article>
  )
}

export function ProjectWikiPage() {
  const { id } = useParams()
  const { key: locationKey } = useLocation()
  const { routeProjectId, role } = useCurrentProject()
  const [params] = useSearchParams()
  const [mobileDirectory, setMobileDirectory] = useState<string | null>(null)
  if (!routeProjectId) return null
  const mode = params.get('mode')
  const scope: WikiScope = {
    projectId: routeProjectId,
    url: `/v2${projectResourceHref(routeProjectId, 'wiki')}`,
    canWrite: role === 'owner' || role === 'editor',
  }
  const parentId = params.get('container_id')
  const creating = mode === 'new' && scope.canWrite
  const index = !id && !creating && mode !== 'trash'
  const showDirectory = index || mobileDirectory === locationKey
  let content
  if (id) content = <WikiReader {...scope} id={id} editing={mode === 'edit'} />
  else if (mode === 'trash') content = scope.canWrite
    ? <WikiTrash {...scope} selected={params.get('code')} />
    : <ErrorNotification message="没有权限访问 Wiki 回收站" />
  else if (creating) content = <WikiEditor key={parentId} {...scope} parentId={parentId} />

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col md:flex-row">
      {!index && <div className="shrink-0 border-b px-3 py-1 md:hidden">
        <Button type="button" size="sm" variant="ghost" aria-controls="wiki-directory" aria-expanded={showDirectory}
          onClick={() => setMobileDirectory(showDirectory ? null : locationKey)}>
          <ListTree aria-hidden="true" />Wiki 目录
        </Button>
      </div>}
      <WikiDirectory {...scope} selectedId={id} visibleOnMobile={showDirectory}
        className={cn('md:flex md:max-h-none md:w-60 md:shrink-0 md:border-e lg:w-72',
          showDirectory ? 'flex' : 'hidden', index ? 'flex-1 md:flex-none' : 'max-h-[45dvh] shrink-0 border-b md:border-b-0')} />
      <div key={id ?? mode} className={cn('min-h-0 min-w-0 flex-1 overflow-auto p-3 sm:p-6', index && 'hidden md:block')}>
        {content}
      </div>
    </div>
  )
}
