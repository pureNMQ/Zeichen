import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'

import { MarkdownComposer, type CompletionCandidate } from '@/components/markdown-composer'
import { VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { Button } from '@/components/ui/button'
import { ErrorNotification } from '@/components/ui/notification'
import { api, STATUS_LABEL, type Page, type WorkflowStatus } from '@/lib/api'
import { useProjectCompletion } from '@/lib/project-completion'
import { projectFileUpload } from '@/lib/project-files'
import { projectResourceHref } from '@/lib/project-links'

type TimelineReply = {
  entry_id: string
  kind: 'manual' | 'system'
  withdrawn: boolean
  body_preview: string | null
  event_type: string | null
}

type TimelineEntry = {
  id: string
  project_id: string
  requirement_id: string
  kind: 'manual' | 'system'
  actor_id: string | null
  occurred_at: string
  source_task: string | null
  reply_to: TimelineReply | null
  revised: boolean
  withdrawn: boolean
  event_type: string | null
  event_data: Record<string, unknown> | null
  body_preview: string | null
}

type EntryDetail = Omit<TimelineEntry, 'body_preview'> & { body: string | null }
type ContextWindow = { anchor_id: string; items: TimelineEntry[] }
type AppendInput = { body: string; replyTo: string | null; requestId: string }

const dateFormat = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })

function eventLabel(eventType: string | null) {
  switch (eventType) {
    case 'requirement.status_changed': return '变更需求状态'
    case 'task.status_changed': return '变更任务状态'
    case 'task.claimed': return '认领任务'
    default: return '系统记录'
  }
}

function statusChange(data: TimelineEntry['event_data'], eventType: string | null) {
  if (eventType !== 'requirement.status_changed' && eventType !== 'task.status_changed') return null
  const before = data?.before
  const after = data?.after
  if (typeof before !== 'string' || typeof after !== 'string') return null
  if (!Object.hasOwn(STATUS_LABEL, before) || !Object.hasOwn(STATUS_LABEL, after)) return null
  return `${STATUS_LABEL[before as WorkflowStatus]} → ${STATUS_LABEL[after as WorkflowStatus]}`
}

function replyLabel(reply: TimelineReply) {
  if (reply.withdrawn) return '原记录已撤回'
  return reply.kind === 'system' ? eventLabel(reply.event_type) : reply.body_preview ?? '原记录'
}

function TimelineActor({ projectId, actorId }: { projectId: string; actorId: string | null }) {
  const path = actorId ? projectResourceHref(projectId, 'people', actorId) : null
  const { data: person, isError } = useQuery({
    queryKey: ['project-person', projectId, actorId],
    queryFn: ({ signal }) => api.get<CompletionCandidate>(path!, signal),
    enabled: !!path,
    staleTime: 60_000,
    retry: false,
  })
  if (!path) return <span>系统</span>
  if (isError || !person || person.href !== path) return <span>历史人员</span>
  return <Link to={path} className="font-medium hover:underline">{person.label}</Link>
}

