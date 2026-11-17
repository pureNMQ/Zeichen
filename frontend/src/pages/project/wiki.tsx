import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { MarkdownComposer } from '@/components/markdown-composer'
import { VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import { Textarea } from '@/components/ui/textarea'
import { ApiError, api } from '@/lib/api'
import { useCurrentProject } from '@/lib/current-project'
import { useDocumentNavigation } from '@/lib/document-navigation'
import { useProjectCompletion } from '@/lib/project-completion'
import { projectFileUpload } from '@/lib/project-files'
import { projectResourceHref } from '@/lib/project-links'
import { orderWikiTree, useWikiList, type WikiDocument, type WikiReceipt, type WikiScope, type WikiSummary } from '@/lib/project-wiki'
import { WikiLifecycle, WikiTrash, type WikiAction } from '@/pages/project/wiki-lifecycle'

function WikiIndex({ projectId, url, canWrite }: WikiScope) {
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const index = useWikiList<WikiSummary>(projectId, url, query)
  const documents = orderWikiTree(index.documents)

  return (
    <section className="mx-auto max-w-4xl space-y-5">
      <header className="flex items-start justify-between gap-2">
        <h1 className="text-xl font-semibold">Wiki</h1>
        {canWrite && <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline"><Link to="?mode=trash">回收站</Link></Button>
          <Button asChild size="sm"><Link to="?mode=new">新建 Wiki</Link></Button>
        </div>}
      </header>
      <form className="flex max-w-md items-center gap-2" onSubmit={(event) => { event.preventDefault(); setQuery(input.trim()) }}>
        <Input autoComplete="off" aria-label="搜索 Wiki" placeholder="搜索标题" maxLength={256} value={input}
          onChange={(event) => setInput(event.currentTarget.value)} />
        <Button type="submit" size="sm" variant="outline">搜索</Button>
      </form>
      <ErrorNotification message={index.error?.message} />
      {index.isLoading && <p role="status" className="text-sm text-muted-foreground">加载 Wiki…</p>}
      {!index.isLoading && !index.isError && documents.length === 0 && (
        <p className="text-sm text-muted-foreground">{query ? '没有符合条件的 Wiki' : '暂无 Wiki'}</p>
      )}
      {index.isError && !index.isFetchNextPageError && (
        <Button type="button" size="sm" variant="outline" onClick={() => void index.refetch()}>重试加载</Button>
      )}
      {documents.length > 0 && <ul className="divide-y rounded-lg border">
        {documents.map(({ document: wiki, depth }) => (
          <li key={wiki.id} className="space-y-1 p-3" style={{ paddingInlineStart: `${0.75 + Math.min(depth, 4) * 1.25}rem` }}>
            <Link to={projectResourceHref(projectId, 'wiki', wiki.id)} className="font-medium hover:underline">
              <span className="me-2 rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">{wiki.id}</span>
              {wiki.title}
            </Link>
            {wiki.summary && <p className="line-clamp-2 text-sm text-muted-foreground">{wiki.summary}</p>}
            {wiki.parent_id && !depth && <Link to={projectResourceHref(projectId, 'wiki', wiki.parent_id)}
              className="block text-xs text-muted-foreground hover:underline">上级 {wiki.parent_id}</Link>}
          </li>
        ))}
      </ul>}
      {index.hasNextPage && <Button type="button" size="sm" variant="outline" disabled={index.isFetchingNextPage}
        onClick={() => void index.fetchNextPage()}>
        {index.isFetchingNextPage ? '加载中…' : index.isFetchNextPageError ? '重试下一页' : '加载更多'}
      </Button>}
    </section>
  )
}

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
  const [pendingUrl, setPendingUrl] = useState<string | null>(null)
  const createAttempt = useRef<{ key: string; requestId: string } | null>(null)
  const navigation = useNavigate()
  const { registerBlocker } = useDocumentNavigation()
  const qc = useQueryClient()
  const lookup = useProjectCompletion(projectId)
  const indexHref = projectResourceHref(projectId, 'wiki')
  const cancelHref = document ? projectResourceHref(projectId, 'wiki', document.id) : indexHref
  const dirty = draft.title !== initial.title || draft.summary !== initial.summary || draft.category !== initial.category
    || draft.tags !== initial.tags || draft.body !== initial.body

  useEffect(() => {
    if (!dirty) return
    registerBlocker((href) => { setPendingUrl(href); return true })
    function beforeUnload(event: BeforeUnloadEvent) { event.preventDefault() }
    window.addEventListener('beforeunload', beforeUnload)
    return () => {
      registerBlocker(null)
      window.removeEventListener('beforeunload', beforeUnload)
    }
  }, [dirty, registerBlocker])

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
            onClick={() => dirty ? setPendingUrl(cancelHref) : navigation(cancelHref)}>取消</Button>
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
      <MarkdownComposer value={draft.body} onChange={(body) => change('body', body)} lookup={lookup} disabled={busy}
        upload={projectFileUpload(projectId)} onUploadPending={setUploading} />
      <Dialog open={pendingUrl !== null} onOpenChange={(open) => { if (!open) setPendingUrl(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>保留草稿？</DialogTitle>
            <DialogDescription>离开此页会放弃尚未保存的更改。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setPendingUrl(null)}>继续编辑</Button>
            <Button type="button" variant="destructive" onClick={() => { if (pendingUrl) navigation(pendingUrl) }}>放弃修改</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </form>
  )
}

function WikiReader({ projectId, url, canWrite, id, editing }: WikiScope & { id: string; editing: boolean }) {
  const [action, setAction] = useState<WikiAction | null>(null)
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
  const base = projectResourceHref(projectId, 'wiki')

  if (detail.isLoading) return <p role="status" className="text-sm text-muted-foreground">加载 Wiki…</p>
  if (detail.isError || !document) {
    return <>
      <Link to={base} className="text-sm text-primary hover:underline">返回 Wiki</Link>
      <ErrorNotification message={detail.error?.message ?? 'Wiki 不存在或无访问权限'} />
    </>
  }
  if (editing && canWrite) {
    return <WikiEditor key={id} projectId={projectId} url={url} canWrite={canWrite} document={document} parentId={document.parent_id} />
  }
  return (
    <article className="mx-auto max-w-4xl space-y-5">
      <Link to={base} className="text-sm text-primary hover:underline">返回 Wiki</Link>
      <header className="space-y-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h1 className="min-w-0 break-words text-2xl font-semibold">{document.title}</h1>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setAction('history')}>版本历史</Button>
            {canWrite && <>
              <Button asChild size="sm" variant="outline">
                <Link to={`${base}?mode=new&container_id=${encodeURIComponent(document.id)}`}>新建子 Wiki</Link>
              </Button>
              <Button size="sm" variant="outline" onClick={() => setAction('move')}>移动</Button>
              <Button size="sm" variant="outline" onClick={() => setAction('delete')}>删除</Button>
              <Button asChild size="sm"><Link to="?mode=edit">编辑</Link></Button>
            </>}
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
  const { routeProjectId, role } = useCurrentProject()
  const [params] = useSearchParams()
  if (!routeProjectId) return null
  const mode = params.get('mode')
  const scope: WikiScope = {
    projectId: routeProjectId,
    url: `/v2${projectResourceHref(routeProjectId, 'wiki')}`,
    canWrite: role === 'owner' || role === 'editor',
  }
  if (id) return <WikiReader key={id} {...scope} id={id} editing={mode === 'edit'} />
  if (mode === 'trash') return scope.canWrite
    ? <WikiTrash {...scope} selected={params.get('code')} />
    : <ErrorNotification message="没有权限访问 Wiki 回收站" />
  if (mode === 'new' && scope.canWrite) return <WikiEditor {...scope} parentId={params.get('container_id')} />
  return <WikiIndex {...scope} />
}
