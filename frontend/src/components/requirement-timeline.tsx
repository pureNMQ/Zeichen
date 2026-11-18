import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { Activity, CirclePlus, GitPullRequestArrow, History, Link2, MessageSquare, Pencil,
  Reply, RotateCcw, SquareStack, Trash2, UserCheck, UserMinus, UserPlus } from 'lucide-react'

import { MarkdownComposer, type CompletionCandidate } from '@/components/markdown-composer'
import { UserAvatar } from '@/components/user-avatar'
import { TimelineFilterForm, type TimelineFilters, type TimelineTask } from '@/components/timeline-filters'
import { VditorMarkdownViewer } from '@/components/vditor-ir-editor'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ErrorNotification } from '@/components/ui/notification'
import { api, STATUS_LABEL, type Page, type WorkflowStatus } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { useProjectCompletion } from '@/lib/project-completion'
import { projectFileUpload } from '@/lib/project-files'
import { projectResourceHref } from '@/lib/project-links'

type TimelineReply = {
  entry_id: string
  actor_name?: string | null
  revised?: boolean
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
  actor_name?: string | null
  actor_avatar?: string | null
  actor_is_agent?: boolean
  occurred_at: string
  source_task: string | null
  reply_to: TimelineReply | null
  revised: boolean
  withdrawn: boolean
  version: number | null
  event_type: string | null
  event_data: Record<string, unknown> | null
  body_preview: string | null
}

type EntryDetail = Omit<TimelineEntry, 'body_preview'> & { body: string | null }
type ContextWindow = { anchor_id: string; items: TimelineEntry[] }
type AppendInput = { body: string; replyTo: string | null; sourceTask: string; requestId: string }

const dateFormat = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })

type Revision = { version: number; kind: string; body: string | null; reason: string | null; created_at: string; actor_name: string | null }

function TimelineRevisionPreview({ endpoint, version }: { endpoint: string; version: string }) {
  const result = useQuery({
    queryKey: ['timeline-revision', endpoint, version],
    queryFn: ({ signal }) => api.get<Revision>(`${endpoint}/revisions/${version}`, signal),
    retry: false,
  })
  return <div className="space-y-2 rounded-md border p-2">
    <p className="text-sm font-medium">历史记录 · 第 {version} 版</p>
    {result.data && <p className="text-xs text-muted-foreground">{dateFormat.format(new Date(result.data.created_at))} · {result.data.actor_name || '未知操作者'}</p>}
    <ErrorNotification message={result.error?.message} />
    {result.isLoading && <p role="status">正在读取历史…</p>}
    {result.data?.reason && <p className="text-sm text-muted-foreground">{result.data.reason}</p>}
    {result.data && (result.data.body === null ? <p className="text-sm">此版本撤回了正文。</p>
      : <VditorMarkdownViewer markdown={result.data.body} />)}
    {result.isError && <Button size="sm" variant="outline" onClick={() => void result.refetch()}>重试历史版本</Button>}
  </div>
}