function TimelineRecord({
  entry, projectId, url, queryKey, focused, linkToEntry, onReply,
}: {
  entry: TimelineEntry
  projectId: string
  url: string
  queryKey: readonly string[]
  focused: boolean
  linkToEntry: (entryId: string) => string
  onReply?: (entry: TimelineEntry) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const showBody = !entry.withdrawn && entry.kind === 'manual' && (expanded || focused)
  const detail = useQuery({
    queryKey: [...queryKey, 'detail', entry.id],
    queryFn: ({ signal }) => api.get<EntryDetail>(`${url}/${encodeURIComponent(entry.id)}`, signal),
    enabled: showBody,
    retry: false,
  })
  const currentDetail = detail.data?.project_id === entry.project_id
    && detail.data.requirement_id === entry.requirement_id && detail.data.id === entry.id
    ? detail.data
    : null
  const body = detail.isError || currentDetail?.withdrawn ? null : currentDetail?.body
  const status = statusChange(entry.event_data, entry.event_type)

  return (
    <li
      id={`timeline-${entry.id}`}
      tabIndex={focused ? -1 : undefined}
      className={`space-y-2 rounded-lg border px-3 py-2.5 ${focused ? 'border-ring' : ''}`}
    >
      <div className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
        <TimelineActor projectId={projectId} actorId={entry.actor_id} />
        <time dateTime={entry.occurred_at}>{dateFormat.format(new Date(entry.occurred_at))}</time>
        {entry.revised && !entry.withdrawn && <span>已修订</span>}
        {entry.source_task && <Link className="hover:underline" to={projectResourceHref(projectId, 'tasks', entry.source_task)}>
          {entry.source_task}
        </Link>}
      </div>
      {entry.reply_to && <Link
        to={linkToEntry(entry.reply_to.entry_id)}
        className="block max-w-full truncate border-s-2 border-border ps-2 text-sm text-muted-foreground hover:underline"
      >
        回复：{replyLabel(entry.reply_to)}
      </Link>}
      {entry.withdrawn || currentDetail?.withdrawn ? <p className="text-sm text-muted-foreground">此记录已撤回</p>
        : entry.kind === 'system' ? <p className="text-sm">
          {typeof entry.event_data?.summary === 'string' ? entry.event_data.summary : eventLabel(entry.event_type)}
          {status && ` · ${status}`}
        </p>
          : showBody && body !== undefined && body !== null ? <VditorMarkdownViewer markdown={body} />
            : <p className="whitespace-pre-wrap break-words text-sm">{entry.body_preview}</p>}
      <ErrorNotification message={detail.isError && showBody ? '无法读取记录正文，请重试。' : null} />
      <div className="flex flex-wrap items-center gap-2">
        {showBody && detail.isFetching && <span role="status" className="text-xs text-muted-foreground">加载正文…</span>}
        {showBody && detail.isError && <Button type="button" size="sm" variant="ghost" onClick={() => void detail.refetch()}>重试正文</Button>}
        {!entry.withdrawn && entry.kind === 'manual' && !focused && (
          <Button type="button" size="sm" variant="ghost" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
            {expanded ? '收起正文' : '展开正文'}
          </Button>
        )}
        {onReply && <Button type="button" size="sm" variant="ghost" onClick={() => onReply(entry)}>回复</Button>}
        {!focused && <Link to={linkToEntry(entry.id)} className="text-xs text-muted-foreground hover:underline">定位记录</Link>}
      </div>
    </li>
  )
}

export function RequirementTimeline({ projectId, requirementId, canWrite }: {
  projectId: string
  requirementId: string
  canWrite: boolean
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const anchor = searchParams.get('entry')
  const queryKey = ['requirement-timeline', projectId, requirementId] as const
  const url = `${projectResourceHref(projectId, 'requirements', requirementId)}/timeline`
  const lookup = useProjectCompletion(projectId)
  const qc = useQueryClient()
  const [draft, setDraft] = useState('')
  const [reply, setReply] = useState<TimelineEntry | null>(null)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const previousRequest = useRef<AppendInput | null>(null)

  const history = useInfiniteQuery({
    queryKey: [...queryKey, 'history'],
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: '20' })
      if (pageParam) params.set('cursor', pageParam)
      return api.get<Page<TimelineEntry>>(`${url}?${params}`, signal)
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled: !anchor,
    retry: false,
  })
  const context = useQuery({
    queryKey: [...queryKey, 'context', anchor],
    queryFn: ({ signal }) => api.get<ContextWindow>(`${url}/${encodeURIComponent(anchor!)}/context`, signal),
    enabled: !!anchor,
    retry: false,
  })
  const contextAnchor = context.isError ? null : context.data?.anchor_id
  useEffect(() => {
    if (anchor && contextAnchor === anchor) {
      document.getElementById(`timeline-${anchor}`)?.focus()
    }
  }, [anchor, contextAnchor])

  function paramsForEntry(entryId: string | null) {
    const params = new URLSearchParams(searchParams)
    if (entryId) params.set('entry', entryId)
    else params.delete('entry')
    return params
  }

  function selectReply(entry: TimelineEntry) {
    setReply(entry)
    document.getElementById('timeline-draft')?.focus()
  }

  async function append(event: FormEvent) {
    event.preventDefault()
    if (!canWrite || saving || uploading || !draft.trim()) return
    const replyTo = reply?.id ?? null
    const prior = previousRequest.current
    const requestId = prior?.body === draft && prior.replyTo === replyTo ? prior.requestId : crypto.randomUUID()
    previousRequest.current = { body: draft, replyTo, requestId }
    setSaving(true)
    setSaveError(null)
    try {
      const receipt = await api.post<{ entry_id: string }>(url, {
        body: draft,
        reply_to: replyTo,
        request_id: requestId,
      })
      previousRequest.current = null
      setDraft('')
      setReply(null)
      setSearchParams((current) => {
        const params = new URLSearchParams(current)
        params.set('entry', receipt.entry_id)
        return params
      }, { replace: true })
      void qc.invalidateQueries({ queryKey })
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : '无法保存时间轴记录，请重试。')
    } finally {
      setSaving(false)
    }
  }

  const entries = anchor
    ? contextAnchor === anchor ? context.data?.items ?? [] : []
    : history.data?.pages.flatMap((page) => page.items) ?? []
  const visibleEntries = entries.filter((entry) => entry.project_id === projectId && entry.requirement_id === requirementId)
  const isLoading = anchor ? context.isLoading : history.isLoading
  const loadError = anchor ? context.error : history.error

  return (
    <section className="space-y-3" aria-label="时间轴">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">时间轴</h2>
        {anchor && <Button type="button" size="sm" variant="outline" onClick={() => setSearchParams(paramsForEntry(null))}>返回最新记录</Button>}
      </div>
      <ErrorNotification message={loadError instanceof Error ? loadError.message : null} />
      {canWrite && <form onSubmit={(event) => void append(event)} className="space-y-2">
        <ErrorNotification message={saveError} />
        {reply && <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="min-w-0 truncate">回复：{replyLabel({ ...reply, entry_id: reply.id })}</span>
          <Button type="button" size="sm" variant="ghost" disabled={saving || uploading} onClick={() => setReply(null)}>取消回复</Button>
        </div>}
        <MarkdownComposer id="timeline-draft" label="时间轴正文" value={draft} onChange={setDraft} lookup={lookup} disabled={saving}
          upload={projectFileUpload(projectId)} onUploadPending={setUploading} />
        <Button type="submit" size="sm" disabled={saving || uploading || !draft.trim()}>
          {saving ? '发布中…' : reply ? '发布回复' : '发布记录'}
        </Button>
      </form>}
      {isLoading && <p role="status" className="text-sm text-muted-foreground">加载时间轴…</p>}
      {!isLoading && !loadError && !visibleEntries.length && <p className="text-sm text-muted-foreground">暂无记录</p>}
      {loadError && (anchor || !history.isFetchNextPageError) && (
        <Button type="button" size="sm" variant="outline" onClick={() => void (anchor ? context.refetch() : history.refetch())}>重试加载</Button>
      )}
      <ol className="space-y-2">
        {visibleEntries.map((entry) => <TimelineRecord
          key={entry.id}
          entry={entry}
          projectId={projectId}
          url={url}
          queryKey={queryKey}
          focused={entry.id === anchor}
          linkToEntry={(entryId) => `?${paramsForEntry(entryId)}`}
          onReply={canWrite && !saving && !uploading ? selectReply : undefined}
        />)}
      </ol>
      {!anchor && history.hasNextPage && <Button type="button" variant="outline" size="sm"
        disabled={history.isFetchingNextPage}
        onClick={() => void history.fetchNextPage()}>
        {history.isFetchingNextPage ? '加载中…' : history.isFetchNextPageError ? '重试加载较早记录' : '加载较早记录'}
      </Button>}
    </section>
  )
}
