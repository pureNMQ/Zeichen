import { useState, type ReactNode } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'

import { VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { ErrorNotification } from '@/components/ui/notification'
import { api } from '@/lib/api'
import { projectResourceHref } from '@/lib/project-links'
import { orderWikiTree, useWikiList, type WikiContent, type WikiDocument, type WikiReceipt, type WikiScope, type WikiSummary } from '@/lib/project-wiki'

export type WikiAction = 'history' | 'move' | 'delete'
type ActionProps = WikiScope & { document: WikiDocument; onClose: () => void }
type VersionSummary = { version: number; title: string; created_at: string }
type VersionPage = { items: VersionSummary[]; next_before: number | null }
type Snapshot = WikiContent & WikiReceipt
type DeleteImpact = WikiReceipt & { affected_count: number; sample: string[] }
type DeletedWiki = WikiSummary & { deleted_at: string }
type DeletedWikiDetail = DeletedWiki & { body: string }

function ActionDialog({ title, description, busy = false, onClose, children }: {
  title: string; description: string; busy?: boolean; onClose: () => void; children: ReactNode
}) {
  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose() }}>
    <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>
      {children}
    </DialogContent>
  </Dialog>
}

function DialogError({ message }: { message: string | null | undefined }) {
  return message ? <p role="alert" className="text-sm text-destructive">{message}</p> : null
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '操作失败，请重试。'
}

function documentEndpoint(url: string, documentId: string) {
  return `${url}/${encodeURIComponent(documentId)}`
}

function WikiHistory({ projectId, url, canWrite, document, onClose }: ActionProps) {
  const [expectedVersion] = useState(document.version)
  const [selected, setSelected] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()
  const path = `${documentEndpoint(url, document.id)}/versions`
  const versions = useInfiniteQuery({
    queryKey: ['wiki-v2', projectId, 'versions', document.id],
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: '20' })
      if (pageParam !== null) params.set('before', String(pageParam))
      return api.get<VersionPage>(`${path}?${params}`, signal)
    },
    initialPageParam: null as number | null,
    getNextPageParam: (page) => page.next_before,
    retry: false,
  })
  const snapshot = useQuery({
    queryKey: ['wiki-v2', projectId, 'snapshot', document.id, selected],
    queryFn: ({ signal }) => api.get<Snapshot>(`${path}/${selected}`, signal),
    enabled: selected !== null,
    retry: false,
  })
  const selectedDocument = snapshot.data?.project_id === projectId
    && snapshot.data.id === document.id && snapshot.data.version === selected ? snapshot.data : null

  async function restore() {
    if (!canWrite || busy || !selectedDocument || selectedDocument.version === expectedVersion) return
    setBusy(true)
    setError(null)
    try {
      await api.post(`${path}/${selectedDocument.version}/restore`, { expected_version: expectedVersion })
      void qc.invalidateQueries({ queryKey: ['wiki-v2', projectId] })
      onClose()
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <ActionDialog title="版本历史" description="恢复所选版本会创建一个新版本，原有版本仍保留。" busy={busy} onClose={onClose}>
      <DialogError message={error ?? versions.error?.message ?? snapshot.error?.message} />
      {versions.isLoading && <p role="status" className="text-sm text-muted-foreground">加载版本…</p>}
      {versions.isError && !versions.isFetchNextPageError && (
        <Button size="sm" variant="outline" onClick={() => void versions.refetch()}>重试版本列表</Button>
      )}
      <ul className="divide-y rounded-lg border">
        {versions.data?.pages.flatMap((page) => page.items).map((version) => (
          <li key={version.version}>
            <button type="button" disabled={busy} aria-pressed={version.version === selected}
              className="w-full px-3 py-2 text-left text-sm hover:bg-muted aria-pressed:bg-muted"
              onClick={() => { setError(null); setSelected(version.version) }}>
              版本 {version.version} · {version.title}
            </button>
          </li>
        ))}
      </ul>
      {versions.hasNextPage && <Button size="sm" variant="outline" disabled={busy || versions.isFetchingNextPage}
        onClick={() => void versions.fetchNextPage()}>
        {versions.isFetchingNextPage ? '加载中…' : versions.isFetchNextPageError ? '重试加载旧版本' : '加载旧版本'}
      </Button>}
      {snapshot.isLoading && <p role="status" className="text-sm text-muted-foreground">加载版本正文…</p>}
      {snapshot.isError && <Button size="sm" variant="outline" onClick={() => void snapshot.refetch()}>重试版本正文</Button>}
      {selectedDocument && !snapshot.isError && <section aria-label="所选版本" className="space-y-2 rounded-lg border p-3">
        <h3 className="font-medium">{selectedDocument.title}</h3>
        {selectedDocument.summary && <p className="text-sm text-muted-foreground">{selectedDocument.summary}</p>}
        {selectedDocument.category && <p className="text-sm text-muted-foreground">分类：{selectedDocument.category}</p>}
        {selectedDocument.tags.length > 0 && <p className="text-sm text-muted-foreground">标签：{selectedDocument.tags.join('、')}</p>}
        <VditorMarkdownViewer markdown={selectedDocument.body} />
      </section>}
      <DialogFooter>
        <Button type="button" variant="outline" disabled={busy} onClick={onClose}>关闭</Button>
        {canWrite && selectedDocument && !snapshot.isError && selectedDocument.version !== expectedVersion && (
          <Button type="button" disabled={busy} onClick={() => void restore()}>
            {busy ? '恢复中…' : `恢复到版本 ${selectedDocument.version}`}
          </Button>
        )}
      </DialogFooter>
    </ActionDialog>
  )
}

