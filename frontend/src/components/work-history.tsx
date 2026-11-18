import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type RequirementRow, type TaskRow } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { ErrorNotification } from '@/components/ui/notification'
import { VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { useCurrentPage } from '@/lib/use-current-page'

type Revision = {
  version: number
  title: string
  created_at: string
  actor_id: string | null
  actor_name: string | null
  actor_is_agent: boolean | null
  description?: string | null
}

function revisionAuthor(revision: Revision) {
  if (!revision.actor_name) return revision.actor_id ? '作者信息不可用' : '作者未记录'
  return revision.actor_is_agent ? `${revision.actor_name}（Agent）` : revision.actor_name
}

export function WorkHistory({ projectId, kind, item, canEdit }: {
  projectId: string; kind: 'requirements' | 'tasks'; item: RequirementRow | TaskRow; canEdit: boolean
}) {
  const base = `/projects/${projectId}/${kind}/${item.id}/versions`
  const [params, setParams] = useSearchParams()
  const requested = params.get('version') ?? ''
  const selected = /^[1-9]\d{0,9}$/.test(requested) ? Number(requested) : null
  function select(version: number | null) {
    setParams(prev => {
      const next = new URLSearchParams(prev)
      if (kind === 'requirements') next.set('tab', 'history')
      else next.set('taskTab', 'history')
      if (version) next.set('version', String(version))
      else next.delete('version')
      return next
    }, { replace:true })
  }
  const [compare, setCompare] = useState(false)
  const [busy, setBusy] = useState(false)
  const restoring = useRef(false)
  const isCurrentPage = useCurrentPage()
  const [error, setError] = useState('')
  const qc = useQueryClient()
  const history = useInfiniteQuery({
    queryKey: ['work-versions', base],
    queryFn: ({pageParam}) => api.get<{items: Revision[];next_before: number | null}>(base + (pageParam ? '?before=' + pageParam : '')),
    initialPageParam: null as number | null, getNextPageParam: page => page.next_before ?? undefined,
  })
  const revisions = history.data?.pages.flatMap(page => page.items) ?? []
  const current = revisions.find(v => v.version === item.version)
  const number = selected ?? item.version
  const revision = useQuery({
    queryKey: ['work-versions', base, number],
    queryFn: () => api.get<Revision>(base + '/' + number), enabled: !!number,
  })
  async function restore() {
    if (restoring.current || !canEdit || !number || !item.version) return
    restoring.current = true
    setBusy(true); setError('')
    try {
      await api.post(`${base}/${number}/restore`, { expected_version: item.version })
      await Promise.all(['work-versions','work-editor-source','task','requirement','requirements','requirement-tasks','requirement-timeline','project-files','project-file-usage'].map(
        key => qc.invalidateQueries({ queryKey: [key] }),
      ))
      if (isCurrentPage()) { select(null); setCompare(false) }
    } catch (e) {
      if (isCurrentPage()) setError(e instanceof Error ? e.message : '恢复版本失败')
    } finally { restoring.current = false; setBusy(false) }
  }
  return <section className="space-y-4" aria-label="历史版本">
    <ErrorNotification message={history.error?.message || revision.error?.message || error} />
    <div className="flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-2 text-sm">历史版本
        <select className="h-8 min-w-0 max-w-full rounded-md border bg-background px-2" value={number ?? ''} onChange={e => select(Number(e.target.value))}>
          {selected && !revisions.some(v => v.version === selected) && <option value={selected}>
            v{selected}{revision.data && ` · ${revisionAuthor(revision.data)}`}
          </option>}
          {revisions.map(v => <option value={v.version} key={v.version}>
            v{v.version} · {revisionAuthor(v)} · {new Date(v.created_at).toLocaleString()}{v.version === item.version ? '（当前）' : ''}
          </option>)}
        </select></label>
      {history.hasNextPage && <Button size="sm" variant="ghost" onClick={() => void history.fetchNextPage()}>更早版本</Button>}
      {number !== item.version && revision.data && <>
        <Button variant="outline" size="sm" aria-pressed={compare} onClick={() => setCompare(!compare)}>对照当前版本</Button>
        {canEdit && <Button size="sm" disabled={busy} onClick={() => void restore()}>恢复此版本</Button>}
      </>}
    </div>
    {revision.isLoading && <p role="status">加载版本…</p>}
    {revision.data && <div className={compare && number !== item.version ? 'grid gap-5 md:grid-cols-2' : ''}>
      <div className="min-w-0"><p className="break-words text-xs text-muted-foreground">v{number} · {revisionAuthor(revision.data)}</p><h2 className="my-2 font-semibold">{revision.data.title}</h2>
        <VditorMarkdownViewer markdown={revision.data.description ?? ''} /></div>
      {compare && number !== item.version && <div className="min-w-0"><p className="break-words text-xs text-muted-foreground">当前 · v{item.version}{current && ` · ${revisionAuthor(current)}`}</p>
        <h2 className="my-2 font-semibold">{item.title}</h2><VditorMarkdownViewer markdown={item.description ?? ''} /></div>}
    </div>}
  </section>
}