function TimelineHistory({ endpoint }: { endpoint: string }) {
  const result = useInfiniteQuery({
    queryKey: ['timeline-revisions', endpoint],
    initialPageParam: '',
    queryFn: ({ pageParam }) => api.get<Page<Revision>>(`${endpoint}/revisions?${new URLSearchParams({
      limit: '5', ...(pageParam ? { cursor: pageParam } : {}),
    })}`),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  return (
    <div className="space-y-2">
      <ErrorNotification message={result.error?.message} />
      {result.isLoading && <p role="status">正在读取历史…</p>}
      {result.data?.pages.flatMap((page) => page.items).map((revision) => (
        <details key={revision.version} className="rounded-md border p-2">
          <summary className="cursor-pointer text-sm">
            第 {revision.version} 版 · {dateFormat.format(new Date(revision.created_at))} · {revision.actor_name || '未知操作者'}
          </summary>
          {revision.reason && <p className="text-sm text-muted-foreground">{revision.reason}</p>}
          {revision.body === null ? <p className="text-sm">此版本撤回了正文。</p>
            : <VditorMarkdownViewer markdown={revision.body} />}
        </details>
      ))}
      {result.hasNextPage && <Button size="sm" variant="outline" disabled={result.isFetchingNextPage}
        onClick={() => void result.fetchNextPage()}>更早版本</Button>}
      {result.isError && <Button size="sm" variant="outline" onClick={() => void result.refetch()}>重试</Button>}
    </div>
  )
}

function TimelineChange({ endpoint, mode, detail, actorIsAuthor, onSaved }: {
  endpoint: string; mode: 'revise' | 'withdraw'; detail: EntryDetail; actorIsAuthor: boolean; onSaved: () => void
}) {
  const [body, setBody] = useState(detail.body ?? '')
  const [reason, setReason] = useState('')
  const [uploading, setUploading] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const lastRequest = useRef<{ payload: string; id: string } | null>(null)
  const lookup = useProjectCompletion(detail.project_id)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (pending || uploading || detail.version === null || (!actorIsAuthor && !reason.trim()) || (mode === 'revise' && !body.trim())) return
    const payload = { expected_version: detail.version, reason: reason.trim() || null,
      ...(mode === 'revise' ? { body } : {}) }
    const signature = JSON.stringify(payload)
    const requestId = lastRequest.current?.payload === signature ? lastRequest.current.id : crypto.randomUUID()
    lastRequest.current = { payload: signature, id: requestId }
    setPending(true)
    setError(null)
    try {
      const request = { ...payload, request_id: requestId }
      if (mode === 'revise') await api.patch(endpoint, request)
      else await api.post(`${endpoint}/withdraw`, request)
      onSaved()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '保存失败，请重试')
    } finally {
      setPending(false)
    }
  }

  return (
    <form className="space-y-3" onSubmit={(event) => void submit(event)}>
      {mode === 'revise' && <MarkdownComposer id={`timeline-revise-${detail.id}`} label="修订正文"
        value={body} disabled={pending} onChange={setBody} lookup={lookup}
        upload={projectFileUpload(detail.project_id)} onUploadPending={setUploading} />}
      <Input autoComplete="off" aria-label="操作原因" placeholder={actorIsAuthor ? '操作原因（选填）' : '操作原因（必填）'}
        required={!actorIsAuthor} value={reason} maxLength={512} onChange={(event) => setReason(event.target.value)} />
      {error && <p className="text-sm text-destructive">{error}</p>}
      <DialogFooter>
        <Button type="submit" variant={mode === 'withdraw' ? 'destructive' : 'default'} disabled={pending || uploading}>
          {mode === 'withdraw' ? '确认撤回' : '保存修订'}
        </Button>
      </DialogFooter>
    </form>
  )
}