function WikiMove({ projectId, url, document, onClose }: ActionProps) {
  const [expectedVersion] = useState(document.version)
  const [parent, setParent] = useState<string | null>(document.parent_id)
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()
  const list = useWikiList<WikiSummary>(projectId, url, query)
  const descendants = new Set([document.id])
  for (const { document: candidate } of orderWikiTree(list.documents)) {
    if (candidate.parent_id && descendants.has(candidate.parent_id)) descendants.add(candidate.id)
  }
  const choices = list.documents.filter((candidate) => !descendants.has(candidate.id))

  async function move() {
    if (busy || parent === document.parent_id || (parent !== null && descendants.has(parent))) return
    setBusy(true)
    setError(null)
    try {
      await api.patch(`${documentEndpoint(url, document.id)}/location`, {
        expected_version: expectedVersion, parent_id: parent,
      })
      void qc.invalidateQueries({ queryKey: ['wiki-v2', projectId] })
      onClose()
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <ActionDialog title="移动 Wiki" description="选择新的上级 Wiki，或将此页移到顶层。" busy={busy} onClose={onClose}>
      <DialogError message={error ?? list.error?.message} />
      <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); setQuery(input.trim()) }}>
        <Input autoComplete="off" aria-label="搜索上级 Wiki" value={input} maxLength={256}
          onChange={(event) => setInput(event.currentTarget.value)} />
        <Button type="submit" size="sm" variant="outline" disabled={busy}>搜索</Button>
      </form>
      <div className="space-y-1">
        <Button type="button" size="sm" variant={parent === null ? 'secondary' : 'ghost'} disabled={busy}
          aria-pressed={parent === null} onClick={() => setParent(null)}>顶层</Button>
        {list.isLoading && <p role="status" className="text-sm text-muted-foreground">加载可选上级…</p>}
        {list.isError && !list.isFetchNextPageError && (
          <Button type="button" size="sm" variant="outline" onClick={() => void list.refetch()}>重试加载</Button>
        )}
        {choices.map((candidate) => (
          <Button key={candidate.id} type="button" variant={parent === candidate.id ? 'secondary' : 'ghost'}
            className="flex w-full min-w-0 justify-start" disabled={busy}
            aria-pressed={parent === candidate.id} onClick={() => setParent(candidate.id)}>
            <span className="truncate">{candidate.id} · {candidate.title}</span>
          </Button>
        ))}
      </div>
      {list.hasNextPage && (
        <Button type="button" size="sm" variant="outline" disabled={busy || list.isFetchingNextPage}
          onClick={() => void list.fetchNextPage()}>
          {list.isFetchingNextPage ? '加载中…' : list.isFetchNextPageError ? '重试加载' : '加载更多上级'}
        </Button>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" disabled={busy} onClick={onClose}>取消</Button>
        <Button type="button" disabled={busy || parent === document.parent_id} onClick={() => void move()}>
          {busy ? '移动中…' : '确认移动'}
        </Button>
      </DialogFooter>
    </ActionDialog>
  )
}