function eventAppearance(type: string | null, legacyAction?: unknown) {
  const [entity, event] = (type ?? '').split('.')
  const action = type === 'legacy.activity' ? legacyAction : event
  const subject = entity === 'task' ? '任务' : entity === 'requirement' ? '需求' : '工作项'
  switch (action) {
    case 'create': return { icon: CirclePlus, label: `创建${subject}` }
    case 'update': return { icon: Pencil, label: `更新${subject}` }
    case 'delete': return { icon: Trash2, label: `删除${subject}` }
    case 'restore': return { icon: History, label: `恢复${subject}` }
    case 'status': case 'status_changed': return { icon: Activity, label: `变更${subject}状态` }
    case 'assign': return { icon: UserPlus, label: '指派任务' }
    case 'claim': case 'claimed': return { icon: UserCheck, label: '认领任务' }
    case 'unassign': return { icon: UserMinus, label: '解除指派' }
    case 'reference': return { icon: Link2, label: '更新引用' }
    case 'blocker': case 'blockers_changed': return { icon: GitPullRequestArrow, label: '更新需求的前置关系' }
    default: return { icon: SquareStack, label: '系统记录' }
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
  const excerpt = reply.withdrawn ? '原记录已撤回'
    : reply.kind === 'system' ? eventAppearance(reply.event_type).label : reply.body_preview ?? '原记录'
  return [reply.actor_name, excerpt, reply.revised && !reply.withdrawn && '已修订'].filter(Boolean).join(' · ')
}

function TimelineActor({ projectId, actorId, fallback, avatar, isAgent }: {
  projectId: string; actorId: string | null; fallback?: string | null; avatar?: string | null; isAgent?: boolean
}) {
  const path = actorId ? projectResourceHref(projectId, 'people', actorId) : null
  const { data: person, isError } = useQuery({
    queryKey: ['project-person', projectId, actorId],
    queryFn: ({ signal }) => api.get<CompletionCandidate>(path!, signal),
    enabled: !!path,
    staleTime: 60_000,
    retry: false,
  })
  if (!actorId) return <span className="inline-flex items-center gap-2 text-sm">
    <span className="grid size-6 place-items-center rounded-full bg-muted text-muted-foreground"><SquareStack className="size-3.5" aria-hidden="true" /></span>系统
  </span>
  const profile = !isError && person?.href === path ? person : null
  const name = profile?.label || fallback || '历史人员'
  const identity = <>
    <span aria-hidden="true" className="inline-flex shrink-0"><UserAvatar user={{ id: actorId, username: name, avatar }} className="size-6" /></span>
    <span className="min-w-0 break-words">{name}</span>
    {(profile ? profile.kind === 'agent' : isAgent) && <span className="text-xs font-normal text-muted-foreground">Agent</span>}
  </>
  const style = 'inline-flex min-w-0 items-center gap-2 text-sm font-medium'
  return path && profile ? <Link to={path} className={style + ' hover:underline'}>{identity}</Link>
    : <span className={style}>{identity}</span>
}

function TimelineRecord({
  entry, projectId, url, queryKey, focused, historicalVersion, linkToEntry, onReply, canModerate,
}: {
  entry: TimelineEntry
  projectId: string
  url: string
  queryKey: readonly string[]
  focused: boolean
  historicalVersion: string | null
  linkToEntry: (entryId: string) => string
  onReply?: (entry: TimelineEntry) => void
  canModerate: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const [action, setAction] = useState<'history' | 'revise' | 'withdraw' | null>(null)
  const { user } = useAuth()
  const client = useQueryClient()
  const endpoint = `${url}/${encodeURIComponent(entry.id)}`
  const actorIsAuthor = !!user && user.id === entry.actor_id
  const canManage = entry.kind === 'manual' && !entry.withdrawn && !!onReply && (actorIsAuthor || canModerate)
  const showBody = !entry.withdrawn && entry.kind === 'manual' && (expanded || (focused && !historicalVersion))
  const detail = useQuery({
    queryKey: [...queryKey, 'detail', entry.id],
    queryFn: ({ signal }) => api.get<EntryDetail>(endpoint, signal),
    enabled: showBody || action === 'revise' || action === 'withdraw',
    retry: false,
  })
  const currentDetail = detail.data?.project_id === entry.project_id
    && detail.data.requirement_id === entry.requirement_id && detail.data.id === entry.id
    ? detail.data
    : null
  const body = detail.isError || currentDetail?.withdrawn ? null : currentDetail?.body
  const status = statusChange(entry.event_data, entry.event_type)
  const withdrawn = entry.withdrawn || currentDetail?.withdrawn
  const system = entry.kind === 'system'
  const node = system ? eventAppearance(entry.event_type, entry.event_data?.action)
    : withdrawn ? { icon: RotateCcw, label: '已撤回记录' }
    : entry.reply_to ? { icon: Reply, label: '回复' } : { icon: MessageSquare, label: '人工记录' }
  const NodeIcon = node.icon
  const time = <time dateTime={entry.occurred_at}>{dateFormat.format(new Date(entry.occurred_at))}</time>

  return (
    <li
      id={`timeline-${entry.id}`}
      tabIndex={focused ? -1 : undefined}
      className="relative grid min-w-0 grid-cols-[1.75rem_minmax(0,1fr)] items-start gap-x-3 pb-4 last:pb-0 focus:outline-none"
    >
      <span className={`timeline-node relative grid size-7 place-items-center rounded-full bg-muted text-muted-foreground ring-[3px] ring-background ${focused ? 'outline outline-1 outline-foreground' : ''}`}
        role="img" aria-label={node.label} title={node.label}><NodeIcon className="size-3.5" aria-hidden="true" /></span>
      <div className={`min-w-0 space-y-1.5 rounded-md ${focused ? 'bg-muted/50 px-2 pb-2' : ''}`}>
        <div className="flex min-h-7 items-center text-sm font-semibold tabular-nums">
          {focused ? time : <Link to={linkToEntry(entry.id)} className="rounded-sm underline-offset-4 hover:underline" title="定位记录">{time}</Link>}
        </div>
        <div className="flex"><TimelineActor projectId={projectId} actorId={entry.actor_id} fallback={entry.actor_name}
          avatar={entry.actor_avatar} isAgent={entry.actor_is_agent} /></div>
        {(system || entry.source_task || entry.revised && !withdrawn) && <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          {system && <span className="min-w-0 break-words">
            {typeof entry.event_data?.summary === 'string' ? entry.event_data.summary : node.label}{status && ` · ${status}`}</span>}
          {entry.source_task && <Link className="text-xs text-muted-foreground hover:underline" to={projectResourceHref(projectId, 'tasks', entry.source_task)}>
            {entry.source_task}
          </Link>}
          {entry.revised && !entry.withdrawn && <span className="text-xs text-muted-foreground">已修订</span>}
          {system && onReply && <Button type="button" size="icon-sm" variant="ghost" aria-label="回复" title="回复"
            className="size-7 text-muted-foreground" onClick={() => onReply(entry)}><Reply className="size-3.5" /></Button>}
        </div>}
        {entry.reply_to && <Link
          to={linkToEntry(entry.reply_to.entry_id)}
          className="block max-w-full truncate border-s-2 border-border ps-2 text-sm text-muted-foreground hover:underline"
        >
          回复：{replyLabel(entry.reply_to)}
        </Link>}
        {historicalVersion && entry.kind === 'manual' ? <TimelineRevisionPreview endpoint={endpoint} version={historicalVersion} />
          : entry.withdrawn || currentDetail?.withdrawn ? <p className="text-sm text-muted-foreground">此记录已撤回</p>
          : system ? null
            : showBody && body !== undefined && body !== null ? <VditorMarkdownViewer markdown={body} />
              : <p className="whitespace-pre-wrap break-words text-sm">{entry.body_preview}</p>}
        <ErrorNotification message={detail.isError && showBody ? '无法读取记录正文，请重试。' : null} />
        {!system && <div className="-ms-2 flex flex-wrap items-center gap-x-1 gap-y-0.5 text-muted-foreground [&_button]:h-7 [&_button]:px-2 [&_button]:text-xs">
          {showBody && detail.isFetching && <span role="status" className="text-xs text-muted-foreground">加载正文…</span>}
          {showBody && detail.isError && <Button type="button" size="sm" variant="ghost" onClick={() => void detail.refetch()}>重试正文</Button>}
          {!entry.withdrawn && entry.kind === 'manual' && !focused && (
            <Button type="button" size="sm" variant="ghost" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
              {expanded ? '收起正文' : '展开正文'}
            </Button>
          )}
          {onReply && <Button type="button" size="sm" variant="ghost" onClick={() => onReply(entry)}>回复</Button>}
          {entry.kind === 'manual' && (entry.revised || entry.withdrawn) &&
            <Button size="sm" variant="ghost" onClick={() => setAction('history')}>历史记录</Button>}
          {canManage && <Button size="sm" variant="ghost" onClick={() => setAction('revise')}>修订</Button>}
          {canManage && <Button size="sm" variant="ghost" onClick={() => setAction('withdraw')}>撤回</Button>}
        </div>}
      </div>
      {action && <Dialog open onOpenChange={(open) => { if (!open) setAction(null) }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{action === 'history' ? '历史记录' : action === 'revise' ? '修订记录' : '撤回记录'}</DialogTitle>
            <DialogDescription>原文与操作历史会保留。</DialogDescription>
          </DialogHeader>
          {action === 'history' ? <TimelineHistory endpoint={endpoint} /> : currentDetail ? <TimelineChange
            endpoint={endpoint} mode={action} detail={currentDetail} actorIsAuthor={actorIsAuthor}
            onSaved={() => {
              setAction(null)
              void client.invalidateQueries({ queryKey })
              void client.invalidateQueries({ queryKey: ['timeline-revisions', endpoint] })
            }}
          /> : detail.isError
            ? <Button variant="outline" onClick={() => void detail.refetch()}>重新读取记录</Button>
            : <p role="status">正在读取记录…</p>}
        </DialogContent>
      </Dialog>}
    </li>
  )
}

export function RequirementTimeline({ projectId, requirementId, canWrite, canModerate, tasks = [], participants = [] }: {
  projectId: string
  requirementId: string
  canWrite: boolean
  canModerate: boolean
  tasks?: TimelineTask[]
  participants?: { id: string; name: string }[]
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const { hash } = useLocation()
  const anchor = searchParams.get('entry') ?? (hash.startsWith('#timeline-') ? hash.slice(10) : null)
  const versionParam = searchParams.get('timelineVersion')
  const historicalVersion = versionParam && /^[1-9]\d{0,9}$/.test(versionParam) && Number(versionParam) <= 2_147_483_647
    ? versionParam : null
  const queryKey = ['requirement-timeline', projectId, requirementId] as const
  const url = `${projectResourceHref(projectId, 'requirements', requirementId)}/timeline`
  const lookup = useProjectCompletion(projectId)
  const qc = useQueryClient()
  const [draft, setDraft] = useState('')
  const [sourceTask, setSourceTask] = useState('')
  const [filters, setFilters] = useState<TimelineFilters>({})
  const [reply, setReply] = useState<TimelineEntry | null>(null)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const previousRequest = useRef<AppendInput | null>(null)

  const history = useInfiniteQuery({
    queryKey: [...queryKey, 'history', filters],
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: '20', ...filters })
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
    params.delete('timelineVersion')
    params.set('tab','timeline')
    if (entryId) params.set('entry', entryId)
    else params.delete('entry')
    return params
  }

  function selectReply(entry: TimelineEntry) {
    setReply(entry)
    setSourceTask(tasks.find(task => task.id === entry.source_task)?.id ?? '')
    document.getElementById('timeline-draft')?.focus()
  }

  async function append(event: FormEvent) {
    event.preventDefault()
    if (!canWrite || saving || uploading || !draft.trim()) return
    const replyTo = reply?.id ?? null
    const prior = previousRequest.current
    const requestId = prior?.body === draft && prior.replyTo === replyTo && prior.sourceTask === sourceTask ? prior.requestId : crypto.randomUUID()
    previousRequest.current = { body: draft, replyTo, sourceTask, requestId }
    setSaving(true)
    setSaveError(null)
    try {
      const receipt = await api.post<{ entry_id: string }>(url, {
        body: draft,
        ...(sourceTask && { source_task: sourceTask }),
        reply_to: replyTo,
        request_id: requestId,
      })
      previousRequest.current = null
      setDraft('')
      setSourceTask('')
      setReply(null)
      setSearchParams((current) => {
        const params = new URLSearchParams(current)
        params.delete('timelineVersion')
        params.set('entry', receipt.entry_id)
        return params
      }, { replace: true })
      void qc.invalidateQueries({ queryKey })
      void qc.invalidateQueries({ queryKey: ['requirements', projectId] })
      void qc.invalidateQueries({ queryKey: ['requirement', requirementId] })
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
        <div className="flex flex-wrap items-center gap-2">
        {tasks.length > 0 && <label className="flex items-center gap-2 text-sm text-muted-foreground">来源任务
          <select className="h-8 max-w-64 rounded-md border bg-background px-2 text-foreground" value={sourceTask}
            disabled={saving} onChange={event => setSourceTask(event.target.value)}>
            <option value="">无</option>{tasks.map(task => <option key={task.id} value={task.id}>{task.id} · {task.title}</option>)}
          </select></label>}
        <Button type="submit" size="sm" disabled={saving || uploading || !draft.trim()}>
          {saving ? '发布中…' : reply ? '发布回复' : '发布记录'}
        </Button></div>
      </form>}
      <TimelineFilterForm tasks={tasks} actors={participants} onApply={next => {
        setFilters(next)
        if (anchor) setSearchParams(paramsForEntry(null))
      }} />
      {isLoading && <p role="status" className="text-sm text-muted-foreground">加载时间轴…</p>}
      {!isLoading && !loadError && !visibleEntries.length && <p className="text-sm text-muted-foreground">暂无记录</p>}
      {loadError && (anchor || !history.isFetchNextPageError) && (
        <Button type="button" size="sm" variant="outline" onClick={() => void (anchor ? context.refetch() : history.refetch())}>重试加载</Button>
      )}
      <ol className="work-timeline" aria-label="时间轴记录">
        {visibleEntries.map((entry) => <TimelineRecord
          key={entry.id}
          entry={entry}
          projectId={projectId}
          url={url}
          queryKey={queryKey}
          canModerate={canModerate}
          focused={entry.id === anchor}
          historicalVersion={entry.id === anchor ? historicalVersion : null}
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