function WikiDelete({ projectId, url, document, onClose }: ActionProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const path = documentEndpoint(url, document.id)
  const impact = useQuery({
    queryKey: ['wiki-v2', projectId, 'delete-impact', document.id],
    queryFn: ({ signal }) => api.get<DeleteImpact>(`${path}/delete-impact`, signal),
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
    retry: false,
  })
  const result = impact.data?.project_id === projectId && impact.data.id === document.id ? impact.data : null

  async function remove() {
    if (busy || !result || impact.isFetching || impact.isError || error) return
    setBusy(true)
    try {
      await api.delete(`${path}?confirmed_count=${result.affected_count}`)
      qc.removeQueries({ queryKey: ['wiki-v2', projectId, 'detail', document.id] })
      void qc.invalidateQueries({ queryKey: ['wiki-v2', projectId] })
      navigate(projectResourceHref(projectId, 'wiki'), { replace: true })
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <ActionDialog title="删除 Wiki" description={document.title} busy={busy} onClose={onClose}>
      {impact.isFetching && <p role="status" className="text-sm text-muted-foreground">检查删除影响…</p>}
      {result && !impact.isFetching && !impact.isError && <div className="space-y-2 text-sm">
        <p>会影响 {result.affected_count} 篇 Wiki。删除后可在回收站恢复。</p>
        {result.sample.length > 0 && <p className="break-words text-muted-foreground">{result.sample.join('、')}</p>}
      </div>}
      <DialogError message={error ?? impact.error?.message} />
      {(error || impact.isError) && (
        <Button size="sm" variant="outline" disabled={impact.isFetching} onClick={() => { setError(null); void impact.refetch() }}>
          重新检查影响
        </Button>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" disabled={busy} onClick={onClose}>取消</Button>
        <Button type="button" variant="destructive" disabled={busy || !!error || !result || impact.isFetching || impact.isError}
          onClick={() => void remove()}>{busy ? '删除中…' : '确认删除'}</Button>
      </DialogFooter>
    </ActionDialog>
  )
}

export function WikiLifecycle({ action, ...props }: ActionProps & { action: WikiAction }) {
  if (action === 'history') return <WikiHistory {...props} />
  if (!props.canWrite) return null
  return action === 'move' ? <WikiMove {...props} /> : <WikiDelete {...props} />
}

export function WikiTrash({ projectId, url, selected }: WikiScope & { selected: string | null }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const base = projectResourceHref(projectId, 'wiki')
  const list = useWikiList<DeletedWiki>(projectId, `${url}/trash`, '', 'trash')
  const detail = useQuery({
    queryKey: ['wiki-v2', projectId, 'trash-detail', selected],
    queryFn: ({ signal }) => api.get<DeletedWikiDetail>(`${url}/trash/${encodeURIComponent(selected!)}`, signal),
    enabled: !!selected,
    retry: false,
  })
  const document = detail.data?.project_id === projectId && detail.data.id === selected ? detail.data : null

  async function restore() {
    if (!document || busy) return
    setBusy(true)
    setError(null)
    try {
      const receipt = await api.post<WikiReceipt>(`${url}/trash/${encodeURIComponent(document.id)}/restore`)
      if (receipt.project_id !== projectId || receipt.id !== document.id) throw new Error('恢复结果与所选 Wiki 不一致。')
      void qc.invalidateQueries({ queryKey: ['wiki-v2', projectId] })
      navigate(projectResourceHref(projectId, 'wiki', receipt.id), { replace: true })
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="mx-auto max-w-4xl space-y-4">
      <Link to={base} className="text-sm text-primary hover:underline">返回 Wiki</Link>
      <h1 className="text-xl font-semibold">Wiki 回收站</h1>
      <ErrorNotification message={error ?? list.error?.message ?? detail.error?.message} />
      {list.isLoading && <p role="status" className="text-sm text-muted-foreground">加载回收站…</p>}
      {list.isError && !list.isFetchNextPageError && (
        <Button size="sm" variant="outline" onClick={() => void list.refetch()}>重试回收站</Button>
      )}
      {!list.isLoading && !list.isError && list.documents.length === 0 && <p className="text-sm text-muted-foreground">回收站为空</p>}
      {list.documents.length > 0 && <ul className="divide-y rounded-lg border">
        {list.documents.map((item) => (
          <li key={item.id} className="flex flex-wrap justify-between gap-2 px-3 py-2">
            <Link to={`?mode=trash&code=${encodeURIComponent(item.id)}`} className="text-sm font-medium hover:underline"
              aria-current={item.id === selected ? 'page' : undefined} onClick={() => setError(null)}>
              {item.id} · {item.title}
            </Link>
            <time dateTime={item.deleted_at} className="text-xs text-muted-foreground">{new Date(item.deleted_at).toLocaleString()}</time>
          </li>
        ))}
      </ul>}
      {list.hasNextPage && <Button type="button" size="sm" variant="outline" disabled={list.isFetchingNextPage}
        onClick={() => void list.fetchNextPage()}>
        {list.isFetchingNextPage ? '加载中…' : list.isFetchNextPageError ? '重试加载' : '加载更多'}
      </Button>}
      {detail.isLoading && <p role="status" className="text-sm text-muted-foreground">加载已删除的 Wiki…</p>}
      {document && !detail.isError && (
        <article className="space-y-3 rounded-lg border p-4">
          <div className="flex flex-wrap justify-between gap-2">
            <h2 className="font-semibold">{document.title}</h2>
            <Button type="button" size="sm" disabled={busy} onClick={() => void restore()}>
              {busy ? '恢复中…' : '恢复 Wiki'}
            </Button>
          </div>
          {document.parent_id && <p className="text-sm text-muted-foreground">原上级：{document.parent_id}</p>}
          <VditorMarkdownViewer markdown={document.body} />
        </article>
      )}
    </section>
  )
}
